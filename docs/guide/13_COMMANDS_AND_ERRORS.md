# 13. Справочник команд и ошибок

## Как читать команды PowerShell

### Приглашение `PS C:\...>`

Это часть интерфейса терминала. Его не нужно копировать. Копируется только текст
после `>`.

### Переменная `$name`

```powershell
$config = "C:\ProgramData\Aerotech Docflow\config\config.toml"
```

PowerShell запоминает строку под именем `$config`. Переменная действует только в
текущем окне. После закрытия терминала её нужно задать снова.

### Оператор `&`

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" --help
```

`&` говорит PowerShell выполнить файл, путь к которому записан строкой или
переменной. Он особенно нужен для путей с пробелами.

### Обратная кавычка

Символ `` ` `` в конце строки означает продолжение команды:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/scan"
```

После обратной кавычки не должно быть пробела. Если PowerShell показывает `>>`,
он ждёт продолжение незавершённой команды. `Ctrl+C` отменяет ввод.

### Pipeline `|`

Передаёт результат одной команды следующей:

```powershell
Get-ChildItem "D:\REPLACE_WITH_ARCHIVE_ROOT" -Recurse -File |
  Get-FileHash -Algorithm SHA256
```

### Hashtable `@{}` и JSON

```powershell
$body = @{
    task_id = "53243"
    doc_type = "НКЛ"
    document_number = "001"
    scanner_profile = "MY_NAPS2_PROFILE"
} | ConvertTo-Json
```

`@{}` создаёт набор ключей и значений. `ConvertTo-Json` превращает его в JSON
для HTTP-запроса.

### Кавычки и пути

Путь с пробелами всегда берите в двойные кавычки:

```powershell
"C:\Program Files\Aerotech Docflow"
```

В PowerShell используется один `\`. Двойной `\\` нужен внутри TOML/JSON-строк.

## Базовые переменные

```powershell
$installed = "C:\Program Files\Aerotech Docflow"
$data = "C:\ProgramData\Aerotech Docflow"
$exe = "$installed\app\aerotech-docflow.exe"
$config = "$data\config\config.toml"
$incoming = "C:\ProgramData\Aerotech Docflow\incoming"
$archive = "D:\REPLACE_WITH_ARCHIVE_ROOT"
```

## Команды только чтения

```powershell
& $exe --config $config show-config
& $exe --config $config preflight
& $exe --config $config diagnose
Invoke-RestMethod http://127.0.0.1:8000/health
Get-Content $config -Encoding UTF8
Get-ChildItem "$data\logs"
Get-Process aerotech-docflow,NAPS2* -ErrorAction SilentlyContinue
Get-Service AerotechDocflow -ErrorAction SilentlyContinue
```

Они не запускают физический скан. `preflight` может проверять существование и
права, но не пишет PDF.

## Команды изменения конфигурации

```powershell
Copy-Item $config "$config.backup" -Force
notepad $config
```

После изменения всегда:

```powershell
& $exe --config $config show-config
& $exe --config $config preflight
```

## Команды запуска

```powershell
& "$installed\start-manually.ps1"
```

Запуск сервера сам по себе не сканирует. Физический скан запускает только:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/scan" ...
```

## Команды с изменением системного состояния

Требуют администратора и понимания последствий:

```powershell
.\install_current_machine.ps1 -ConfirmArchive
.\cleanup_previous_install.ps1
Start-Service AerotechDocflow
Stop-Service AerotechDocflow
Remove-Item "C:\ProgramData\Aerotech Docflow\incoming\.scanner.lock"
```

Последняя команда запрещена без stale-диагностики.

## CLI-команды

```text
configure    интерактивно создать config.toml
show-config показать итоговые значения и env overrides
preflight    проверить production без скана
diagnose     прочитать lock/process/tmp/reserve
run          запустить FastAPI
```

Пример:

```powershell
& $exe --config $config diagnose
```

Аргумент `--config` ставится перед подкомандой.

## Частые error codes

| `error_code` | HTTP | Что означает | Первое действие |
|---|---:|---|---|
| `validation_error` | 422 | неверный JSON или реквизиты | исправить запрос, скан не запускался |
| `scanner_locked` | 409 | существует активный/непроверенный lock | `diagnose`, не удалять lock |
| `scanner_busy` | 409 | устройство занято NAPS2/другой программой | закрыть GUI, дождаться операции |
| `idempotency_in_progress` | 409 | тот же ключ ещё выполняется | дождаться и повторить тот же ключ |
| `idempotency_key_request_conflict` | 409 | ключ использован для других реквизитов | проверить бизнес-идентичность, не менять JSON вслепую |
| `no_scanned_pages` | 500 | ADF пуст или профиль не получил страницы | положить документ, проверить source |
| `scanner_connection_error` | 503 | сеть/VPN/firewall/устройство | проверить профиль в NAPS2 и сеть |
| `scanner_not_found` | 503 | устройство не найдено | проверить имя/профиль/питание |
| `scanner_timeout` | 503 | NAPS2 превысил timeout и остановлен | диагностика, затем повтор того же ключа |
| `scanner_process_still_running` | 503 | NAPS2 не удалось остановить | poisoned-state, ручной recovery |
| `manual_recovery_required` | 503 | автоматическое продолжение небезопасно | проверить JSON/temp/final/SHA-256 |
| `naps2_not_found` | 500 | неверный путь к Console EXE | исправить scanner config |
| `naps2_process_error` | 500 | NAPS2 вернул общий ненулевой код | читать message, stdout/stderr logs |
| `output_missing` | 500 | NAPS2 не создал файл | проверить NAPS2 и карантин |
| `output_too_small` | 500 | подозрительно маленький файл | документ не принят |
| `output_not_pdf` | 500 | неверный заголовок | документ не принят |
| `output_pdf_missing_eof` | 500 | незавершённый PDF | документ не принят, проверить сбой |
| `output_pdf_parse_error` | 500 | `pypdf` не разобрал PDF | документ не принят |
| `output_pdf_has_no_pages` | 500 | PDF без страниц | документ не принят |
| `archive_root_missing` | 500 | архив недоступен | восстановить диск, source не удалять |
| `archive_directory_create_error` | 500 | нет прав/места для ГОД/ТИП | проверить ACL и диск |
| `atomic_temp_copy_error` | 500 | ошибка копирования `.tmp` | проверить место/доступ, source сохранить |
| `atomic_temp_hash_mismatch` | 500 | копия отличается от source | прекратить, проверить диск |
| `atomic_temp_pdf_invalid` | 500 | копия не прошла PDF-проверку | прекратить, сохранить доказательства |
| `atomic_no_clobber_finalize_error` | 500 | нет безопасного hard-link publish | проверить NTFS/SMB capability |
| `destination_appeared_during_atomic_move` | 500 | гонка за final path | существующий файл не перезаписан |
| `too_many_duplicates_or_reservations` | 500 | заняты 100 вариантов имени | диагностика `.reserve` и бизнес-дубликатов |
| `idempotency_published_file_mismatch` | 500 | temp и опубликованный final различаются | оба файла оставить, ручной аудит |

Точный `message` в ответе предназначен оператору. `technical_message` и stack
trace ищутся в application log.

## Быстрая матрица симптомов

| Симптом | Проверка |
|---|---|
| `/health` не отвечает | процесс, порт, окно startup, preflight |
| `/health` ok, но скан не идёт | профиль NAPS2, VPN, ADF, lock |
| 409 | текущая операция, lock, idempotency JSON |
| 503 | сеть/timeout/manual recovery |
| 500 сразу | validation stage уже прошла; читать `error_code` |
| PDF остался в incoming | вероятен storage failure/retry |
| `.reserve` остался | процесс упал в storage; diagnose ownership |
| служба Stopped | wrapper log и Event ID 7000/7038 |
| config изменён, но эффект старый | restart и `overridden_by_environment` |

## Полезные PowerShell-команды

```powershell
Test-Path PATH                 # существует ли путь
Get-Item PATH                  # сведения об одном объекте
Get-ChildItem PATH -Force      # список, включая скрытые файлы
Get-Content FILE -Raw          # прочитать файл целиком
Copy-Item SOURCE DESTINATION   # копировать
Get-FileHash FILE -Algorithm SHA256
Select-String -Path FILE -Pattern TEXT
Get-Process NAME
Get-Service NAME
Invoke-RestMethod URL
```

`-ErrorAction SilentlyContinue` скрывает ожидаемую ошибку «не найдено», но не
исправляет проблему. Не добавляйте его к операциям удаления.
