"""Хранилище заданий в SQLite."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from app.config import settings
from app.schemas import JobResponse, JobStatus, ScanRequest


class IdempotencyConflictError(RuntimeError):
    """
    Один external_request_id был использован
    для двух разных запросов.
    """


@dataclass(frozen=True)
class CreateJobResult:
    """Результат идемпотентного создания задания."""

    job: JobResponse
    created: bool


class JobRepository:
    """Управляет заданиями, сохранёнными в SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = RLock()

        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        """Создать соединение с SQLite."""

        connection = sqlite3.connect(
            self._database_path,
            timeout=30,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialize_database(self) -> None:
        """Создать базу, таблицу и выполнить простую миграцию."""

        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connect() as connection:
            connection.execute(
                "PRAGMA journal_mode = WAL"
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    request_id TEXT PRIMARY KEY,
                    task_id INTEGER NOT NULL,

                    document_type TEXT NOT NULL,
                    document_number TEXT NOT NULL,
                    user_code TEXT NOT NULL,

                    context_json TEXT NOT NULL,
                    status TEXT NOT NULL,

                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,

                    source_file TEXT,
                    result_file TEXT,
                    result_filename TEXT,
                    sha256 TEXT,

                    error TEXT
                )
                """
            )

            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(jobs)"
                ).fetchall()
            }

            # Миграция существующей базы.
            if "external_request_id" not in columns:
                connection.execute(
                    """
                    ALTER TABLE jobs
                    ADD COLUMN external_request_id TEXT
                    """
                )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_jobs_external_request_id
                ON jobs(external_request_id)
                WHERE external_request_id IS NOT NULL
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_created_at
                ON jobs(created_at)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_task_id
                ON jobs(task_id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_status
                ON jobs(status)
                """
            )

    @staticmethod
    def _row_to_job(
        row: sqlite3.Row,
    ) -> JobResponse:
        """Преобразовать строку SQLite в JobResponse."""

        return JobResponse(
            request_id=UUID(row["request_id"]),
            external_request_id=row["external_request_id"],
            task_id=row["task_id"],
            document_type=row["document_type"],
            document_number=row["document_number"],
            user_code=row["user_code"],
            context=json.loads(row["context_json"]),
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(
                row["created_at"]
            ),
            updated_at=datetime.fromisoformat(
                row["updated_at"]
            ),
            source_file=row["source_file"],
            result_file=row["result_file"],
            result_filename=row["result_filename"],
            sha256=row["sha256"],
            error=row["error"],
        )

    @staticmethod
    def _validate_duplicate_payload(
        existing_job: JobResponse,
        payload: ScanRequest,
    ) -> None:
        """
        Проверить, что повторный запрос содержит те же данные.

        Если external_request_id тот же, а данные отличаются,
        запрос считается конфликтующим.
        """

        is_same_request = (
            existing_job.task_id == payload.task_id
            and existing_job.document_type
            == payload.document_type
            and existing_job.document_number
            == payload.document_number
            and existing_job.user_code
            == payload.user_code
            and existing_job.context == payload.context
        )

        if not is_same_request:
            raise IdempotencyConflictError(
                "external_request_id уже используется "
                "для другого набора данных"
            )

    def create_or_get(
        self,
        payload: ScanRequest,
    ) -> CreateJobResult:
        """
        Создать задание или вернуть существующее.

        Один external_request_id соответствует одному заданию.
        """

        with self._lock:
            existing_job = self.get_by_external_request_id(
                payload.external_request_id
            )

            if existing_job is not None:
                self._validate_duplicate_payload(
                    existing_job=existing_job,
                    payload=payload,
                )

                return CreateJobResult(
                    job=existing_job,
                    created=False,
                )

            now = datetime.now(timezone.utc)

            job = JobResponse(
                request_id=uuid4(),
                external_request_id=(
                    payload.external_request_id
                ),
                task_id=payload.task_id,
                document_type=payload.document_type,
                document_number=payload.document_number,
                user_code=payload.user_code,
                context=payload.context,
                status=JobStatus.ACCEPTED,
                created_at=now,
                updated_at=now,
                source_file=None,
                result_file=None,
                result_filename=None,
                sha256=None,
                error=None,
            )

            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO jobs (
                            request_id,
                            external_request_id,
                            task_id,
                            document_type,
                            document_number,
                            user_code,
                            context_json,
                            status,
                            created_at,
                            updated_at,
                            source_file,
                            result_file,
                            result_filename,
                            sha256,
                            error
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            str(job.request_id),
                            job.external_request_id,
                            job.task_id,
                            job.document_type,
                            job.document_number,
                            job.user_code,
                            json.dumps(
                                job.context,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            job.status.value,
                            job.created_at.isoformat(),
                            job.updated_at.isoformat(),
                            job.source_file,
                            job.result_file,
                            job.result_filename,
                            job.sha256,
                            job.error,
                        ),
                    )

            except sqlite3.IntegrityError:
                # Дополнительная защита на случай,
                # если одинаковые запросы пришли одновременно.
                existing_job = (
                    self.get_by_external_request_id(
                        payload.external_request_id
                    )
                )

                if existing_job is None:
                    raise

                self._validate_duplicate_payload(
                    existing_job=existing_job,
                    payload=payload,
                )

                return CreateJobResult(
                    job=existing_job,
                    created=False,
                )

        return CreateJobResult(
            job=job,
            created=True,
        )

    def create(
        self,
        payload: ScanRequest,
    ) -> JobResponse:
        """
        Создать задание.

        Метод сохранён для совместимости с существующими тестами.
        """

        return self.create_or_get(payload).job

    def get(
        self,
        request_id: UUID,
    ) -> JobResponse | None:
        """Получить задание по request_id."""

        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE request_id = ?
                    """,
                    (
                        str(request_id),
                    ),
                ).fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    def get_by_external_request_id(
        self,
        external_request_id: str,
    ) -> JobResponse | None:
        """Найти задание по ID внешнего запроса."""

        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE external_request_id = ?
                    """,
                    (
                        external_request_id,
                    ),
                ).fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobResponse]:
        """Получить список заданий."""

        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    OFFSET ?
                    """,
                    (
                        limit,
                        offset,
                    ),
                ).fetchall()

        return [
            self._row_to_job(row)
            for row in rows
        ]

    def update_status(
        self,
        request_id: UUID,
        status: JobStatus,
        error: str | None = None,
    ) -> JobResponse | None:
        """Изменить статус задания."""

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET
                        status = ?,
                        error = ?,
                        updated_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        status.value,
                        error,
                        updated_at,
                        str(request_id),
                    ),
                )

                if cursor.rowcount == 0:
                    return None

        return self.get(request_id)

    def set_source_file(
        self,
        request_id: UUID,
        source_file: str,
    ) -> JobResponse | None:
        """Записать первоначальный путь к PDF."""

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET
                        source_file = ?,
                        updated_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        source_file,
                        updated_at,
                        str(request_id),
                    ),
                )

                if cursor.rowcount == 0:
                    return None

        return self.get(request_id)

    def set_archive_result(
        self,
        request_id: UUID,
        result_file: str,
        result_filename: str,
        sha256: str,
    ) -> JobResponse | None:
        """Записать результат архивирования."""

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET
                        result_file = ?,
                        result_filename = ?,
                        sha256 = ?,
                        updated_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        result_file,
                        result_filename,
                        sha256,
                        updated_at,
                        str(request_id),
                    ),
                )

                if cursor.rowcount == 0:
                    return None

        return self.get(request_id)

    def mark_interrupted_jobs_failed(
        self,
    ) -> int:
        """Пометить прерванные задания как failed."""

        interrupted_statuses = (
            JobStatus.ACCEPTED.value,
            JobStatus.WAITING_FOR_FILE.value,
            JobStatus.FILE_RECEIVED.value,
            JobStatus.ARCHIVING.value,
        )

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        placeholders = ", ".join(
            "?"
            for _ in interrupted_statuses
        )

        query = f"""
            UPDATE jobs
            SET
                status = ?,
                error = ?,
                updated_at = ?
            WHERE status IN ({placeholders})
        """

        parameters = (
            JobStatus.FAILED.value,
            (
                "Обработка была прервана "
                "перезапуском backend-сервиса"
            ),
            updated_at,
            *interrupted_statuses,
        )

        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    query,
                    parameters,
                )

                return cursor.rowcount


job_repository = JobRepository(
    database_path=settings.database_path
)