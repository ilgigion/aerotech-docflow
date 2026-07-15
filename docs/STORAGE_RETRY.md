# Сценарий 3.2: сканирование прошло, но архив недоступен

## Цель

Если сканер успешно создал временный PDF, но перенос в архив не удался, нельзя заставлять оператора сканировать документ повторно.

Правильное поведение:

```text
1. Временный PDF остаётся в incoming.
2. Ошибка содержит source_path.
3. Оператор/администратор исправляет проблему архива.
4. Система повторяет только перенос файла.
5. Повторного сканирования нет.
```

---

## Где это реализовано

Файлы:

```text
app/document_flow.py
app/storage.py
tests/run_storage_retry_test.py
```

Основная функция полного процесса:

```python
process_document_scan(...)
```

Функция повторного переноса без сканирования:

```python
retry_store_existing_scan(...)
```

Безопасная версия для будущего FastAPI/Planfix:

```python
retry_store_existing_scan_safe(...)
```

---

## Как это работает

Полный процесс:

```text
scan_document()
  → создал D:\incoming\PF_....pdf

store_document()
  → пытается перенести в архив
  → архив недоступен
  → выбрасывает StorageError
  → source_path остаётся в ошибке
```

После исправления архива:

```text
retry_store_existing_scan(source_path=...)
  → берёт уже существующий PDF
  → формирует имя
  → переносит в архив
```

---

## Почему это важно

Без этой защиты возможен плохой сценарий:

```text
сканирование прошло
архив временно недоступен
оператор вынужден сканировать заново
появляются дубли и путаница
```

С новой логикой:

```text
сканирование прошло один раз
при ошибке архивирования PDF сохраняется
перенос можно повторить отдельно
```

---

## Как протестировать

Из корня проекта:

```powershell
python -m tests.run_storage_retry_test
```

Тест делает следующее:

```text
1. Создаёт временный PDF в D:\incoming.
2. Пытается сохранить его в неправильный archive_root.
3. Получает StorageError.
4. Проверяет, что временный PDF остался.
5. Повторяет только перенос в D:\archive_test.
```

Ожидаемый результат:

```text
OK: получили ошибку архива
source_path exists: True
OK
Финальный путь: D:\archive_test\2026\УПД\...
source_path exists after move: False
```

---

## Как это пригодится для Planfix

В будущем при ошибке сохранения можно записать в задачу Planfix:

```text
status = Ошибка сохранения
error_code = archive_root_not_directory / archive_directory_not_writable / file_move_error
error_message = понятное сообщение
source_path = D:\incoming\PF_....pdf
```

После исправления проблемы можно повторить только архивирование:

```python
retry_store_existing_scan(
    task_id=task_id,
    source_path=source_path,
    doc_type=doc_type,
    document_datetime=document_datetime,
    document_number=document_number,
)
```
