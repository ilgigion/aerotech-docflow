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

## Важное правило

Unit-тесты не должны обращаться к HTTP-серверу, NAPS2 или физическому сканеру. Если такая логика появится позже, её нужно держать в отдельной ветке/этапе или в `tests/integration/`, но не в clean-main unit suite.
