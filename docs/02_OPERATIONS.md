# 02. Операционные команды

## Диагностика

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics
```

Мягкое восстановление:

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics --kill-naps2 --remove-stale-lock --cleanup-artifacts
```

Жёсткое восстановление, только если точно нет активного сканирования:

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics --kill-naps2 --remove-lock --cleanup-artifacts
```

## Реальное сканирование через профиль

```powershell
python -m tests.manual.run_scan_epson_profile
```

## Реальное сканирование прямым eSCL

```powershell
python -m tests.manual.run_scan_epson_escl_duplex
```

Основной рабочий вариант сейчас — профиль NAPS2, если в нём настроены duplex и исключение пустых страниц.

## Логи

Месячные TXT-логи пишутся в:

```text
C:\AerotechDocflow-Example\logs\docflow_YYYY_MM.txt
```
