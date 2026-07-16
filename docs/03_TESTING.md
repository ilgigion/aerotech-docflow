# 03. Тесты

Тесты разделены на две группы.

## Unit-тесты без сканера

```powershell
python -m tests.unit.run_all_unit_tests
```

Они проверяют:

- naming;
- storage;
- `.tmp`/`.reserve`;
- idempotency;
- monthly file logging;
- incoming cleanup.

## Manual-тесты со сканером

```powershell
python -m tests.manual.run_scan_epson_profile
python -m tests.manual.run_scan_epson_escl_duplex
python -m tests.manual.run_scanner_recovery_diagnostics
```

Manual-тесты могут запускать реальный NAPS2 и физический сканер.

## Приёмочные испытания с доказательствами

Перед production используется отдельный runner, который сохраняет команды,
логи, JSON-запросы и ответы, снимки файлов, SHA-256 и итоговую таблицу по всем
12 сценариям:

```powershell
python -m tests.acceptance.run_acceptance_tests start
```

Без флага `--confirm-real-scan` runner не запускает физический сканер. Полная
процедура описана в `docs/07_ACCEPTANCE_TESTING.md`.

## Важное правило

Unit-тесты не должны обращаться к HTTP-серверу, NAPS2 или физическому сканеру.
Реальные запросы и физические испытания находятся только в `tests/acceptance/`
и требуют явного подтверждения.
