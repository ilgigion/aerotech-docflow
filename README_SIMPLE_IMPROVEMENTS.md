# Simple improvements package

Заменить/добавить файлы из этого архива в проект.

## Что добавлено

1. Усиленная проверка входных данных в `app/naming.py`.
2. Диагностика окружения сканера: `check_scanner_environment`.
3. Диагностика архива: `check_storage_environment`.
4. Единый результат процесса: `DocumentProcessResult` и `process_document_scan_safe`.
5. Улучшенное логирование с `operation_id`.
6. Предварительная проверка имени и архива до запуска физического сканирования.

## Запуск тестов

```powershell
python -m tests.run_naming_test
python -m tests.run_storage_test
python -m tests.run_diagnostics_test
python -m tests.run_document_flow_test
```

`tests.run_document_flow_test` запускает реальный сканер.
