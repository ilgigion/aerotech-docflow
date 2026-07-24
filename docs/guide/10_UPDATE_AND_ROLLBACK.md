# 10. Автономное обновление и откат

## Главное правило

Обновление выполняет постоянное отдельное приложение:

```text
C:\Program Files\Aerotech Updater\AerotechUpdater.exe
```

Оператор запускает ярлык на общем рабочем столе:

```text
Обновить Aerotech Docflow
```

Updater не подключается к GitHub, VPS или другим сетевым источникам и ничего
не скачивает. Готовый ZIP нужно заранее положить в:

```text
C:\Temp\Aerotech Docflow\
```

## Установка updater один раз

Администратор запускает `AerotechUpdaterSetup.exe`. Setup:

1. проверяет права администратора;
2. проверяет существующую установку Aerotech Docflow;
3. определяет установленную версию по имеющимся метаданным;
4. при неоднозначной версии останавливается с `LEGACY_VERSION_UNKNOWN`;
5. устанавливает постоянный `AerotechUpdater.exe`;
6. создаёт ярлык `Обновить Aerotech Docflow`;
7. создаёт каталог пакетов и `logs\updater.log`;
8. не изменяет рабочий `config.toml`.

Updater и приложение имеют независимые жизненные циклы. Новый Setup требуется
только для обновления самого updater, а не для каждого релиза Docflow.

## Подготовка ZIP

Скачайте нужный asset из доверенного GitHub Release вручную. Имя:

```text
aerotech-docflow-v1.3.0.zip
```

Не распаковывайте ZIP. Скопируйте его целиком:

```text
C:\Temp\Aerotech Docflow\aerotech-docflow-v1.3.0.zip
```

Если ZIP несколько, updater выберет максимальную корректную SemVer-версию,
которая строго новее установленной. Равные и старые версии игнорируются.

## Формат релиза

```text
app\
service\
version.json
build-manifest.json
```

`version.json`:

```json
{
  "version": "1.3.0",
  "config_schema": 2
}
```

`build-manifest.json` — массив всех файлов кроме самого manifest с полями
`path`, `size`, `sha256`.

В ZIP отсутствуют updater, PowerShell update-скрипты, конфиги, логи, state,
incoming, PDF и другие рабочие данные.

## Что происходит до установки

Updater показывает видимые проверки:

```text
[OK] Установленная версия: 1.2.0
[OK] Найден пакет: aerotech-docflow-v1.3.0.zip
[OK] Версия пакета: 1.3.0
[OK] Архив ZIP проверен
[OK] Манифест проверен
[OK] Конфигурация найдена
[OK] Предварительная проверка пройдена
[OK] Сканирование сейчас не выполняется
```

Проверяются:

- структура ZIP и отсутствие опасных путей;
- размер и SHA-256 каждого файла;
- отсутствие лишних файлов;
- версия и `config_schema`;
- production `preflight` нового EXE с текущим конфигом;
- наличие и SHA-256 действующего `service\docflow-service.xml`;
- отсутствие NAPS2;
- отсутствие `<incoming>\.scanner.lock`.

Рабочая служба на этом этапе ещё не остановлена. После успешных проверок
updater ждёт нажатия клавиши. Неинтерактивный запуск установку не начинает.

## Повторная проверка сканирования

После нажатия клавиши updater обязательно повторяет проверки NAPS2 и
`.scanner.lock`. Они повторяются ещё раз после остановки службы. Если за время
ожидания начался скан, установка не переключается.

## Переключение версии

```text
[1/6] Распаковка и проверка завершены.
[2/6] Остановка службы...
[3/6] Создание резервной копии...
[4/6] Установка новой версии...
[5/6] Запуск службы...
[6/6] Проверка работоспособности...
```

Старая программа временно перемещается в:

```text
C:\Temp\Aerotech Docflow\rollback
```

Новая устанавливается в канонический путь:

```text
C:\Program Files\Aerotech Docflow
```

Учётная запись существующей Windows-службы не изменяется. Updater переносит
действующий `service\docflow-service.xml` байт-в-байт и повторно проверяет его
SHA-256. Благодаря этому сохраняются путь к `config.toml`, service account,
`logpath`, параметры перезапуска и остальные настройки WinSW. Шаблон из нового
ZIP не заменяет рабочий XML существующей службы.

Путь пакетов всегда абсолютный: `C:\Temp\Aerotech Docflow`. Значение
`SystemDrive=C:` не преобразуется в относительный путь `C:Temp\...`.

## Проверка результата

Успех подтверждается только после того, как:

1. служба перешла в Running;
2. `GET http://127.0.0.1:8000/health` вернул `status=ok`;
3. `/health.version` совпал с `version.json` нового пакета.

Выполняются десять попыток с интервалом две секунды. После успеха удаляются ZIP,
`unpacked` и `rollback`.

## Автоматический откат

При ошибке после остановки службы updater:

1. останавливает нерабочую новую службу;
2. удаляет неполную новую установку;
3. возвращает `rollback`;
4. запускает старую службу;
5. проверяет старый `/health`;
6. оставляет исходный ZIP для диагностики.

Если старая версия восстановлена, пользователь получает однозначное сообщение.
Если не прошёл и откат, updater выводит `ROLLBACK_FAILED`; отправлять запросы
`/scan` до вмешательства администратора нельзя.

## Что updater может менять

Разрешено:

```text
C:\Program Files\Aerotech Docflow
C:\Temp\Aerotech Docflow
C:\ProgramData\Aerotech Docflow\logs\updater.log
```

Запрещено изменять, удалять или перемещать:

```text
C:\ProgramData\Aerotech Docflow\config
C:\ProgramData\Aerotech Docflow\incoming
C:\ProgramData\Aerotech Docflow\state
рабочий config.toml
архив и существующие PDF
```

## Лог

```text
C:\ProgramData\Aerotech Docflow\logs\updater.log
```

Лог содержит версии, имя пакета, результаты manifest/preflight, действия со
службой, health-check, откат и код ошибки. Содержимое рабочего конфига и секреты
в лог не записываются.

После успеха или ошибки окно остаётся открытым до нажатия клавиши.

## Сборка релиза

```powershell
.\scripts\build_release.ps1 `
  -Version "1.3.0" `
  -ConfigSchema 2 `
  -WinSWPath "C:\Tools\WinSW-x64.exe" `
  -Python ".\.venv-build\Scripts\python.exe"
```

Результат:

```text
dist\aerotech-docflow-v1.3.0.zip
```

Сборка updater выполняется отдельно и не для каждого релиза:

```powershell
.\scripts\build_updater.ps1 `
  -Version "1.0.0" `
  -Python ".\.venv-build\Scripts\python.exe"
```

Результаты:

```text
dist\updater\AerotechUpdater.exe
dist\updater\AerotechUpdaterSetup.exe
```

Manifest на первом этапе не является цифровой подписью. Доверенной границей
считается администратор, поместивший ZIP в `C:\Temp\Aerotech Docflow`.
