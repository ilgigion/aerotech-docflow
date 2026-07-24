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
    config.production.toml
    config.production.example.toml
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

D:\REPLACE_WITH_ARCHIVE_ROOT\
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
D:\REPLACE_WITH_ARCHIVE_ROOT\.aerotech-docflow-archive.json
```

Содержимое:

```json
{
  "marker": "aerotech-docflow-archive-v1",
  "archive_id": "REPLACE_WITH_UNIQUE_ARCHIVE_ID"
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

Если профиль `MY_NAPS2_PROFILE` создан под оператором, служба под LocalSystem,
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

## 6. Сборка ZIP-релиза

Сборка выполняется на Windows той же архитектуры, на которой будет работать
приложение.

```powershell
py -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-build.txt
```

Скачайте проверенный WinSW с официального release и сохраните локально. Затем:

```powershell
.\scripts\build_release.ps1 `
  -Version "1.3.0" `
  -ConfigSchema 2 `
  -Python ".\.venv-build\Scripts\python.exe" `
  -WinSWPath "C:\Downloads\WinSW-x64.exe"
```

Результат:

```text
dist\aerotech-docflow-v1.3.0.zip

ZIP:

app\
  aerotech-docflow.exe
  _internal\
service\
  docflow-service.exe
  docflow-service.xml.template
version.json
build-manifest.json
```

Build-скрипт:

- создаёт PyInstaller `onedir`-сборку;
- отключает UPX;
- добавляет WinSW под именем `docflow-service.exe`;
- формирует `build-manifest.json` с размером и SHA-256 каждого файла;
- создаёт один ZIP фиксированного формата;
- повторно валидирует готовый ZIP;
- выводит SHA-256 ZIP в консоль.

Updater, конфиги, документация и PowerShell update-скрипты в ZIP не входят.

## 7. Проверка пакета до установки

Распакуйте ZIP в отдельную тестовую папку и используйте отдельный тестовый TOML:

```powershell
Expand-Archive .\dist\aerotech-docflow-v1.3.0.zip C:\Temp\DocflowRelease
& C:\Temp\DocflowRelease\app\aerotech-docflow.exe `
  --config "C:\Temp\Docflow\config.toml" show-config
```

Затем создайте отдельный development TOML с тестовым архивом и выполните:

```powershell
& C:\Temp\DocflowRelease\app\aerotech-docflow.exe `
  --config "C:\Temp\Docflow\config.toml" preflight
```

В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Перед production требуется новый приёмочный прогон именно собранного пакета.

## 8. Первоначальная установка Windows-службы

Публичный release ZIP предназначен для стандартизированных обновлений и не
содержит установочные скрипты. Первоначальная установка остаётся контролируемой
административной операцией из доверенной копии исходного проекта. Используйте
внутренний `packaging\install_current_machine.ps1`, затем:

```powershell
cd C:\path\to\aerotech-docflow

.\packaging\service\install-service.ps1 `
  -InstallDir "C:\Program Files\Aerotech Docflow" `
  -ConfigPath "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  -ServiceAccountMode Prompt `
  -StartService
```

Внутренний скрипт:

1. проверяет запуск от администратора;
2. проверяет наличие EXE, WinSW, шаблона и TOML;
3. отказывается перезаписывать существующую службу;
4. использует заранее установленную программную часть в `Program Files`;
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
  updater.log

C:\ProgramData\Aerotech Docflow\service-logs\
  docflow-service.out.log
  docflow-service.err.log
  docflow-service.wrapper.log
```

Application log связывает `task_id`, `operation_id`, idempotency key и итоговый
файл. Service logs показывают ошибки запуска EXE, неверный рабочий каталог,
проблемы учётной записи и перезапуски WinSW. Также проверяйте Windows Event Log.

## 10. Обновление

1. Один раз установите `AerotechUpdaterSetup.exe`.
2. Скачайте ZIP-релиз вручную.
3. Положите его без распаковки в `C:\Temp\Aerotech Docflow`.
4. Закройте NAPS2.
5. Запустите ярлык `Обновить Aerotech Docflow`.
6. Прочитайте результаты проверок и нажмите клавишу.
7. Дождитесь сообщения об успехе либо автоматическом откате.

Updater не скачивает файлы, повторно проверяет NAPS2 и `.scanner.lock` после
подтверждения, сохраняет `ProgramData` и проверяет новую службу через `/health`.
Полный алгоритм: [guide/10_UPDATE_AND_ROLLBACK.md](guide/10_UPDATE_AND_ROLLBACK.md).

## 11. Удаление службы

Из elevated PowerShell:

```powershell
cd "C:\path\to\aerotech-docflow"
.\packaging\service\uninstall-service.ps1
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

