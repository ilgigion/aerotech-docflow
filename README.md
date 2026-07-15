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

Запуск сканирования из PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/scan" `
  -ContentType "application/json" `
  -Body '{
    "task_id": "53243",
    "doc_type": "НКЛ",
    "document_datetime": "2026-06-24T13:50:00",
    "document_number": "001",
    "idempotency_key": "planfix_53243_НКЛ_20260624T135000_001"
  }'
```

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

- `docs/00_OVERVIEW.md` — архитектура и состав проекта.
- `docs/01_CONFIGURATION.md` — переменные окружения и настройки NAPS2.
- `docs/02_OPERATIONS.md` — рабочие команды оператора/администратора.
- `docs/03_TESTING.md` — структура тестов.
- `docs/04_FAILURE_RECOVERY.md` — восстановление после аварий.
- `docs/05_STORAGE_AND_IDEMPOTENCY.md` — архив, `.tmp`, `.reserve`, идемпотентность.
- `docs/06_LOCAL_API.md` — контракт и эксплуатация локального HTTP API.
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
