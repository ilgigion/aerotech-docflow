# 10. Конфигурация, EXE и Windows-служба

Этот документ описывает перенос Aerotech Docflow на другой Windows-компьютер,
настройку сканера и архива, сборку `aerotech-docflow.exe`, регистрацию Windows-службы,
обновление и диагностику.

## 1. Что устанавливается и где

Рекомендуемая production-структура:

```text
C:\Program Files\Aerotech Docflow\
  app\
    aerotech-docflow.exe
    _internal\
  service\
    docflow-service.exe
    docflow-service.xml
    docflow-service.xml.template
    install-service.ps1
    uninstall-service.ps1
  config\
    config.example.toml
  docs\
    INSTALLATION.md

C:\ProgramData\Aerotech Docflow\
  config\
    config.toml
  logs\
  service-logs\
  data\
    idempotency\

D:\Docflow\incoming\
  PF_*.pdf
  .scanner.lock
  _failed_runtime\

D:\Archive\
  .aerotech-docflow-archive.json
  2026\НКЛ\...
```

Назначение каталогов:

- `Program Files` содержит неизменяемую программу;
- `ProgramData` содержит настройки и служебное состояние;
- `incoming` находится на локальном стабильном диске и хранит временный PDF;
- `Archive` содержит только документы и archive marker.

Программу, конфигурацию, логи, incoming и idempotency нельзя размещать внутри
архива. Production preflight отклонит такую конфигурацию.

## 2. Как работает config.toml

Приложение сохранило совместимость со всеми существующими переменными
окружения. Модуль `app.configuration` читает TOML и до запуска остальных
компонентов переносит значения в прежний environment-контракт.

Приоритет значений:

```text
переменные окружения процесса
→ config.toml
→ development defaults
```

Это означает, что администратор может временно переопределить один параметр, не
редактируя файл:

```powershell
$env:DOCFLOW_LOG_LEVEL = "DEBUG"
& .\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" run
```

`show-config` показывает итоговые значения и список параметров, перекрытых
окружением:

```powershell
& .\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" show-config
```

Неизвестный ключ, неподдерживаемый тип, повреждённый UTF-8 или TOML-синтаксис
останавливают запуск. Это защищает от опечатки, которая могла бы незаметно
переключить архив или сканер.

Полный образец: `config.example.toml`.

## 3. CLI

Из исходного кода:

```powershell
python -m app.cli --config .\config.toml show-config
python -m app.cli --config .\config.toml preflight
python -m app.cli --config .\config.toml diagnose
python -m app.cli --config .\config.toml run
```

Из EXE:

```powershell
.\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" show-config
.\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" preflight
.\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" diagnose
.\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" run
```

Команды:

- `configure` — интерактивно создаёт машинный TOML;
- `show-config` — показывает итоговые параметры, не обращаясь к сканеру;
- `preflight` — проверяет production-инварианты, не сканирует и не пишет PDF;
- `diagnose` — читает lock, процессы NAPS2 и временные артефакты, ничего не удаляет;
- `run` — после preflight запускает FastAPI на localhost.

API намеренно разрешает только `127.0.0.1` или `localhost`. TOML не позволяет
случайно открыть порт на `0.0.0.0`; внешний доступ должен идти через отдельно
настроенный и защищённый SSH-туннель.

## 4. Создание машинной конфигурации

Сначала установите NAPS2 и создайте корень реального архива. Затем:

```powershell
New-Item -ItemType Directory -Path "C:\ProgramData\Aerotech Docflow\config" -Force

& .\app\aerotech-docflow.exe configure `
  --output "C:\ProgramData\Aerotech Docflow\config\config.toml"
```

Мастер:

1. выбирает production/development;
2. запрашивает путь к NAPS2;
3. выбирает профиль или direct mode;
4. задаёт incoming;
5. принимает только уже существующий архив;
6. задаёт `archive_id`, типы документов и годы;
7. создаёт только incoming, logs и idempotency после подтверждения;
8. сохраняет TOML атомарной заменой.

Мастер намеренно не создаёт архив и archive marker. Это отдельное действие
администратора. В корне архива должен находиться файл:

```text
D:\Archive\.aerotech-docflow-archive.json
```

Содержимое:

```json
{
  "marker": "aerotech-docflow-archive-v1",
  "archive_id": "aerotech-primary-archive"
}
```

`archive_id` должен совпасть с `archive.archive_id`, а `archive.confirmation` —
с разрешённым абсолютным `archive.root`.

Ограничьте ACL `config.toml`: запись нужна только администраторам, чтение —
администраторам и выбранной служебной учётной записи. Обычный оператор не должен
иметь возможности заменить `archive.root`, `NAPS2_EXECUTABLE` или каталоги
служебного состояния.

После создания TOML:

```powershell
& .\app\aerotech-docflow.exe --config "C:\ProgramData\Aerotech Docflow\config\config.toml" preflight
```

Продолжать можно только при `"status": "ok"`.

## 5. Профиль NAPS2 и учётная запись службы

Профили NAPS2 принадлежат Windows-пользователю и обычно находятся в:

```text
%APPDATA%\NAPS2\profiles.xml
```

Если профиль `EPSON DS-790WN` создан под оператором, служба под LocalSystem,
LocalService или другим пользователем может его не увидеть.

Безопасные варианты:

1. запустить службу под выделенной учётной записью и создать профиль именно под
   ней;
2. оставить `scanner.profile` пустым и использовать `[scanner.direct]` с eSCL,
   WIA или TWAIN;
3. для доменной среды использовать отдельную service account/gMSA и проверить
   права на сетевой сканер и архив.

Не выбирайте LocalSystem только ради обхода проблем с правами: эта учётная
запись имеет чрезмерные локальные полномочия. Установщик по умолчанию просит
выделенную учётную запись и передаёт пароль непосредственно Windows Service
Control Manager через WinSW; пароль в XML не записывается.

## 6. Сборка aerotech-docflow.exe

Сборка выполняется на Windows той же архитектуры, на которой будет работать
приложение.

```powershell
py -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-build.txt
```

Скачайте проверенный WinSW с официального release и сохраните локально. Для
режима `ServiceAccountMode Prompt` нужен WinSW 3 с поддержкой `<prompt>`;
встроенные учётные записи работают и без интерактивного запроса. Затем:

```powershell
.\packaging\build_windows.ps1 `
  -Python ".\.venv-build\Scripts\python.exe" `
  -WinSWPath "C:\Downloads\WinSW-x64.exe" `
  -Clean
```

Результат:

```text
dist\AerotechDocflow\
  app\
    aerotech-docflow.exe
    _internal\
  config\
    config.example.toml
  service\
    docflow-service.exe
    docflow-service.xml.template
    install-service.ps1
    uninstall-service.ps1
    WinSW.sha256
  docs\
    INSTALLATION.md
  build-manifest.json
  common_paths.ps1
  update.ps1
  update-helper.ps1
```

Build-скрипт:

- создаёт PyInstaller `onedir`-сборку;
- отключает UPX;
- добавляет WinSW под именем `docflow-service.exe`;
- сохраняет SHA-256 WinSW;
- формирует `build-manifest.json` с размером и SHA-256 каждого файла;
- создаёт `dist\dist.zip` и `dist\dist.zip.sha256` для GitHub Release;
- добавляет автономный загрузчик обновления и rollback-helper;
- добавляет конфиг-пример, service scripts и этот документ.

Если `-WinSWPath` не передан, EXE всё равно собирается, но установить службу
будет нельзя.

## 7. Проверка пакета до установки

На тестовом компьютере:

```powershell
cd .\dist\AerotechDocflow
.\app\aerotech-docflow.exe --config .\config\config.example.toml show-config
```

Затем создайте отдельный development TOML с тестовым архивом и выполните:

```powershell
.\app\aerotech-docflow.exe --config "C:\Temp\Docflow\config.toml" preflight
.\app\aerotech-docflow.exe --config "C:\Temp\Docflow\config.toml" run
```

В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Перед production требуется новый приёмочный прогон именно собранного пакета.

## 8. Установка Windows-службы

Скопируйте весь `dist\AerotechDocflow` на целевой компьютер. Создайте production
TOML и успешно выполните preflight. Затем откройте PowerShell от имени
администратора:

```powershell
cd C:\Temp\AerotechDocflow

.\service\install-service.ps1 `
  -InstallDir "C:\Program Files\Aerotech Docflow" `
  -ConfigPath "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  -ServiceAccountMode Prompt `
  -StartService
```

Если Windows пометила скачанный ZIP и блокирует локальные `.ps1`, сначала после
проверки источника и SHA-256 снимите downloaded-file marker только с файлов
пакета:

```powershell
Get-ChildItem C:\Temp\AerotechDocflow -Recurse -File | Unblock-File
```

Не меняйте системную Execution Policy целиком ради установки.

Скрипт:

1. проверяет запуск от администратора;
2. проверяет наличие EXE, WinSW, шаблона и TOML;
3. отказывается перезаписывать существующую службу;
4. копирует пакет в `Program Files`;
5. генерирует WinSW XML с абсолютными путями;
6. выполняет production preflight;
7. только после успешного preflight регистрирует службу;
8. по флагу `-StartService` запускает её.

Режимы `ServiceAccountMode`:

- `Prompt` — рекомендуемый, WinSW спрашивает пользователя и пароль;
- `LocalService` — минимум локальных прав, часто нет доступа к профилю/архиву;
- `NetworkService` — использует машинную учётную запись в сети;
- `LocalSystem` — высокие локальные права, применять только обоснованно.

Проверьте:

```powershell
Get-Service AerotechDocflow
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 9. Логи

Есть два независимых слоя:

```text
C:\ProgramData\Aerotech Docflow\logs\
  docflow_YYYY_MM.txt

C:\ProgramData\Aerotech Docflow\service-logs\
  docflow-service.out.log
  docflow-service.err.log
  docflow-service.wrapper.log
```

Application log связывает `task_id`, `operation_id`, idempotency key и итоговый
файл. Service logs показывают ошибки запуска EXE, неверный рабочий каталог,
проблемы учётной записи и перезапуски WinSW. Также проверяйте Windows Event Log.

## 10. Обновление

1. Соберите новую версию и сохраните build manifest.
2. Проведите тесты и приёмку.
3. Сделайте резервную копию текущего `Program Files` и TOML.
4. Остановите службу:

```powershell
& "C:\Program Files\Aerotech Docflow\service\docflow-service.exe" stop
```

5. Убедитесь, что нет активного NAPS2 и `.scanner.lock`.
6. Замените только каталоги `app`, `service`, `docs` и build manifest в
   `Program Files`. Не копируйте пример поверх рабочего TOML.
7. Не удаляйте TOML, logs, incoming, idempotency и архив.
8. Выполните preflight новым EXE.
9. Запустите службу и проверьте `/health`.

Если новая версия не проходит preflight, служба не должна запускаться; верните
предыдущий каталог программы.

## 11. Удаление службы

Из elevated PowerShell:

```powershell
& "C:\Program Files\Aerotech Docflow\service\uninstall-service.ps1"
```

Скрипт останавливает и снимает регистрацию службы, но намеренно не удаляет:

- приложение;
- `config.toml`;
- логи;
- incoming и карантин;
- idempotency records;
- архив.

Удаление данных выполняется администратором отдельно только после проверки.

## 12. Сетевой архив

Для UNC-пути используйте полный путь:

```toml
[archive]
root = "\\\\archive-server\\documents"
confirmation = "\\\\archive-server\\documents"
```

Не используйте букву сетевого диска: службы обычно не видят пользовательские
drive mappings.

До production необходимо на конкретном файловом сервере проверить:

- доступ служебной учётной записи;
- создание временного файла и hard link;
- атомарность publish;
- отказ при совпадении имени;
- разрыв SMB во время копирования;
- отсутствие изменения существующих PDF;
- восстановление после перезапуска сервера.

Если сервер/SMB не поддерживает требуемый hard link, текущий storage завершится
ошибкой. Ослаблять publish до обычного overwrite/move нельзя.

## 13. Диагностика проблем

Эффективная конфигурация:

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" show-config
```

Production preflight:

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" preflight
```

Состояние lock/NAPS2/артефактов:

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" diagnose
```

Состояние службы:

```powershell
Get-Service AerotechDocflow
& "C:\Program Files\Aerotech Docflow\service\docflow-service.exe" status
```

Если NAPS2 работает вручную, но не из службы, почти всегда сначала проверяются:

1. учётная запись службы;
2. наличие профиля в её `%APPDATA%`;
3. права на scanner/incoming/archive;
4. доступность сетевого устройства из служебной сессии;
5. абсолютный путь `NAPS2.Console.exe`;
6. application, wrapper и Windows Event logs.

## 14. Что эта установка не делает

- не открывает API наружу;
- не настраивает SSH и firewall;
- не создаёт очередь заданий;
- не устанавливает NAPS2 автоматически;
- не создаёт и не очищает реальный архив;
- не удаляет пользовательские документы при uninstall;
- не заменяет приёмочные испытания на целевом оборудовании.

