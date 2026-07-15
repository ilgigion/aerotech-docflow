# 05. Сбои и восстановление

## Что уже предусмотрено

- `Ctrl+C` во время сканирования;
- timeout NAPS2;
- принудительное завершение конкретного PID NAPS2;
- проверка, что процесс завершился;
- освобождение `.scanner.lock`;
- карантин недоверенного PDF;
- диагностика зависших `.tmp` и `.reserve`.

Исключение: если после `taskkill` и fallback kill процесс NAPS2 остаётся жив,
`.scanner.lock` не освобождается автоматически. Это защитный poisoned-state;
нужно завершить NAPS2, выполнить диагностику и только затем удалить lock вручную.

## После аварии

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics
```

Если есть риск-маркеры:

```powershell
python -m tests.manual.run_scanner_recovery_diagnostics --kill-naps2 --remove-stale-lock --cleanup-artifacts
```

## Что приложение не может гарантировать

- выключение питания ПК;
- аварийное завершение Windows;
- убийство `python.exe` через `Stop-Process -Force`;
- зависание прошивки сканера.

Для этих случаев используется диагностика и ручной/полуавтоматический recovery.
