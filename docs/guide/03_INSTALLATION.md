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

## Установка текущего готового пакета

Готовый пакет находится в:

```text
C:\path\to\aerotech-docflow\dist\AerotechDocflow
```

Откройте PowerShell через **Запуск от имени администратора**:

```powershell
cd "C:\path\to\aerotech-docflow\dist\AerotechDocflow"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Если на компьютере была предыдущая попытка установки:

```powershell
.\cleanup_previous_install.ps1
```

Скрипт удаляет только старую службу, приложение и `ProgramData`. Он не изменяет
корни архивов, PDF или archive marker. Если служба помечена
для удаления, перезагрузите Windows и повторите cleanup.

Перед установкой откройте единственный машинный конфиг пакета:

```powershell
notepad ".\config\config.production.toml"
```

Укажите в нём NAPS2/profile, incoming, archive root и confirmation, уникальный
archive_id, logs, idempotency и остальные настройки. Затем проверьте, что
выбранный archive root уже существует. Установщик читает эти значения из TOML;
собственных путей архива и incoming у него больше нет.

Установите программу:

```powershell
.\install_current_machine.ps1 -ConfirmArchive
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

Закройте административный PowerShell. Под пользователем, который создал профиль
NAPS2, выполните:

```powershell
& "C:\Program Files\Aerotech Docflow\start-manually.ps1"
```

Оставьте окно открытым. В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`/health` не запускает сканер. После успешной проверки можно выполнить один
физический тест по [разделу ежедневной работы](05_DAILY_OPERATION.md).

## Установка на другой компьютер

Сценарий `install_current_machine.ps1` использует пути только из переданного
production TOML. Для другого устройства:

1. скопируйте пакет целиком;
2. отредактируйте `config\config.production.toml` либо создайте машинный TOML;
3. при отдельном TOML передайте `-ConfigSource "C:\path\config.toml"`;
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
