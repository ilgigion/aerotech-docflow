# 2. Файлы и каталоги

## Исходный проект

```text
C:\path\to\aerotech-docflow\
```

Содержит Python-код, тесты, документацию, внутренние установочные инструменты и
сценарии сборки. Установленная служба не зависит от этой папки.

## ZIP конкретной версии

```text
dist\aerotech-docflow-v1.3.0.zip
```

Содержит только заменяемую программную часть:

```text
app\
  aerotech-docflow.exe
  _internal\
service\
  docflow-service.exe
  docflow-service.xml.template
version.json
build-manifest.json
```

В ZIP нет updater, конфигов, рабочих данных и установочных PowerShell-скриптов.

## Установленное приложение

```text
C:\Program Files\Aerotech Docflow\
  app\
  service\
  version.json
  build-manifest.json
```

Эта папка целиком заменяется при обновлении.

## Постоянный updater

```text
C:\Program Files\Aerotech Updater\
  AerotechUpdater.exe
```

Он устанавливается отдельным `AerotechUpdaterSetup.exe`, не находится внутри
Docflow и не заменяется вместе с ним.

## Постоянные рабочие данные

```text
C:\ProgramData\Aerotech Docflow\
  config\
    config.toml
  incoming\
    .scanner.lock
    PF_*.pdf
    _failed_runtime\
  logs\
    docflow_YYYY_MM.txt
    updater.log
  service-logs\
  state\
  data\
    idempotency\
```

Updater может дописывать только `logs\updater.log`. Остальные постоянные данные
он не изменяет.

## Временные данные обновления

```text
C:\Temp\Aerotech Docflow\
  aerotech-docflow-v1.3.0.zip
  unpacked\
  rollback\
```

После успешного обновления ZIP, `unpacked` и `rollback` удаляются. При ошибке ZIP
остаётся для диагностики.

## Архив документов

```text
D:\REPLACE_WITH_ARCHIVE_ROOT\
  .aerotech-docflow-archive.json
  2026\
    НКЛ\
    УПД\
```

Updater не обращается к PDF и не перемещает архив. `preflight` только проверяет
уже настроенный архив по рабочему `config.toml`.

## Назначение критических файлов

| Файл | Назначение | Правило |
|---|---|---|
| `config.toml` | Рабочая конфигурация компьютера | Updater только читает |
| `version.json` | Версия программы и схема конфига | Заменяется вместе с приложением |
| `build-manifest.json` | Размеры и SHA-256 релиза | Нужен для проверки ZIP |
| `.scanner.lock` | Запрет параллельного скана | Updater не удаляет |
| `updater.log` | История обновлений | Единственная запись updater в ProgramData |
| `.aerotech-docflow-archive.json` | Identity архива | Updater не изменяет |
| `*.reserve`, `*.tmp` | Защита публикации PDF | Не удалять вручную без диагностики |

## Что резервировать

1. `C:\ProgramData\Aerotech Docflow\config\config.toml`;
2. idempotency/state;
3. application, service и updater logs;
4. `version.json` и `build-manifest.json` установленной версии;
5. архив по корпоративной политике.
