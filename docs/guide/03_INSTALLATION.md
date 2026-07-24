# 3. Чистая установка и первый запуск

## Предварительные требования

На чистом Windows-компьютере должны быть установлены:

1. драйвер сканера от производителя;
2. NAPS2 с `NAPS2.Console.exe`;
3. рабочий профиль NAPS2 либо параметры direct mode;
4. локальный NTFS-диск для incoming;
5. существующий и заранее выбранный корень архива;
6. PowerShell 5.1 или новее.

Python на целевом компьютере не нужен: он включён в PyInstaller `onedir`.
WinSW нужен только для необязательного запуска как Windows-служба.

## Перед установкой

Сначала проверьте сканер непосредственно в NAPS2:

1. откройте NAPS2 под будущим рабочим Windows-пользователем;
2. создайте профиль;
3. выполните один тестовый скан;
4. убедитесь, что имя профиля отображается в
   `%APPDATA%\NAPS2\profiles.xml`;
5. закройте NAPS2 перед запуском Docflow.

## Первоначальная установка приложения

Публичный release является ZIP фиксированного формата:

```text
C:\path\to\aerotech-docflow\dist\aerotech-docflow-v1.3.0.zip
```

Он не содержит конфиг и установочные PowerShell-скрипты. Первоначальную
установку выполняет администратор из доверенной копии исходного проекта.
Распакуйте ZIP:

```powershell
Expand-Archive `
  "C:\path\to\aerotech-docflow\dist\aerotech-docflow-v1.3.0.zip" `
  "C:\Temp\AerotechDocflowRelease"
```

Создайте отдельный проверенный машинный конфиг вне release ZIP, например:

```powershell
C:\Secure\AerotechDocflow\config.toml
```

Укажите в нём NAPS2/profile, incoming, archive root и confirmation, уникальный
archive_id, logs, idempotency и остальные настройки. Затем проверьте, что
выбранный archive root уже существует. Установщик читает эти значения из TOML;
собственных путей архива и incoming у него больше нет.

Установите программу:

```powershell
cd "C:\path\to\aerotech-docflow"
.\packaging\install_current_machine.ps1 `
  -PackageRoot "C:\Temp\AerotechDocflowRelease" `
  -ConfigSource "C:\Secure\AerotechDocflow\config.toml" `
  -ConfirmArchive
```

Сценарий создаёт каталоги incoming/log/idempotency из TOML, копирует программу
и этот production-конфиг, формирует marker из `archive.archive_id` и выполняет
`preflight`. Он не запускает сканер и намеренно не регистрирует Windows-службу.

## Проверка установки

Ожидаемый preflight:

```json
{
  "status": "ok",
  "environment": "production",
  "production": true,
  "archive_root": "ПУТЬ ИЗ CONFIG.TOML",
  "incoming_dir": "ПУТЬ ИЗ CONFIG.TOML"
}
```

Проверьте установленные файлы:

```powershell
Test-Path "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe"
Test-Path "C:\ProgramData\Aerotech Docflow\config\config.toml"
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  preflight
```

Все значения должны быть `True`.

## Первый запуск

Под пользователем, который создал профиль NAPS2, выполните:

```powershell
& "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe" `
  --config "C:\ProgramData\Aerotech Docflow\config\config.toml" `
  run
```

Оставьте окно открытым. В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`/health` не запускает сканер. После успешной проверки можно выполнить один
физический тест по [разделу ежедневной работы](05_DAILY_OPERATION.md).

## Установка на другой компьютер

Сценарий `install_current_machine.ps1` использует пути только из переданного
машинного TOML. Для другого устройства:

1. скопируйте release ZIP и распакуйте его;
2. создайте отдельный машинный TOML;
3. передайте `-PackageRoot` и `-ConfigSource` внутреннему установщику;
4. установщик проверит root, identity marker и выполнит preflight;
5. сначала запускайте программу вручную;
6. только после аппаратной приёмки решайте вопрос Windows-службы.

## Чего нельзя делать при установке

- не копировать отдельные DLL из старой версии;
- не размещать `config.toml` внутри архива;
- не создавать marker в нескольких несвязанных архивах с одним `archive_id`;
- не запускать production без preflight;
- не устанавливать службу под LocalSystem только ради обхода пароля;
- не проверять первый запуск сразу на единственном экземпляре важного документа.
