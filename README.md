# Aerotech Docflow

Локальный Python-модуль для сканирования документов через NAPS2, формирования имени файла и безопасного сохранения PDF в архив.

Эта версия — **clean main**: стабильное ядро проекта с минимальным локальным HTTP API, но без внешних интеграций, очереди заданий и воркера.

## Текущий стабильный контур

```text
NAPS2 / EPSON DS-790WN
  → app.scanner
  → D:\incoming\PF_*.pdf
  → app.document_flow
  → app.storage
  → D:\archive_test\ГОД\ТИП\ТИП_ГГММДД_ЧЧММСС_НОМЕР.pdf
```

## Что реализовано

- запуск NAPS2 через профиль или прямой eSCL;
- file lock сканера `D:\incoming\.scanner.lock`;
- защита от `Ctrl+C`, timeout и зависшего NAPS2;
- аварийный карантин частичных runtime-файлов;
- атомарный перенос через `.tmp`;
- резервирование финального имени через `.reserve`;
- файловая идемпотентность без SQLite;
- месячные TXT-логи;
- диагностика восстановления после сбоев;
- unit-тесты без физического сканера;
- manual-тесты для Epson/NAPS2.

## Что намеренно не входит в clean main

- внешний HTTP API и публичный веб-сервер;
- внешние интеграции;
- внешний tunnel / Cloudflare / ngrok;
- очередь заданий и воркер для нескольких операторов;
- OCR;
- загрузка файлов во внешние системы;
- боевая авторизация/HMAC.

Эти части должны добавляться позже отдельными ветками/этапами, чтобы не загрязнять стабильное ядро.

## Установка

```powershell
cd D:\PROG_PROJECTS\aerotech-docflow
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Для установки на другие Windows-устройства реализованы единый `config.toml`,
CLI, PyInstaller `onedir`-сборка и запуск через WinSW как Windows-служба.
Полная инструкция: `docs/10_WINDOWS_INSTALLATION_AND_SERVICE.md`.
Короткая чистая установка с удалением предыдущей попытки:
`docs/11_CLEAN_INSTALLATION.md`.

Основные команды из исходного кода:

```powershell
python -m app.cli --config .\config.toml show-config
python -m app.cli --config .\config.toml preflight
python -m app.cli --config .\config.toml diagnose
python -m app.cli --config .\config.toml run
```

В готовой сборке `python -m app.cli` заменяется на
`app\aerotech-docflow.exe`.

`pypdf` является обязательной защитой целостности PDF. Если библиотека отсутствует
или PDF не удаётся строго разобрать, документ не переносится в архив.

Финальная публикация PDF использует атомарный hard link без перезаписи. Рабочий
архив должен находиться на файловой системе Windows, поддерживающей hard links
(рекомендуется NTFS). Если NAPS2 не удалось остановить после timeout/прерывания,
`.scanner.lock` намеренно сохраняется до ручной диагностики.

## Основные команды

### Локальный API

Установить зависимости и запустить сервер:

```powershell
pip install -r requirements.txt
python -m app.run_local_api
```

Сервер слушает только `127.0.0.1:8000`. Проверка состояния не обращается к сканеру:

```powershell
curl http://127.0.0.1:8000/health
```

Перед первым запуском на реальном архиве включите `DOCFLOW_ENV=production`,
заполните обязательные параметры из `docs/01_CONFIGURATION.md` и выполните:

```powershell
python -m app.preflight
```

Preflight не запускает NAPS2 и не пишет в архив. Production-сервер не стартует
на `archive_test`, при отсутствующем корне архива или без точного подтверждения
`DOCFLOW_ARCHIVE_CONFIRMATION`.

Запуск сканирования из PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/scan" `
  -ContentType "application/json" `
  -Body '{
    "task_id": "53243",
    "doc_type": "НКЛ",
    "document_number": "001",
    "scanner_profile": "EPSON DS-790WN",
    "idempotency_key": "planfix_53243_НКЛ_001"
  }'
```

Дата и время в имени PDF фиксируются сервером непосредственно перед запуском
NAPS2 в часовом поясе `Europe/Moscow`; клиент их не передаёт.

`POST /scan` синхронно ждёт завершения текущего `document_flow` и возвращает имя
готового файла. Очереди, worker, внешней авторизации и туннеля в этой версии нет.
Позже endpoint сможет вызываться ПланФиксом через отдельно настроенный внешний
HTTPS-туннель; сейчас он намеренно доступен только с локального компьютера.

Проверить unit-тесты без сканера:

```powershell
python -m tests.unit.run_all_unit_tests
```

Проверить диагностику сканера:

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics
```

Выполнить реальное сканирование через профиль NAPS2:

```powershell
python -m tests.manual.run_scan_epson_profile
```

Выполнить реальное сканирование прямым eSCL:

```powershell
python -m tests.manual.run_scan_epson_escl_duplex
```

## Документация

- `docs/guide/README.md` — полное руководство пользователя, оператора и администратора.
- `docs/00_OVERVIEW.md` — архитектура и состав проекта.
- `docs/01_CONFIGURATION.md` — переменные окружения и настройки NAPS2.
- `docs/02_OPERATIONS.md` — рабочие команды оператора/администратора.
- `docs/03_TESTING.md` — структура тестов.
- `docs/04_FAILURE_RECOVERY.md` — восстановление после аварий.
- `docs/05_STORAGE_AND_IDEMPOTENCY.md` — архив, `.tmp`, `.reserve`, идемпотентность.
- `docs/06_LOCAL_API.md` — контракт и эксплуатация локального HTTP API.
- `docs/07_ACCEPTANCE_TESTING.md` — приёмка перед production с логами и доказательствами.
- `docs/08_RELEASE_CANDIDATE_2026-07-16.md` — исправления, найденные при приёмке, и статус release candidate.
- `docs/09_PRODUCTION_ARCHIVE_HARDENING.md` — fail-closed защита реального архива и оставшиеся условия допуска.
- `docs/10_WINDOWS_INSTALLATION_AND_SERVICE.md` — TOML-конфигурация, EXE-сборка, WinSW-служба, установка, обновление и диагностика.
- `docs/11_CLEAN_INSTALLATION.md` — чистая установка на текущий компьютер по шагам.
- `docs/99_CLEAN_MAIN.md` — как сделать эту чистую версию веткой `main`.

## Структура проекта

```text
app/
  document_flow.py
  idempotency.py
  incoming_cleanup.py
  locks.py
  monthly_file_logging.py
  naming.py
  scanner.py
  scanner_recovery.py
  storage.py

tests/
  unit/
  manual/

docs/
```
