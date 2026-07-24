from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Callable

from updater.errors import (
    RollbackFailedError,
    UpdateFailedRestoredError,
    UpdaterError,
)
from updater.models import ValidatedPackage, VersionInfo
from updater.package import extract_package, select_newest_package
from updater.windows import (
    UpdaterPaths,
    assert_docflow_process_stopped,
    assert_scanner_idle,
    collect_service_diagnostics,
    incoming_from_config,
    run_preflight,
    service_state,
    start_service,
    stop_service,
    wait_health,
)


@dataclass(frozen=True)
class PreparedUpdate:
    installed: VersionInfo
    package: ValidatedPackage
    incoming: Path
    service_xml_sha256: str


@dataclass(frozen=True)
class UpdateResult:
    previous_version: str
    installed_version: str
    cleanup_warning: str | None = None


def read_version_file(path: Path) -> VersionInfo:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdaterError("INVALID_VERSION_FILE", f"Не удалось прочитать {path}: {exc}") from exc
    return VersionInfo.from_json(payload)


def write_version_file_atomic(path: Path, version: VersionInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(version.to_json(), ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return path.is_symlink()
    except OSError:
        return False
    return bool(attributes & 0x400)


def _assert_exact_path(actual: Path, expected: Path) -> Path:
    actual = actual.resolve(strict=False)
    expected = expected.resolve(strict=False)
    if os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
        raise UpdaterError("UNSAFE_FILESYSTEM_PATH", f"Операция запрещена вне пути: {expected}")
    if actual.exists() and _is_reparse_point(actual):
        raise UpdaterError("UNSAFE_FILESYSTEM_PATH", f"Reparse point запрещён: {actual}")
    return actual


def _remove_managed(path: Path, expected: Path) -> None:
    path = _assert_exact_path(path, expected)
    if path.exists():
        shutil.rmtree(path)


def _service_xml_sha256(path: Path) -> str:
    if path.is_symlink() or _is_reparse_point(path):
        raise UpdaterError("SERVICE_XML_UNSAFE", f"WinSW XML не должен быть ссылкой: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise UpdaterError("SERVICE_XML_MISSING", f"Рабочий WinSW XML не найден: {path}") from exc
    if not path.is_file() or size == 0 or size > 1024 * 1024:
        raise UpdaterError("SERVICE_XML_INVALID", f"Некорректный размер рабочего WinSW XML: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise UpdaterError("SERVICE_XML_READ_FAILED", f"Не удалось прочитать WinSW XML: {path}") from exc
    return digest.hexdigest()


def _preserve_service_xml(source: Path, destination: Path, expected_sha256: str) -> None:
    if _service_xml_sha256(source) != expected_sha256:
        raise UpdaterError("SERVICE_XML_CHANGED", "Рабочий WinSW XML изменился во время обновления.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if _service_xml_sha256(temporary) != expected_sha256:
            raise UpdaterError("SERVICE_XML_COPY_MISMATCH", "Копия рабочего WinSW XML имеет другой SHA-256.")
        os.replace(temporary, destination)
        if _service_xml_sha256(destination) != expected_sha256:
            raise UpdaterError("SERVICE_XML_COPY_MISMATCH", "Установленный WinSW XML имеет другой SHA-256.")
    finally:
        temporary.unlink(missing_ok=True)


class UpdateTransaction:
    def __init__(self, paths: UpdaterPaths, logger: logging.Logger) -> None:
        self.paths = paths
        self.logger = logger

    @property
    def installed_version_path(self) -> Path:
        return self.paths.install_dir / "version.json"

    @property
    def installed_executable(self) -> Path:
        return self.paths.install_dir / "app" / "aerotech-docflow.exe"

    def recover_interrupted_update(self) -> None:
        rollback = _assert_exact_path(self.paths.rollback_dir, self.paths.rollback_dir)
        if not rollback.exists():
            return
        self.logger.warning("Found leftover rollback directory: %s", rollback)
        install = _assert_exact_path(self.paths.install_dir, self.paths.install_dir)
        if install.exists():
            try:
                installed = read_version_file(install / "version.json")
                if service_state() == 4:
                    wait_health(str(installed.version), attempts=2, interval=1)
                    _remove_managed(rollback, self.paths.rollback_dir)
                    self.logger.info("Removed verified leftover rollback; active version=%s", installed.version)
                    return
            except Exception as exc:
                self.logger.warning("Active installation is not healthy while rollback exists: %s", exc)

        try:
            if service_state() not in {None, 1}:
                stop_service()
            if install.exists():
                _remove_managed(install, self.paths.install_dir)
            os.replace(rollback, install)
            restored = read_version_file(install / "version.json")
            start_service()
            wait_health(str(restored.version))
            self.logger.info("Recovered interrupted update; restored version=%s", restored.version)
        except Exception as exc:
            raise UpdaterError(
                "INTERRUPTED_UPDATE_RECOVERY_FAILED",
                f"Не удалось восстановить незавершённое обновление: {exc}",
            ) from exc

    def prepare(
        self,
        *,
        report: Callable[[str], None] | None = None,
    ) -> PreparedUpdate:
        def emit(message: str) -> None:
            self.logger.info("Preparation detail: %s", message)
            if report is not None:
                report(message)

        emit("Чтение version.json установленной версии...")
        installed = read_version_file(self.installed_version_path)
        emit(f"Установленная версия определена: {installed.version}.")
        emit("Проверка установленного EXE, рабочего config.toml и WinSW XML...")
        if not self.installed_executable.is_file():
            raise UpdaterError("INSTALLATION_INVALID", f"Приложение не найдено: {self.installed_executable}")
        if not self.paths.config_path.is_file():
            raise UpdaterError("CONFIG_NOT_FOUND", f"Рабочий конфиг не найден: {self.paths.config_path}")
        service_xml = self.paths.install_dir / "service" / "docflow-service.xml"
        service_xml_sha256 = _service_xml_sha256(service_xml)
        emit(f"Рабочий WinSW XML найден, SHA-256={service_xml_sha256}.")

        def report_invalid(path: Path, error: UpdaterError) -> None:
            self.logger.warning("Rejected package=%s code=%s reason=%s", path, error.code, error.message)

        emit(f"Поиск и проверка ZIP в {self.paths.temp_root}...")
        package = select_newest_package(
            self.paths.temp_root,
            installed,
            report_invalid=report_invalid,
        )
        emit(f"Выбран пакет {package.zip_path.name}; manifest и SHA-256 корректны.")
        emit(f"Распаковка пакета в {self.paths.unpacked_dir}...")
        extract_package(package, self.paths.unpacked_dir)
        new_executable = self.paths.unpacked_dir / "app" / "aerotech-docflow.exe"
        emit(f"Запуск preflight нового EXE с рабочим config.toml: {new_executable}")
        run_preflight(new_executable, self.paths.config_path)
        emit("Preflight новой версии успешно завершён.")
        emit("Чтение фактического incoming из рабочего config.toml...")
        incoming = incoming_from_config(self.installed_executable, self.paths.config_path)
        emit(f"Проверка NAPS2 и scanner lock в {incoming}...")
        assert_scanner_idle(incoming)
        emit("Подготовка завершена; служба пока не остановлена.")
        self.logger.info(
            "Preparation passed old_version=%s new_version=%s package=%s",
            installed.version,
            package.version.version,
            package.zip_path,
        )
        return PreparedUpdate(
            installed=installed,
            package=package,
            incoming=incoming,
            service_xml_sha256=service_xml_sha256,
        )

    def _record_service_diagnostics(
        self,
        stage: str,
        *,
        detail: Callable[[str], None] | None = None,
        error: bool = False,
    ) -> dict[str, object]:
        try:
            diagnostics = collect_service_diagnostics(self.paths)
        except Exception as exc:
            self.logger.exception("Failed to collect service diagnostics stage=%s", stage)
            if detail is not None:
                detail(f"Диагностика службы недоступна: {exc}")
            return {"diagnostic_error": str(exc)}
        message = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True, default=str)
        if error:
            self.logger.error("Service diagnostics stage=%s data=%s", stage, message)
        else:
            self.logger.info("Service diagnostics stage=%s data=%s", stage, message)
        if detail is not None:
            detail(f"WinSW EXE: {diagnostics.get('wrapper_path')}")
            detail(f"WinSW XML: {diagnostics.get('xml_path')}")
            scm = diagnostics.get("scm")
            if isinstance(scm, dict):
                detail(f"SCM ImagePath: {scm.get('image_path')}")
                detail(f"SCM StartName: {scm.get('start_name')}")
            xml = diagnostics.get("xml")
            if isinstance(xml, dict):
                detail(f"XML executable: {xml.get('executable')}")
                detail(f"XML arguments: {xml.get('arguments')}")
                detail(f"XML workingdirectory: {xml.get('workingdirectory')}")
                detail(f"XML logpath: {xml.get('logpath')}")
            detail(f"SCM state: {diagnostics.get('service_state', diagnostics.get('service_state_error'))}")
            processes = diagnostics.get("relevant_processes")
            detail(f"Процессы WinSW/Docflow: {processes if processes else 'не обнаружены'}")
        return diagnostics

    def apply(
        self,
        prepared: PreparedUpdate,
        *,
        progress: Callable[[int, int, str], None],
        detail: Callable[[str], None] | None = None,
    ) -> UpdateResult:
        total_steps = 14

        def emit(message: str) -> None:
            self.logger.info("Update detail: %s", message)
            if detail is not None:
                detail(message)

        def advance(number: int, message: str) -> None:
            self.logger.info("Update step=%s/%s message=%s", number, total_steps, message)
            progress(number, total_steps, message)

        advance(1, "Пакет распакован, manifest и preflight уже проверены.")
        advance(2, "Повторная проверка NAPS2 и scanner lock после подтверждения...")
        # Required second check: the operator may have started a scan while the
        # updater was waiting for the confirmation key.
        assert_scanner_idle(prepared.incoming)
        emit("NAPS2 не запущен; scanner lock отсутствует.")
        install = _assert_exact_path(self.paths.install_dir, self.paths.install_dir)
        rollback = _assert_exact_path(self.paths.rollback_dir, self.paths.rollback_dir)
        unpacked = _assert_exact_path(self.paths.unpacked_dir, self.paths.unpacked_dir)
        if rollback.exists():
            raise UpdaterError("ROLLBACK_ALREADY_EXISTS", f"Rollback уже существует: {rollback}")
        if not unpacked.is_dir():
            raise UpdaterError("UNPACKED_PACKAGE_MISSING", f"Распакованный пакет отсутствует: {unpacked}")

        shutdown_started = False
        old_moved = False
        committed = False
        try:
            advance(3, "Отправка команды остановки Windows-службы...")
            shutdown_started = True
            stop_service()
            advance(4, "Проверка остановки aerotech-docflow.exe...")
            assert_docflow_process_stopped()
            emit("Процесс aerotech-docflow.exe остановлен.")
            advance(5, "Контрольная проверка сканера и рабочего WinSW XML...")
            assert_scanner_idle(prepared.incoming)
            current_service_xml = install / "service" / "docflow-service.xml"
            if _service_xml_sha256(current_service_xml) != prepared.service_xml_sha256:
                raise UpdaterError("SERVICE_XML_CHANGED", "Рабочий WinSW XML изменился после подготовки.")
            emit(f"WinSW XML подтверждён, SHA-256={prepared.service_xml_sha256}.")

            advance(6, "Перемещение старой установки в rollback...")
            os.replace(install, rollback)
            old_moved = True
            emit(f"Rollback: {rollback}")

            advance(7, "Перемещение файлов новой версии в Program Files...")
            os.replace(unpacked, install)
            emit(f"Новая установка: {install}")
            advance(8, "Восстановление рабочего WinSW XML без изменений...")
            _preserve_service_xml(
                rollback / "service" / "docflow-service.xml",
                install / "service" / "docflow-service.xml",
                prepared.service_xml_sha256,
            )
            self.logger.info("Preserved WinSW service XML sha256=%s", prepared.service_xml_sha256)
            emit("Рабочий WinSW XML восстановлен и повторно проверен по SHA-256.")

            advance(9, "Проверка путей WinSW, XML и учётной записи службы...")
            self._record_service_diagnostics("before-start", detail=detail)
            advance(10, "Вызов sc.exe start AerotechDocflow...")
            start_service(report=emit)
            advance(11, "Windows Service Control Manager подтвердил RUNNING.")
            advance(12, "Проверка процессов WinSW и aerotech-docflow.exe...")
            self._record_service_diagnostics("after-start", detail=detail)
            advance(13, "Ожидание локального /health новой версии...")
            wait_health(str(prepared.package.version.version), report=emit)
            committed = True
            self.logger.info(
                "Update committed old_version=%s new_version=%s",
                prepared.installed.version,
                prepared.package.version.version,
            )
        except Exception as update_error:
            self.logger.exception("Update failed; starting rollback")
            if old_moved and install.exists():
                self._record_service_diagnostics("update-failure-before-rollback", detail=detail, error=True)
            if not shutdown_started:
                raise
            try:
                emit("Rollback: остановка неуспешной новой службы.")
                if service_state() not in {None, 1}:
                    stop_service()
                if old_moved:
                    emit("Rollback: удаление новой установки и возврат старого каталога.")
                    if install.exists():
                        _remove_managed(install, self.paths.install_dir)
                    os.replace(rollback, install)
                emit("Rollback: запуск предыдущей версии службы.")
                start_service(report=lambda message: emit(f"Rollback: {message}"))
                wait_health(
                    str(prepared.installed.version),
                    report=lambda message: emit(f"Rollback: {message}"),
                )
                self.logger.info("Rollback passed health version=%s", prepared.installed.version)
            except Exception as rollback_error:
                self.logger.exception("Rollback failed")
                raise RollbackFailedError(update_error, rollback_error) from rollback_error
            raise UpdateFailedRestoredError(update_error) from update_error

        cleanup_warning: str | None = None
        if committed:
            advance(14, "Очистка rollback, ZIP и временных файлов...")
            failures: list[str] = []
            try:
                _remove_managed(rollback, self.paths.rollback_dir)
            except Exception as exc:
                failures.append(f"rollback: {exc}")
            try:
                Path(prepared.package.zip_path).unlink()
            except Exception as exc:
                failures.append(f"ZIP: {exc}")
            if unpacked.exists():
                try:
                    _remove_managed(unpacked, self.paths.unpacked_dir)
                except Exception as exc:
                    failures.append(f"unpacked: {exc}")
            if failures:
                cleanup_warning = "; ".join(failures)
                self.logger.warning("Post-install cleanup incomplete: %s", cleanup_warning)
        return UpdateResult(
            previous_version=str(prepared.installed.version),
            installed_version=str(prepared.package.version.version),
            cleanup_warning=cleanup_warning,
        )
