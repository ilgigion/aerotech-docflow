# Aerotech Docflow

Локальный Python-модуль для сканирования документов через NAPS2, формирования имени файла и безопасного сохранения PDF в архив.

Эта версия — **clean main**: стабильное ядро проекта без внешних интеграций, HTTP API, очереди заданий и воркера.

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

- HTTP API и веб-сервер;
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

`pypdf` используется для дополнительной проверки PDF. Если он недоступен, базовое сканирование всё равно может работать, но проверка количества страниц будет пропущена.

## Основные команды

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
