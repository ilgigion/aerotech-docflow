from __future__ import annotations


class UpdaterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RollbackFailedError(UpdaterError):
    def __init__(self, update_error: Exception, rollback_error: Exception) -> None:
        super().__init__(
            "ROLLBACK_FAILED",
            "Обновление и автоматический откат завершились ошибкой. "
            f"Ошибка обновления: {update_error}. Ошибка отката: {rollback_error}",
        )
        self.update_error = update_error
        self.rollback_error = rollback_error


class UpdateFailedRestoredError(UpdaterError):
    def __init__(self, update_error: Exception) -> None:
        code = update_error.code if isinstance(update_error, UpdaterError) else "UPDATE_FAILED"
        super().__init__(code, str(update_error))
        self.update_error = update_error
