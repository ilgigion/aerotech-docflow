# 9. Диагностика и восстановление

## Правило диагностики

Сначала собрать факты, затем изменять состояние. Не удаляйте lock, JSON,
`.reserve` или `.tmp` как первый шаг.

## Базовые переменные администратора

```powershell
$exe = "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe"
$config = "C:\ProgramData\Aerotech Docflow\config\config.toml"
$incoming = "D:\incoming"
$archive = "D:\Archive"
$logs = "C:\ProgramData\Aerotech Docflow\logs"
```

## Безопасная read-only проверка

Остановите новые запросы и выполните:

```powershell
& $exe --config $config show-config
& $exe --config $config preflight
& $exe --config $config diagnose
Get-Process aerotech-docflow,NAPS2* -ErrorAction SilentlyContinue
Get-ChildItem $incoming -Force
```

Первые три команды не запускают сканер. `diagnose` выводит:

| Поле | Значение |
|---|---|
| `lock_exists` | существует ли `.scanner.lock` |
| `lock_info` | владелец: operation, task, PID, hostname, время |
| `lock_is_stale` | доказана ли stale-ситуация по возрасту и PID |
| `naps2_processes` | активные NAPS2/NAPS2.Console |
| `incoming_pf_files` | временные PDF, возможно ожидающие retry storage |
| `incoming_failed_runtime_files` | карантин недоверенных scanner outputs |
| `archive_tmp_files` | временные копии в архиве |
| `archive_reserve_files` | резервирования имён |
| `has_risk_markers` | нужен ли разбор аварийного состояния |

Наличие `PF_*.pdf` само по себе не означает мусор: это может быть единственный
валидный скан после отказа архива.

## API не отвечает

### Симптом

```text
Invoke-RestMethod: Невозможно соединиться с удаленным сервером
```

### Проверки

```powershell
Get-Process aerotech-docflow -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -ErrorAction SilentlyContinue
```

Если процесса нет, запустите `start-manually.ps1` и прочитайте ошибку в его
окне. Если процесс есть, но порта нет, обычно startup preflight завершился
ошибкой. Выполните preflight отдельно.

## Preflight не проходит

Проверяйте сверху вниз:

```powershell
Test-Path $exe
Test-Path $config
Test-Path "C:\Program Files\NAPS2\NAPS2.Console.exe"
Test-Path $incoming
Test-Path $archive
Test-Path "$archive\.aerotech-docflow-archive.json"
Get-Content $config -Encoding UTF8
Get-Content "$archive\.aerotech-docflow-archive.json" -Encoding UTF8
```

Не создавайте новый marker поверх существующего с другой identity. Не меняйте
root на случайный каталог только ради зелёного preflight.

## Пустой автоподатчик: `no_scanned_pages`

Это штатная контролируемая ошибка:

1. убедитесь, что в архиве не появился PDF;
2. положите документ;
3. повторите тот же запрос и тот же idempotency key;
4. если ошибка повторяется, проверьте источник бумаги в профиле NAPS2.

## `scanner_connection_error` или `scanner_not_found`

1. закройте сервер;
2. проверьте скан тем же профилем в NAPS2 GUI;
3. проверьте питание и сеть;
4. отключите VPN, если он меняет маршрут к локальному сканеру;
5. проверьте точное имя профиля;
6. закройте NAPS2 GUI;
7. запустите сервер и повторите тот же idempotency key.

## `scanner_busy` или HTTP 409

Проверьте:

```powershell
Get-Process NAPS2* -ErrorAction SilentlyContinue
Get-Content "$incoming\.scanner.lock" -Encoding UTF8 -ErrorAction SilentlyContinue
```

Если другой запрос действительно выполняется, дождитесь его. Если открыт NAPS2
GUI, закройте его. Если есть lock без процессов, переходите к stale-проверке.

## Безопасное удаление stale lock

Удалять lock можно только при одновременном выполнении условий:

1. сервер остановлен;
2. NAPS2/NAPS2.Console отсутствуют;
3. PID из lock не существует;
4. `diagnose` показывает `lock_is_stale: true`;
5. сохранена копия lock для расследования.

Из исходного проекта безопасный recovery:

```powershell
cd "D:\PROG_PROJECTS\aerotech-docflow"
python -m tests.manual.run_scanner_recovery_diagnostics
python -m tests.manual.run_scanner_recovery_diagnostics `
  --kill-naps2 `
  --remove-stale-lock `
  --cleanup-artifacts
```

Не используйте `--remove-lock`, пока не доказано отсутствие активного скана.

Если Python-окружение не подготовлено, соберите доказательства и используйте
ручное удаление только после всех пяти проверок:

```powershell
Copy-Item "$incoming\.scanner.lock" "$incoming\.scanner.lock.audit-copy"
Remove-Item "$incoming\.scanner.lock"
```

## `scanner_process_still_running`

Это poisoned-state. Приложение намеренно сохраняет lock, потому что NAPS2 мог
продолжать писать файл.

1. не повторяйте POST;
2. остановите сервер;
3. завершите NAPS2 через Task Manager или recovery tool;
4. убедитесь, что процесса нет;
5. выполните `diagnose`;
6. только затем удаляйте доказанный stale lock.

## Ошибка архива

Типичные коды:

- `archive_root_missing`;
- `archive_directory_create_error`;
- `atomic_temp_copy_error`;
- `atomic_no_clobber_finalize_error`;
- `atomic_temp_hash_mismatch`.

Действия:

1. не удалять `PF_*.pdf`;
2. проверить диск, свободное место, NTFS и права;
3. проверить marker и root;
4. найти `.tmp`/`.reserve` через `diagnose`;
5. устранить доступ;
6. повторить тот же idempotency key — возможен retry только storage.

Успех можно фиксировать только после появления подтверждённого final PDF.

## Повреждённый PDF

Коды `output_pdf_parse_error`, `output_pdf_missing_eof`,
`output_pdf_has_no_pages`, `atomic_temp_pdf_invalid` означают, что документ не
принят. Недоверенный scanner output может находиться в
`D:\incoming\_failed_runtime`.

Не переносите файл из карантина в архив вручную без открытия, строгой проверки
и отдельного решения ответственного за архив.

## `manual_recovery_required`

Обычно JSON говорит `succeeded`, но final недоступен, либо состояние не может
быть безопасно продолжено. Требуется:

1. найти JSON по idempotency key;
2. проверить записанные `temp_scan_path` и `final_file_path`;
3. убедиться, что оба пути внутри разрешённых roots;
4. проверить PDF и SHA-256;
5. восстановить доступ к архиву или оформить ручное решение;
6. не запускать новый скан с новым ключом до окончания расследования.

## Что приложить к обращению

- полный HTTP-ответ;
- `operation_id`;
- `idempotency_key`;
- вывод `show-config`, `preflight`, `diagnose`;
- relevant log lines;
- список процессов NAPS2;
- имена `PF_`, `.tmp`, `.reserve`;
- SHA-256 найденных PDF;
- точное время события.
