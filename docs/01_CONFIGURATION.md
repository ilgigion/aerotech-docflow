# 01. Конфигурация

Все рабочие пути и параметры задаются через `config.toml` либо переменные
окружения. Полный пример находится в `config.example.toml`; прежний контракт
переменных перечислен в `.env.example`.

Приоритет:

```text
переменная окружения
→ config.toml
→ встроенное значение только для алгоритмических параметров
```

Пути архива, incoming, NAPS2, логов и idempotency не имеют скрытых
machine-specific fallback. При их отсутствии runtime завершается ошибкой.

Путь к TOML передаётся через `--config`, `DOCFLOW_CONFIG_FILE` либо по умолчанию
равен `C:\ProgramData\Aerotech Docflow\config\config.toml`. Неизвестные ключи и
невалидный TOML приводят к отказу запуска. Сам Python-код `.env` не загружает.

Проверка эффективных значений:

```powershell
python -m app.cli --config .\config.toml show-config
```

## Рекомендуемые параметры для текущего рабочего сканера

```powershell
$env:NAPS2_EXECUTABLE = "C:\Program Files\NAPS2\NAPS2.Console.exe"
$env:NAPS2_PROFILE = "EPSON DS-790WN"
$env:SCANNER_INCOMING_DIR = "D:\incoming"
$env:ARCHIVE_ROOT = "D:\archive_test"
$env:SCANNER_TIMEOUT_SECONDS = "180"
```

Если используется профиль NAPS2, то `SCANNER_DRIVER`, `SCANNER_DEVICE_NAME`, `SCANNER_SOURCE`, `SCANNER_DPI`, `SCANNER_PAGE_SIZE`, `SCANNER_BIT_DEPTH` не участвуют в команде NAPS2.

## Профиль NAPS2

В профиле `EPSON DS-790WN` рекомендуется:

```text
Драйвер: ESCL
Источник бумаги: Двустороннее сканирование
Размер страницы: A4
Разрешение: 300 dpi
Исключить пустые страницы: включено, если нужно
Автосохранение: выключено
```

Автосохранение NAPS2 не нужно, потому что путь PDF задаёт backend через `-o`.

## Архив

По умолчанию:

```text
D:\archive_test\2026\УПД\УПД_260710_101025_2455B.pdf
```

## Обязательный production-режим

Перед подключением реального архива задайте как минимум:

```powershell
$env:DOCFLOW_ENV = "production"
$env:DOCFLOW_VERSION = "1.0.0"
$env:ARCHIVE_ROOT = "D:\real_archive"
$env:DOCFLOW_ARCHIVE_CONFIRMATION = "D:\real_archive"
$env:DOCFLOW_ARCHIVE_ID = "aerotech-primary-archive"
$env:SCANNER_INCOMING_DIR = "D:\incoming"
$env:NAPS2_EXECUTABLE = "C:\Program Files\NAPS2\NAPS2.Console.exe"
$env:NAPS2_PROFILE = "EPSON DS-790WN"
$env:DOCFLOW_ALLOWED_DOC_TYPES = "НКЛ,УПД"
$env:DOCFLOW_MIN_DOCUMENT_YEAR = "2020"
$env:DOCFLOW_MAX_DOCUMENT_YEAR = "2030"
$env:DOCFLOW_LOG_DIR = "D:\incoming\_logs"
$env:DOCFLOW_IDEMPOTENCY_DIR = "D:\incoming\_idempotency"
```

Каталоги архива, incoming, логов и idempotency создаются заранее. Production:

- не запускается с `archive_test` или отсутствующим корнем архива;
- требует точного совпадения `DOCFLOW_ARCHIVE_CONFIRMATION` и `ARCHIVE_ROOT`;
- требует включённые idempotency и файловые логи;
- запрещает вложение incoming/log/idempotency внутрь архива;
- проверяет stale timeout, допустимые годы и типы документов.

В корне реального архива администратор один раз создаёт
`.aerotech-docflow-archive.json`:

```json
{
  "marker": "aerotech-docflow-archive-v1",
  "archive_id": "aerotech-primary-archive"
}
```

`archive_id` должен точно совпадать с `DOCFLOW_ARCHIVE_ID`. Приложение этот файл
не создаёт и не изменяет; marker защищает от подмены диска/каталога при том же
пути `ARCHIVE_ROOT`.

Проверка без запуска сканера и без записи в архив:

```powershell
python -m app.cli --config .\config.toml preflight
```

Только после результата `status: ok` запускайте API.

Подробная установка EXE и Windows-службы описана в
`docs/10_WINDOWS_INSTALLATION_AND_SERVICE.md`.
