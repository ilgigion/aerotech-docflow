# 2. Файлы и каталоги

## Не путайте три представления программы

### Исходный проект

```text
C:\path\to\aerotech-docflow\
```

Здесь находятся Python-код, тесты, документация и сценарий сборки. Из этого
каталога разрабатывают и собирают новую версию. Рабочая программа не должна
зависеть от того, открыт ли этот проект в VS Code.

### Установочный пакет

```text
C:\path\to\aerotech-docflow\dist\AerotechDocflow\
```

Это переносимый результат PyInstaller. Он содержит EXE, внутренние библиотеки,
WinSW, конфиги-примеры и установочные сценарии. Пакет можно скопировать на другой
компьютер целиком.

### Установленная программа

```text
C:\Program Files\Aerotech Docflow\
```

Это рабочая неизменяемая копия пакета. Её не нужно редактировать для смены
сканера или архива: рабочие настройки находятся в `ProgramData`.

## Рекомендуемая production-структура

```text
C:\Program Files\Aerotech Docflow\
  app\
    aerotech-docflow.exe
    _internal\
  config\
    config.example.toml
    config.production.toml
    config.production.example.toml
  service\
    docflow-service.exe
    docflow-service.xml.template
  docs\
  build-manifest.json
  common_paths.ps1
  cleanup_previous_install.ps1
  install_current_machine.ps1
  start-manually.ps1
  update.ps1
  update-helper.ps1

C:\ProgramData\Aerotech Docflow\
  config\
    config.toml
  logs\
    docflow_YYYY_MM.txt
  service-logs\
  data\
    idempotency\

C:\ProgramData\Aerotech Docflow\incoming\
  .scanner.lock
  PF_*.pdf
  _failed_runtime\

D:\REPLACE_WITH_ARCHIVE_ROOT\
  .aerotech-docflow-archive.json
  2026\
    НКЛ\
    УПД\
```

## Назначение рабочих файлов

| Файл или каталог | Назначение | Можно удалять вручную? |
|---|---|---|
| `config.toml` | Рабочая конфигурация компьютера | Только с резервной копией и при остановленной программе |
| `config.example.toml` | Учебный development-пример | Да, но он нужен для справки и сборки |
| `config.production.example.toml` | Неизменённый обезличенный production-шаблон | Да, но он нужен для сравнения и восстановления настроек |
| `.aerotech-docflow-archive.json` | Подтверждает identity выбранного архива | Нет во время эксплуатации |
| `.scanner.lock` | Запрещает параллельный физический скан | Только после диагностики владельца |
| `PF_*.pdf` | Временный валидный скан или аварийно сохранённый исходник | Нет, пока не проверена идемпотентность |
| `_failed_runtime` | Карантин недоверенных частичных PDF | После ручной проверки и по процедуре хранения |
| `*.reserve` | Резервирование конкретного финального имени | Только автоматическим recovery после stale-проверки |
| `*.tmp` в архиве | Незавершённая или проверяемая копия | Только после диагностики ownership/возраста |
| JSON в `idempotency` | История и состояние запросов | Не удалять для «повторного скана» |
| `docflow_YYYY_MM.txt` | Основной application log | Архивировать по политике хранения |
| `build-manifest.json` | SHA-256 файлов установочного пакета | Нет, нужен для проверки обновлений |

## Что принадлежит архиву

Архивом считается только корень, указанный одновременно в:

- `archive.root`;
- `archive.confirmation`;
- marker-файле с совпадающим `archive_id`.

Логи, конфигурация, incoming и idempotency должны находиться вне архива.
Production preflight отклоняет вложенное размещение служебных каталогов.

## Что резервировать

Минимальный резервный набор администратора:

1. `C:\ProgramData\Aerotech Docflow\config\config.toml`;
2. `C:\ProgramData\Aerotech Docflow\data\idempotency`;
3. application logs;
4. `build-manifest.json` установленной версии;
5. сам архив по корпоративной политике.

Не восстанавливайте idempotency JSON от другой версии или другого архива без
проверки абсолютных путей и `archive_id`.
