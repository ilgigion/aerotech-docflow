# Защита сканирования от внешних сбоев

## Цель

Если во время сканирования выключили сканер, пропала сеть, NAPS2 завис или оператор прервал процесс, сервер не должен зависнуть вместе с внешней программой сканирования.

Этот пакет усиливает защиту вокруг `scanner.py`, `scanner_recovery.py` и существующего `.scanner.lock`.

## Уровни защиты

### 1. Таймаут NAPS2

`scanner.py` запускает NAPS2 как дочерний процесс через `subprocess.Popen` и ждёт его завершения не бесконечно, а только `timeout_seconds`.

По умолчанию:

```python
ScannerSettings(timeout_seconds=180)
```

Через env:

```powershell
$env:SCANNER_TIMEOUT_SECONDS="180"
```

Если NAPS2 не завершился за таймаут, выбрасывается ошибка:

```text
scanner_timeout
```

### 2. Принудительное завершение конкретного процесса NAPS2

При timeout или `Ctrl+C` код завершает именно тот процесс NAPS2, который он сам запустил.

На Windows используется:

```powershell
taskkill /PID <pid> /T /F
```

Это безопаснее, чем убивать все процессы подряд, потому что в штатном сценарии известен конкретный PID.

### 3. Проверка, что процесс действительно завершился

После `taskkill` код несколько секунд проверяет, что процесс ушёл.

Настройка:

```python
verify_process_exit_seconds=5
```

Через env:

```powershell
$env:SCANNER_VERIFY_PROCESS_EXIT_SECONDS="5"
```

Если процесс не завершился, в лог пишется:

```text
manual_check_required=1
```

Это означает: сервер не будет ждать бесконечно, но устройство/драйвер требует ручной проверки.

### 4. Карантин недоверенного временного PDF

Если NAPS2 завис, был прерван или завершился с ошибкой, но успел создать временный файл, этот файл считается недоверенным.

Он переносится из `D:\incoming` в:

```text
D:\incoming\_failed_runtime\YYYYMMDD_HHMMSS_<reason>\PF_....pdf
```

Это защищает временную папку от мусора после аварийных сценариев.

Отключить можно так:

```powershell
$env:SCANNER_QUARANTINE_FAILED_OUTPUTS="0"
```

Но для боевого режима лучше оставить включённым.

### 5. Stale-lock auto-recovery

Если сервер был убит жёстко и `.scanner.lock` остался, следующий запуск сканирования не должен блокироваться навсегда.

`app.locks.ScannerFileLock` проверяет:

1. возраст lock-файла;
2. PID владельца;
3. hostname владельца;
4. жив ли процесс-владелец.

Если lock старый и процесс уже не жив, lock автоматически удаляется, и новая операция захватывает сканер.

По умолчанию lock считается старым после 30 минут:

```python
ScannerLockSettings(stale_after_seconds=30 * 60)
```

Для диагностики можно использовать:

```powershell
python -m tests.run_scanner_recovery_diagnostics --remove-stale-lock
```

### 6. Диагностика после аварии

Проверить состояние:

```powershell
python -m tests.run_scanner_recovery_diagnostics
```

Аварийное восстановление:

```powershell
python -m tests.run_scanner_recovery_diagnostics --kill-naps2 --remove-stale-lock --cleanup-artifacts
```

Жёсткое удаление lock вручную:

```powershell
python -m tests.run_scanner_recovery_diagnostics --kill-naps2 --remove-lock --cleanup-artifacts
```

`--remove-lock` использовать только когда точно нет активного сканирования.

## Что считается штатно закрытым

Закрыты сценарии:

- `Ctrl+C` во время сканирования;
- NAPS2 завис дольше таймаута;
- сканер выключили, и NAPS2 завис в ожидании ответа;
- пропала сеть до сканера, и NAPS2 завис;
- NAPS2 завершился с ошибкой;
- NAPS2 создал частичный PDF;
- старый `.scanner.lock` остался после аварии;
- `.tmp` / `.reserve` остались после аварии storage.

## Что невозможно гарантировать программно

Код не может выполнить восстановление, если:

- выключили питание сервера;
- Windows зависла;
- `python.exe` убили через `Stop-Process -Force`;
- произошёл BSOD;
- зависла прошивка сканера;
- устройство физически держит бумагу после обрыва питания.

Для этих случаев остаётся диагностика и ручной сброс устройства.

## Рекомендуемые боевые настройки Epson

Для текущего Epson DS-790WN:

```python
ScannerSettings(
    profile_name=None,
    driver="escl",
    device_name="EPSON DS-790WN",
    source="duplex",
    dpi=300,
    page_size="a4",
    bit_depth="gray",
    timeout_seconds=180,
    verify_process_exit_seconds=5,
    quarantine_failed_scan_outputs=True,
)
```

Если появятся редкие долгие задания, можно поднять таймаут до 300 секунд.

## Тесты

Проверка без реального сканера:

```powershell
python -m tests.run_scanner_external_failure_unit_test
```

Проверка реального Epson:

```powershell
python -m tests.run_document_flow_epson_escl_duplex_test
```

Диагностика:

```powershell
python -m tests.run_scanner_recovery_diagnostics
```
