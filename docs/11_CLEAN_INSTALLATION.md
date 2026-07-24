# Чистая установка Aerotech Docflow

Все машинные значения задаются перед установкой в
`config\config.production.toml`. Например:

```text
архив      D:\Archive
incoming   D:\incoming
NAPS2      C:\Program Files\NAPS2\NAPS2.Console.exe
профиль    EPSON DS-790WN
API        http://127.0.0.1:8000
```

Сначала приложение устанавливается без Windows-службы. Оно запускается под
текущим пользователем и поэтому видит существующий профиль NAPS2. Настройка
службы выполняется позже, когда будет создана отдельная служебная учётная
запись с паролем.

## Шаг 1. Откройте новый пакет

Пакет находится здесь:

```text
D:\PROG_PROJECTS\aerotech-docflow\dist\AerotechDocflow
```

Не копируйте отдельные файлы из старых каталогов. Все команды ниже выполняются
из нового пакета.

## Шаг 2. Удалите предыдущую неоконченную установку

Откройте **Windows PowerShell от имени администратора** и выполните:

```powershell
cd "D:\PROG_PROJECTS\aerotech-docflow\dist\AerotechDocflow"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\cleanup_previous_install.ps1
```

Скрипт удаляет только:

- службу `AerotechDocflow`;
- `C:\Program Files\Aerotech Docflow`;
- `C:\ProgramData\Aerotech Docflow`.

Он не изменяет архивные корни, PDF или marker-файлы независимо от путей и
`archive_id`.

Ожидаемый конец вывода:

```text
PREVIOUS INSTALLATION REMOVED
All archives were preserved.
```

Если написано, что служба помечена для удаления, перезагрузите Windows и снова
выполните этот шаг.

## Шаг 3. Проверьте архив перед привязкой

Откройте `config\config.production.toml`, возьмите значение `archive.root` и
проверьте именно этот каталог через `Get-Item`/`Get-ChildItem`.

Убедитесь, что это нужный архив. Установочный скрипт не создаёт корень архива и
не удаляет существующие PDF.

## Шаг 4. Установите программу

В том же elevated PowerShell:

```powershell
.\install_current_machine.ps1 -ConfirmArchive
```

Сначала отредактируйте `config\config.production.toml`. Все перечисленные ниже
пути берутся из него, а не из установочного сценария. Затем запустите установку.

Скрипт:

1. проверит NAPS2 и `archive.root` из TOML;
2. создаст `scanner.incoming_dir` из TOML;
3. создаст каталоги в `ProgramData`;
4. скопирует приложение в `Program Files`;
5. установит готовый production `config.toml`;
6. создаст marker с `archive_id` из TOML, если marker ещё отсутствует;
7. выполнит preflight без запуска сканера.

Ожидаемый результат:

```text
"status": "ok"
"environment": "production"
"archive_root": "D:\\Archive"
INSTALLATION FILES READY
No Windows service was created.
```

## Шаг 5. Запустите приложение вручную

Закройте elevated PowerShell. Откройте обычный PowerShell от пользователя,
который видит профиль NAPS2, и выполните:

```powershell
& "C:\Program Files\Aerotech Docflow\start-manually.ps1"
```

Оставьте это окно открытым. Нормальный вывод содержит:

```text
Uvicorn running on http://127.0.0.1:8000
```

## Шаг 6. Проверьте API без сканирования

Откройте второй обычный PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Ожидается:

```text
status  : ok
service : aerotech-docflow
```

Проверка `/health` не запускает сканер.

## Шаг 7. Проведите один тестовый скан

Перед тестом:

1. используйте тестовый документ;
2. выключите VPN;
3. убедитесь, что в автоподатчике находится только этот документ;
4. сохраните список или SHA-256 существующих PDF.

Пример запроса:

```powershell
$body = @{
    task_id = "INSTALL-TEST-001"
    doc_type = "НКЛ"
    document_number = "INSTALL-001"
    scanner_profile = "EPSON DS-790WN"
    idempotency_key = "install_test_001"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/scan" `
  -ContentType "application/json" `
  -Body $body
```

Проверьте, что создан ровно один открывающийся PDF и существующие файлы не
изменены.

## Шаг 8. Остановка программы

В окне с сервером нажмите `Ctrl+C`. После этого `/health` станет недоступен —
это нормально для ручного режима.

## Windows-служба

На первом этапе службу не устанавливайте. PIN Windows Hello нельзя использовать
как пароль службы. Для постоянной работы сначала создайте отдельного локального
пользователя с паролем, настройте под ним NAPS2 и повторите аппаратную проверку.
Только после этого используйте `service\install-service.ps1`.

## Где находятся рабочие файлы

```text
C:\Program Files\Aerotech Docflow\                программа
C:\ProgramData\Aerotech Docflow\config\config.toml
C:\ProgramData\Aerotech Docflow\logs\             application logs
C:\ProgramData\Aerotech Docflow\data\idempotency\
D:\incoming\                                       временные сканы и lock
D:\Archive\                                        архив PDF
```
