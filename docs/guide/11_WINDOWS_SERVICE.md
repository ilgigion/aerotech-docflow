# 11. Windows-служба и учётные записи

## Ручной режим и служба — разные способы запуска

### Ручной режим

```powershell
& "C:\Program Files\Aerotech Docflow\start-manually.ps1"
```

Процесс работает под текущим вошедшим пользователем и видит его `%APPDATA%`,
профили NAPS2, сетевые ресурсы и права. Окно должно оставаться открытым.

### Windows-служба

Служба стартует через WinSW без интерактивного терминала, может запускаться
после reboot и работает под явно выбранной Windows-учётной записью.

## Почему служба просит учётные данные

Это не авторизация HTTP API. Windows должна знать, от чьего имени предоставить
процессу доступ к NAPS2, сканеру, incoming и архиву.

PIN Windows Hello не является паролем службы. Для Microsoft Account нужен
фактический пароль аккаунта; для локальной service account — её пароль.

WinSW с `<prompt>console</prompt>` передаёт credentials в Windows Service Control
Manager. Пароль не записывается в `docflow-service.xml` или application log.

## Почему профиль может исчезнуть

Профили обычно находятся в:

```text
C:\Users\ИМЯ\AppData\Roaming\NAPS2\profiles.xml
```

Профиль, созданный под `esens`, не существует автоматически для LocalSystem,
LocalService или `docflow-service`.

## Рекомендуемый production-вариант

1. создать отдельного локального/доменного пользователя с паролем;
2. выдать ему только необходимые права;
3. войти под ним интерактивно один раз;
4. настроить и проверить NAPS2;
5. выдать modify для incoming, logs, idempotency и требуемого места архива;
6. установить службу через `ServiceAccountMode Prompt`;
7. выполнить отдельную аппаратную приёмку из service session.

До этого используйте ручной режим: он проще и уже проверяет профиль текущего
пользователя.

## Установка службы

Только после подготовки учётной записи, из elevated PowerShell:

```powershell
$installed = "C:\Program Files\Aerotech Docflow"
$config = "C:\ProgramData\Aerotech Docflow\config\config.toml"

& "$installed\service\install-service.ps1" `
  -InstallDir $installed `
  -ConfigPath $config `
  -ServiceAccountMode Prompt `
  -StartService
```

Installer сначала выполняет preflight и только затем регистрирует службу.

## Другие режимы

| Режим | Особенности |
|---|---|
| `Prompt` | Пользовательская/service account; рекомендуемый после настройки профиля |
| `LocalService` | Мало локальных прав, обычно нет пользовательского NAPS2-профиля |
| `NetworkService` | В сети действует от имени компьютера; профиль тоже отдельный |
| `LocalSystem` | Чрезмерные локальные права, не использовать как быстрый обход |

Direct mode без GUI-профиля может уменьшить зависимость от `%APPDATA%`, но его
нужно отдельно протестировать с выбранным driver/device.

## Управление службой

```powershell
Get-Service AerotechDocflow
Start-Service AerotechDocflow
Stop-Service AerotechDocflow
Restart-Service AerotechDocflow
```

WinSW-команды:

```powershell
& "C:\Program Files\Aerotech Docflow\service\docflow-service.exe" status
& "C:\Program Files\Aerotech Docflow\service\docflow-service.exe" restart
```

## Ошибка logon failure

Симптомы:

- служба `Stopped` сразу после старта;
- `/health` недоступен;
- application log пуст;
- Event ID 7038/7000;
- wrapper log говорит `user name or password is incorrect`.

Это означает, что EXE не запускался. Проверьте:

1. не введён ли PIN вместо пароля;
2. точное имя account;
3. срок действия пароля;
4. право Log on as a service;
5. доступ к пользовательскому профилю.

Не повторяйте install поверх существующей записи. Исправьте credentials через
Services MMC либо удалите службу и установите заново.

## Логи службы

```powershell
Get-ChildItem "C:\ProgramData\Aerotech Docflow\service-logs"
Get-Content "C:\ProgramData\Aerotech Docflow\service-logs\docflow-service.wrapper.log"
```

Если wrapper пишет успешный старт, но `/health` отсутствует, проверяйте `.err`,
application logs и production preflight под service account.
