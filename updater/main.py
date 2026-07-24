from __future__ import annotations

import logging
import sys

from updater import console
from updater.errors import RollbackFailedError, UpdateFailedRestoredError, UpdaterError
from updater.transaction import UpdateTransaction
from updater.windows import UpdaterPaths, configure_logging, ensure_administrator, single_instance


def run() -> int:
    console.prepare_console()
    print("Aerotech Docflow Updater")
    print()
    logger: logging.Logger | None = None
    paths: UpdaterPaths | None = None
    try:
        if len(sys.argv) != 1:
            raise UpdaterError("UNSUPPORTED_ARGUMENT", "Updater не поддерживает аргументы командной строки.")
        ensure_administrator()
        paths = UpdaterPaths.production()
        logger = configure_logging(paths.updater_log)
        logger.info("Updater started")
        with single_instance():
            transaction = UpdateTransaction(paths, logger)
            console.activity("Проверка незавершённого предыдущего обновления...")
            transaction.recover_interrupted_update()
            console.activity("Проверка/восстановление предыдущего обновления завершены.")
            prepared = transaction.prepare(report=console.activity)
            console.ok(f"Установленная версия: {prepared.installed.version}")
            console.ok(f"Найден пакет: {prepared.package.zip_path.name}")
            console.ok(f"Версия пакета: {prepared.package.version.version}")
            console.ok("Архив ZIP проверен")
            console.ok("Манифест проверен")
            console.ok("Конфигурация найдена")
            console.ok("Предварительная проверка пройдена")
            console.ok("Сканирование сейчас не выполняется")
            print()
            print(
                f"Всё готово к обновлению {prepared.installed.version} "
                f"→ {prepared.package.version.version}."
            )
            console.wait_for_key(
                "Нажмите любую клавишу, чтобы начать.",
                require_interactive=True,
            )
            print()
            result = transaction.apply(
                prepared,
                progress=console.step,
                detail=console.detail,
            )
            print()
            print("Обновление успешно установлено.")
            print(f"Версия: {result.installed_version}")
            print("Сервис работает.")
            if result.cleanup_warning:
                print(f"Предупреждение очистки: {result.cleanup_warning}")
                print("Код: POST_INSTALL_CLEANUP_WARNING")
            logger.info("Updater finished successfully version=%s", result.installed_version)
            return 0
    except UpdateFailedRestoredError as exc:
        if logger:
            logger.error("Update failed but old version restored code=%s reason=%s", exc.code, exc.message)
        print("Обновление не установлено.")
        print("Предыдущая версия восстановлена и работает.")
        print(f"Причина: {exc.message}")
        print(f"Код ошибки: {exc.code}")
        return 2
    except RollbackFailedError as exc:
        if logger:
            logger.critical("Update and rollback failed: %s", exc, exc_info=True)
        print("Обновление и автоматический откат завершились ошибкой.")
        print("Необходимо вмешательство администратора.")
        print(f"Код ошибки: {exc.code}")
        return 3
    except UpdaterError as exc:
        if logger:
            logger.error("Updater refused code=%s reason=%s", exc.code, exc.message, exc_info=True)
        print("Обновление не установлено.")
        print(f"Причина: {exc.message}")
        print(f"Код ошибки: {exc.code}")
        return 1
    except Exception as exc:
        if logger:
            logger.critical("Unexpected updater failure: %s", exc, exc_info=True)
        print("Обновление не установлено.")
        print(f"Непредвиденная ошибка: {exc}")
        print("Код ошибки: UNEXPECTED_ERROR")
        return 4
    finally:
        if paths:
            print()
            print(f"Подробный лог: {paths.updater_log}")
        console.wait_for_key()


if __name__ == "__main__":
    raise SystemExit(run())
