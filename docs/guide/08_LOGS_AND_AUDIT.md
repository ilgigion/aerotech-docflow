# 8. Логи и аудит

## Виды логов

### Application log

```text
C:\ProgramData\Aerotech Docflow\logs\docflow_YYYY_MM.txt
```

Содержит стадии document flow, NAPS2, storage, lock и idempotency. Файл может не
появиться после одного `/health`: file logging настраивается при обработке
документа.

### Консоль ручного запуска

При `start-manually.ps1` Uvicorn пишет startup, HTTP и shutdown в открытое окно
PowerShell. Для расследования не закрывайте окно до копирования нужного текста.

### WinSW logs

Только при работе Windows-службы:

```text
C:\ProgramData\Aerotech Docflow\service-logs\
```

Wrapper log объясняет установку, старт, logon failure и перезапуски. `.out` и
`.err` содержат stdout/stderr дочернего EXE.

### Windows Event Log

Service Control Manager фиксирует ошибки учётной записи и запуска службы.
Application code обычно ищется в application log, а не в Event Log.

## Основные идентификаторы

| Идентификатор | Для чего используется |
|---|---|
| `task_id` | Связь с бизнес-задачей |
| `idempotency_key` | Связь повторов одной операции |
| `operation_id` | Точная техническая попытка через все стадии |
| `file_name` | Финальный PDF |

Ни один из них не заменяет остальные. Для доказательства сохраняются все четыре.

## Поиск операции

```powershell
$logDir = "C:\ProgramData\Aerotech Docflow\logs"

Get-ChildItem $logDir -Filter "docflow_*.txt" |
  Select-String -Pattern "SCAN_20260721_135102_a1b2c3"
```

По задаче:

```powershell
Get-ChildItem $logDir -Filter "docflow_*.txt" |
  Select-String -Pattern "task_id=53243"
```

По idempotency key:

```powershell
Get-ChildItem $logDir -Filter "docflow_*.txt" |
  Select-String -SimpleMatch "planfix_53243_НКЛ_001"
```

По ошибкам:

```powershell
Get-ChildItem $logDir -Filter "docflow_*.txt" |
  Select-String -Pattern " ERROR | WARNING |error_code="
```

## Что искать в нормальной операции

Последовательность зависит от replay/retry, но для нового скана ожидаются:

```text
idempotency record created
scanner lock acquired
Starting NAPS2 scan
NAPS2 finished
PDF validated
Destination reserved
temporary copy verified
final PDF published
idempotency succeeded
scanner lock released
```

Точные формулировки могут меняться; идентификаторы и порядок стадий важнее
текста сообщения.

## Минимальный набор доказательств

Для каждого приёмочного или аварийного случая сохраняйте:

1. дату и версию;
2. входной JSON;
3. HTTP-код и ответ;
4. `operation_id`;
5. фрагмент application log;
6. полный путь final PDF;
7. SHA-256 PDF;
8. список файлов до/после;
9. при аппаратной проблеме — фото/видео или описание состояния;
10. Git commit/build manifest.

SHA-256:

```powershell
Get-FileHash `
  "D:\Archive\2026\НКЛ\НКЛ_260721_135000_001.pdf" `
  -Algorithm SHA256
```

## Ротация и хранение

В конфиге задаются месячные файлы, ограничение размера, backup count и retention
months. Ротация приложения не заменяет корпоративное резервное копирование.

Не очищайте логи во время расследования. Перед удалением старого месяца
архивируйте его вместе с manifest и отчётом приёмки.

## Персональные и чувствительные данные

Логи содержат task ID, номера документов, типы, пути и технические сообщения.
Они не должны публиковаться в открытый репозиторий или отправляться третьим лицам
без проверки. Пароль Windows-службы в XML и application log не записывается.
