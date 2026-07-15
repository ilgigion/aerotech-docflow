# 00. Обзор проекта

## Назначение

Aerotech Docflow — локальное ядро для физического сканера и файлового архива.

Основная задача текущей версии: получить PDF со сканера, сформировать корректное имя, безопасно сохранить файл и оставить понятные логи/диагностику.

Внешние интеграции и HTTP API в эту clean-main версию намеренно не входят.

## Текущий основной поток

```text
process_document_scan()
  → scanner_lock()
  → scan_document()
  → store_document()
  → monthly txt log
  → optional idempotency record
```

## Основные модули

| Модуль | Ответственность |
|---|---|
| `app/scanner.py` | Запуск NAPS2, timeout, Ctrl+C, kill process tree, проверка PDF. |
| `app/locks.py` | Локальный file lock сканера. |
| `app/naming.py` | Формирование имени `ТИП_ГГММДД_ЧЧММСС_НОМЕР.pdf`. |
| `app/storage.py` | Архив, `.tmp`, `.reserve`, защита от дублей. |
| `app/document_flow.py` | Оркестрация полного процесса. |
| `app/idempotency.py` | Файловая идемпотентность без SQLite. |
| `app/monthly_file_logging.py` | TXT-логи по месяцам. |
| `app/incoming_cleanup.py` | Карантин старых временных PDF. |
| `app/scanner_recovery.py` | Диагностика и восстановление после сбоев. |

## Что удалено из clean-main

- HTTP API и веб-сервер;
- очередь заданий и worker;
- `.git` из архива поставки;
- `__pycache__`;
- `.pytest_cache`;
- локальные PDF из runtime-папок;
- временные zip-пакеты этапов разработки;
- устаревшие/дублирующие markdown-файлы.
