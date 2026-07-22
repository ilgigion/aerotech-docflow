# 10. Обновление, откат и удаление

## Автоматизированное безопасное обновление

В корне новой сборки находится `update_current_machine.ps1`. Запускайте именно
скрипт из **нового распакованного пакета**, расположенного вне
`C:\Program Files\Aerotech Docflow`. Откройте PowerShell от имени администратора:

```powershell
cd "D:\Updates\AerotechDocflow"
.\update_current_machine.ps1
```

По умолчанию скрипт использует:

```text
установленная программа: C:\Program Files\Aerotech Docflow
рабочий конфиг:          C:\ProgramData\Aerotech Docflow\config\config.toml
новая сборка:            папка, из которой запущен скрипт
```

Скрипт последовательно:

1. требует права администратора и проверяет SHA-256 файлов новой сборки по
   `build-manifest.json`;
2. читает путь `scanner.incoming_dir` только из рабочего конфига;
3. отказывается продолжать, если запущен NAPS2 или существует `.scanner.lock`;
4. останавливает службу `AerotechDocflow` и установленный процесс приложения,
   затем повторяет проверку NAPS2 и lock;
5. создаёт проверенную SHA-256 backup-копию рабочего `config.toml`;
6. переименовывает установленную папку в соседнюю rollback-папку с timestamp;
7. копирует новую сборку в новую чистую папку установки;
8. для существующей WinSW-службы безопасно сохраняет сгенерированный XML;
9. выполняет `preflight` новым EXE с прежним рабочим конфигом.

Успешное обновление намеренно **не запускает** ни приложение, ни службу. После
изучения результата службу можно запустить отдельной командой:

```powershell
Start-Service AerotechDocflow
Get-Service AerotechDocflow
Invoke-RestMethod http://127.0.0.1:8000/health
```

Если `preflight`, копирование или проверка новой папки завершается ошибкой,
скрипт автоматически возвращает старую папку на прежнее место. Неудачная новая
папка сохраняется рядом с суффиксом `.failed-update-TIMESTAMP` для диагностики.
Старая версия остаётся остановленной и автоматически не запускается.

После успешного обновления сохраняются:

```text
C:\Program Files\Aerotech Docflow.rollback-TIMESTAMP
C:\ProgramData\Aerotech Docflow\config\config.toml.before-update-TIMESTAMP.bak
```

`C:\ProgramData\Aerotech Docflow` не заменяется и не очищается. Единственное
добавление в нём — запрошенная backup-копия конфига. Скрипт не копирует и не
изменяет incoming, idempotency, логи, archive marker и PDF в архиве. Команда
`preflight` не запускает сканер и не создаёт архивный документ.

Если используются нестандартные пути установки или конфига:

```powershell
.\update_current_machine.ps1 `
  -InstallDir "C:\Apps\Aerotech Docflow" `
  -ConfigPath "C:\DocflowData\config\config.toml"
```

Не удаляйте rollback-папку до проверки `/health` и контрольного скана на
тестовом архиве. Не удаляйте `.scanner.lock` только ради запуска обновления:
сначала выполните диагностику и установите, какому процессу он принадлежит.

## Что обновляется, а что сохраняется

Обновляется:

```text
C:\Program Files\Aerotech Docflow
```

Сохраняется:

```text
C:\ProgramData\Aerotech Docflow\config\config.toml
C:\ProgramData\Aerotech Docflow\logs
C:\ProgramData\Aerotech Docflow\data\idempotency
D:\incoming
D:\Archive
```

Конфиг может потребовать миграции, если новая версия добавляет обязательные
ключи. Никогда не заменяйте рабочий TOML новым `config.example.toml`.

## Сборка новой версии

На компьютере разработчика:

```powershell
cd "D:\PROG_PROJECTS\aerotech-docflow"
py -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-build.txt
```

Обновите номер `application.version` в production-шаблоне и соберите:

```powershell
.\packaging\build_windows.ps1 `
  -Python ".\.venv-build\Scripts\python.exe" `
  -WinSWPath "C:\путь\к\WinSW-x64.exe" `
  -Clean
```

Результат:

```text
dist\AerotechDocflow
```

Build script создаёт пакет с нуля, поэтому старая DLL или WinSW не переживает
сборку незаметно. `build-manifest.json` содержит размер и SHA-256 каждого файла.

## Проверка до обновления

1. выполните unit-тесты;
2. проверьте manifest;
3. запустите новый EXE с копией production-конфига;
4. выполните `show-config` и `preflight`;
5. проведите приёмку на тестовом архиве;
6. сохраните Git commit и отчёт.

Новый EXE можно проверить без установки:

```powershell
& "D:\PROG_PROJECTS\aerotech-docflow\dist\AerotechDocflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  preflight
```

Preflight не запускает сканер.

## Безопасное обновление ручной установки

Откройте PowerShell от администратора. Сначала остановите сервер `Ctrl+C` и
проверьте:

```powershell
Get-Process aerotech-docflow,NAPS2* -ErrorAction SilentlyContinue
Test-Path "D:\incoming\.scanner.lock"
```

Если есть активный процесс или lock, сначала завершите диагностику.

Создайте резервные копии:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$installed = "C:\Program Files\Aerotech Docflow"
$rollback = "C:\Program Files\Aerotech Docflow.rollback.$stamp"

Copy-Item `
  "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  "C:\ProgramData\Aerotech Docflow\config\config.toml.$stamp.backup"

Move-Item $installed $rollback
```

Копируйте новый пакет как целый каталог, а не поверх старого `_internal`:

```powershell
Copy-Item `
  "D:\PROG_PROJECTS\aerotech-docflow\dist\AerotechDocflow" `
  $installed `
  -Recurse
```

Проверьте:

```powershell
& "$installed\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  preflight
```

После preflight запустите вручную и проверьте `/health`, затем один тестовый
скан. Удалять rollback-каталог можно только после приёмки.

## Откат

Остановите новый процесс. Затем из elevated PowerShell:

```powershell
Rename-Item `
  "C:\Program Files\Aerotech Docflow" `
  "Aerotech Docflow.failed-update"

Rename-Item `
  "C:\Program Files\Aerotech Docflow.rollback.YYYYMMDD_HHMMSS" `
  "Aerotech Docflow"
```

Если формат конфига менялся, восстановите совместимую backup-копию. Выполните
preflight старым EXE, затем запустите его. Не меняйте архив и idempotency без
отдельного плана миграции.

## Обновление Windows-службы

1. остановить службу;
2. убедиться в отсутствии дочернего EXE/NAPS2/lock;
3. сохранить XML и ProgramData;
4. заменить целиком `Program Files`;
5. проверить, что WinSW и XML имеют базовое имя `docflow-service`;
6. preflight новым EXE;
7. запустить службу;
8. проверить status, `/health` и service logs.

## Полное удаление

`cleanup_previous_install.ps1` удаляет службу, Program Files и ProgramData. Он
не читает, не изменяет и не удаляет корни архивов, PDF или archive marker.

Перед удалением сохраните config, idempotency и logs, если они нужны для аудита.
Не удаляйте `D:\Archive` вместе с приложением.
