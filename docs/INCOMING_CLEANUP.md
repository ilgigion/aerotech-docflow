# 3.5. Контроль временной папки incoming

## Задача

`scanner.py` создаёт временные PDF в папке `incoming_dir`, например:

```text
D:\incoming\PF_TEST_001_20260715_101010_a1b2c3.pdf
```

В нормальном сценарии `storage.py` переносит этот файл в архив, и в `D:\incoming` он исчезает.

Но после ошибок могут остаться временные PDF:

- сканирование прошло, но архив был недоступен;
- процесс был остановлен;
- была ошибка сети;
- был тестовый запуск;
- storage не смог перенести файл;
- оператор прервал процесс.

Нужно контролировать временную папку, но не трогать ручные или неизвестные файлы.

---

## Правило безопасности

Cleanup трогает только файлы:

```text
PF_*.pdf
```

И только в корне `incoming_dir`.

Cleanup НЕ трогает:

```text
MANUAL_SCAN.pdf
scan.pdf
*.txt
*.jpg
.scanner.lock
подпапки
любые файлы без префикса PF_
```

Это важно, потому что в эту же папку теоретически могут попадать ручные сканы или диагностические файлы.

---

## Почему не удаляем сразу

Старые временные PDF не удаляются, а переносятся в карантин:

```text
D:\incoming\_failed\20260715_103012\PF_OLD_001.pdf
```

Причины:

- файл может быть единственной копией скана;
- можно вручную проверить содержимое;
- можно повторить сохранение в архив;
- меньше риск потерять документ.

Удаление можно добавить позже отдельной политикой, например удалять карантин старше 30 дней.

---

## Защита от активного сканирования

Если существует:

```text
D:\incoming\.scanner.lock
```

cleanup по умолчанию ничего не делает.

Причина: если сканирование активно, в `incoming` может находиться файл, который ещё участвует в процессе.

Поведение:

```text
scanner.lock есть -> cleanup skipped
scanner.lock нет  -> можно искать старые PF_*.pdf
```

---

## Минимальный возраст файла

По умолчанию файл считается кандидатом только если он старше 24 часов:

```python
min_age_seconds = 24 * 60 * 60
```

Это защищает от ситуации, когда файл только что появился, но ещё не был перенесён в архив.

Для тестов можно ставить меньше.

---

## Основные функции

Файл:

```text
app/incoming_cleanup.py
```

Главная функция:

```python
cleanup_incoming_folder(settings, action="dry_run")
```

Режимы:

```text
dry_run     — только показать кандидатов
quarantine  — перенести кандидатов в _failed/<run_id>/
```

---

## Пример dry_run

```python
from pathlib import Path
from app.incoming_cleanup import IncomingCleanupSettings, cleanup_incoming_folder

settings = IncomingCleanupSettings(
    incoming_dir=Path(r"D:\incoming"),
    min_age_seconds=24 * 60 * 60,
)

result = cleanup_incoming_folder(
    settings=settings,
    action="dry_run",
)

print(result.candidate_count)
for candidate in result.candidates:
    print(candidate.path)
```

---

## Пример карантина

```python
result = cleanup_incoming_folder(
    settings=settings,
    action="quarantine",
)

print(result.quarantined_count)
for item in result.quarantined_files:
    print(item.source_path, "->", item.destination_path)
```

---

## Как тестировать

```powershell
python -m tests.run_incoming_cleanup_test
```

Тест проверяет:

```text
1. dry_run находит только старые PF_*.pdf;
2. quarantine переносит только старые PF_*.pdf;
3. новые PF-файлы остаются;
4. ручные файлы остаются;
5. если есть .scanner.lock, cleanup пропускается.
```

---

## Как использовать позже

В будущем cleanup можно запускать:

- вручную администратором;
- при старте сервиса в режиме `dry_run`;
- отдельной scheduled task раз в день;
- из админского FastAPI endpoint.

Пример Windows Task Scheduler:

```powershell
python -m app.cleanup_job
```

Но пока автоматический запуск не добавлен намеренно. Сначала лучше запускать вручную и смотреть результат.

---

## Связь с retry storage

Если в `D:\incoming` остался старый `PF_*.pdf`, возможны два варианта:

1. Это нужный скан, который надо сохранить в архив через `retry_store_existing_scan()`.
2. Это мусор от старого теста или ошибки, который можно перенести в карантин.

Поэтому `cleanup` не удаляет файлы, а только переносит их в `_failed`.

---

## Текущее решение

На этапе 3.5 реализовано:

```text
app/incoming_cleanup.py
```

И тест:

```text
tests/run_incoming_cleanup_test.py
```

Автоматический запуск cleanup пока не подключён к `document_flow.py`, чтобы не было скрытых побочных действий во время сканирования.
