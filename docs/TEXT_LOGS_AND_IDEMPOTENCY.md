# TXT-логи по месяцам и файловая идемпотентность

## Цель

На этом этапе не используем SQLite-журнал сканирования. Вместо этого добавлены две лёгкие вещи:

1. обычные текстовые логи `docflow_YYYY_MM.txt`;
2. файловая идемпотентность через JSON-маркеры по `idempotency_key`.

Очередь и воркер не нужны для текущей физической модели работы: один оператор работает с одним сканером.

## Месячные TXT-логи

По умолчанию логи пишутся в:

```text
D:\incoming\_logs\docflow_2026_07.txt
```

В следующем месяце автоматически появится новый файл:

```text
D:\incoming\_logs\docflow_2026_08.txt
```

Логи подключаются в `document_flow.py` при запуске операции. В файл попадают обычные записи Python logging из модулей `app.document_flow`, `app.scanner`, `app.storage`, `app.locks`, `app.idempotency`.

### Переменные окружения

Отключить TXT-логи:

```powershell
$env:DOCFLOW_MONTHLY_FILE_LOGS="0"
```

Изменить папку:

```powershell
$env:DOCFLOW_LOG_DIR="D:\incoming\_logs"
```

Изменить уровень:

```powershell
$env:DOCFLOW_LOG_LEVEL="INFO"
```

## Файловая идемпотентность

Идемпотентность включается, только если в `process_document_scan(...)` передан `idempotency_key`.

Если ключ не передан, поведение остаётся прежним: каждый запуск реально сканирует документ.

### Где хранятся записи

По умолчанию:

```text
D:\incoming\_idempotency\<safe_key>_<hash>.json
```

Это не SQLite и не журнал операций. Это маленькие JSON-маркеры, которые нужны только для защиты от повторного выполнения одной и той же операции.

Настроить папку:

```powershell
$env:DOCFLOW_IDEMPOTENCY_DIR="D:\incoming\_idempotency"
```

Отключить идемпотентность полностью:

```powershell
$env:DOCFLOW_IDEMPOTENCY_ENABLED="0"
```

## Правила повторного запуска с тем же idempotency_key

### `succeeded`

Если операция уже завершилась успешно и финальный PDF существует:

```text
повторный запуск → не сканировать → вернуть старый final_file_path
```

### `scanned`

Если сканирование уже получило PDF, но сохранение в архив не завершилось:

```text
повторный запуск → не сканировать → повторить только storage
```

### `processing` / `storing`

Если операция ещё свежая:

```text
повторный запуск → ошибка idempotency_in_progress
```

Если запись старая, старше `DOCFLOW_IDEMPOTENCY_STALE_SECONDS`, разрешается новая попытка.

По умолчанию:

```text
30 минут
```

### `failed` / `interrupted` / `timeout`

Повторный запуск разрешён как новая попытка с тем же ключом.

## Пример использования

```python
from app.document_flow import process_document_scan

result = process_document_scan(
    task_id="LOCAL_SCAN_001",
    doc_type="УПД",
    document_datetime="2026-07-10 10:10:25",
    document_number="2455B",
    idempotency_key="LOCAL_SCAN_001_УПД_2455B",
)
```

Повторный вызов с тем же ключом после успеха вернёт тот же `file_path` без повторного сканирования.

## Важно

`idempotency_key` должен быть стабильным для одной операции. Для будущего интерфейса это может быть:

```text
planfix_task_123456_document_УПД_2455B
```

или локальный ключ из UI:

```text
local_scan_20260715_001
```

Не нужно автоматически использовать один и тот же ключ для разных физических документов.

## Тесты

TXT-логи:

```powershell
python -m tests.run_monthly_file_logging_test
```

Модульная проверка идемпотентности:

```powershell
python -m tests.run_idempotency_unit_test
```

Проверка document_flow без реального сканера:

```powershell
python -m tests.run_idempotent_document_flow_fake_test
```

Проверка retry storage без повторного сканирования:

```powershell
python -m tests.run_idempotency_retry_storage_fake_test
```

Реальный профиль Epson:

```powershell
python -m tests.run_document_flow_epson_profile_test
```

Пока существующий профильный тест не передаёт `idempotency_key`, поэтому он будет вести себя как раньше и каждый раз реально сканировать.
