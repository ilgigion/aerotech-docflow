# Чистая установка Aerotech Docflow

Этот документ описывает первоначальную административную установку. Обычные
последующие обновления выполняются отдельным Aerotech Updater.

## 1. Подготовьте зависимости

Установите драйвер сканера, NAPS2 и WinSW. Под будущей учётной записью службы
создайте и физически проверьте профиль NAPS2.

## 2. Соберите или получите release ZIP

```text
aerotech-docflow-v1.3.0.zip
```

ZIP содержит только `app`, `service`, `version.json` и
`build-manifest.json`. Конфиг и установочные скрипты в него не входят.

Распакуйте ZIP:

```powershell
Expand-Archive `
  "C:\Downloads\aerotech-docflow-v1.3.0.zip" `
  "C:\Temp\AerotechDocflowRelease"
```

Не смешивайте файлы разных версий.

## 3. Создайте машинный конфиг

Скопируйте обезличенный шаблон из исходного проекта в закрытый локальный путь:

```powershell
New-Item -ItemType Directory "C:\Secure\AerotechDocflow" -Force
Copy-Item `
  "C:\path\to\aerotech-docflow\packaging\config.production.example.toml" `
  "C:\Secure\AerotechDocflow\config.toml"
notepad "C:\Secure\AerotechDocflow\config.toml"
```

Заполните NAPS2, incoming, archive root/confirmation, `archive_id`, типы
документов, логи и idempotency. Корень архива должен уже существовать.

## 4. Установите программную часть

Откройте Windows PowerShell от имени администратора в доверенной копии исходного
проекта:

```powershell
cd "C:\path\to\aerotech-docflow"

.\packaging\install_current_machine.ps1 `
  -PackageRoot "C:\Temp\AerotechDocflowRelease" `
  -ConfigSource "C:\Secure\AerotechDocflow\config.toml" `
  -ConfirmArchive
```

Скрипт проверяет manifest release, конфиг, NAPS2, identity архива и выполняет
preflight. Он не запускает физический скан.

Ожидаемый итог:

```text
INSTALLATION FILES READY
No Windows service was created.
```

## 5. Ручная проверка

Под пользователем с профилем NAPS2:

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  run
```

В другом окне:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Проведите один физический тест на тестовом документе и тестовом архиве. Затем
остановите ручной сервер через `Ctrl+C`.

## 6. Установите Windows-службу

```powershell
cd "C:\path\to\aerotech-docflow"

.\packaging\service\install-service.ps1 `
  -InstallDir "C:\Program Files\Aerotech Docflow" `
  -ConfigPath "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  -ServiceAccountMode Prompt `
  -StartService
```

Укажите обычный пароль Windows-пользователя с настроенным профилем NAPS2, а не
PIN Windows Hello.

Проверка:

```powershell
Get-Service AerotechDocflow
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 7. Установите постоянный updater

Запустите от администратора:

```text
AerotechUpdaterSetup.exe
```

Setup создаст:

```text
C:\Program Files\Aerotech Updater\AerotechUpdater.exe
C:\Users\Public\Desktop\Обновить Aerotech Docflow.lnk
C:\Temp\Aerotech Docflow\
```

Setup не заменяет рабочий `config.toml`. Если версию старой установки нельзя
подтвердить однозначно, он остановится с `LEGACY_VERSION_UNKNOWN`.

## 8. Рабочие пути

```text
C:\Program Files\Aerotech Docflow\                 приложение
C:\Program Files\Aerotech Updater\                 постоянный updater
C:\ProgramData\Aerotech Docflow\config\config.toml рабочий конфиг
C:\ProgramData\Aerotech Docflow\incoming\          сканы и lock
C:\ProgramData\Aerotech Docflow\logs\              логи
C:\Temp\Aerotech Docflow\                           ZIP обновлений
<ARCHIVE_ROOT>\                                      архив PDF
```

Updater может дописывать только `logs\updater.log` внутри ProgramData и не
изменяет конфиг, incoming, state или архив.
