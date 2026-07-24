# 4. Конфигурация

## Где находится рабочий конфиг

```text
C:\ProgramData\Aerotech Docflow\config\config.toml
```

Файл `config.example.toml` в исходном проекте и пакете — только development-
пример. Установленная программа читает рабочий `config.toml` из `ProgramData`.

## Как выбирается файл

Порядок определения пути:

1. аргумент `--config` в командной строке;
2. переменная `DOCFLOW_CONFIG_FILE`;
3. путь по умолчанию в `ProgramData`.

Порядок значений внутри приложения:

```text
переменные окружения уже запущенного процесса
→ значения из config.toml
→ development defaults, если они допустимы
```

Переменная окружения имеет больший приоритет, чем TOML. Поэтому после изменения
конфига полезно выполнить `show-config` и проверить поле
`overridden_by_environment`.

## Правила файла

- кодировка UTF-8 без BOM;
- неизвестные ключи приводят к остановке запуска;
- неподдерживаемый тип значения приводит к ошибке;
- пути Windows в TOML записываются с двойным `\\`;
- production-пути должны быть абсолютными;
- программа должна быть остановлена во время редактирования;
- перед изменением всегда создаётся резервная копия.

## Команды проверки

```powershell
$exe = "C:\Program Files\Aerotech Docflow\app\aerotech-docflow.exe"
$config = "C:\ProgramData\Aerotech Docflow\config\config.toml"

& $exe --config $config show-config
& $exe --config $config preflight
```

`show-config` показывает, что фактически увидит приложение. `preflight`
проверяет production-инварианты, но не запускает сканер и не пишет PDF.

## Раздел `[application]`

| Ключ | Назначение | Production-рекомендация |
|---|---|---|
| `environment` | Режим выполнения | `production` |
| `version` | Идентификатор сборки в логах и `/health` | Не `dev`, например `1.0.0-rc1+b45d4c5f` |
| `host` | Адрес FastAPI | Только `127.0.0.1` или `localhost` |
| `port` | TCP-порт | `8000`, диапазон 1–65535 |

## Раздел `[scanner]`

| Ключ | Что означает |
|---|---|
| `naps2_executable` | Абсолютный путь к `NAPS2.Console.exe` |
| `profile` | Точное имя GUI-профиля NAPS2; пустая строка включает direct mode |
| `output_encoding` | Кодировка вывода NAPS2, обычно `cp866` на русской Windows |
| `incoming_dir` | Локальная временная папка для `PF_*.pdf` и lock |
| `timeout_seconds` | Максимальное время одного запуска NAPS2 |
| `timeout_kill_grace_seconds` | Ожидание после принудительного завершения |
| `verify_process_exit_seconds` | Проверка, что NAPS2 действительно завершился |
| `quarantine_failed_outputs` | Сохранять недоверенный частичный PDF в карантин |
| `failed_scan_dir_name` | Имя карантина внутри incoming |
| `min_pdf_size_bytes` | Минимальный размер результата |
| `min_pdf_pages` | Минимальное число страниц |
| `stable_checks` | Число повторных проверок неизменности размера PDF |
| `stable_interval_seconds` | Интервал между проверками размера PDF |

## Раздел `[scanner.direct]`

Используется только если `scanner.profile = ""`.

| Ключ | Пример |
|---|---|
| `driver` | `escl`, `wia`, `twain` |
| `device_name` | Точное имя устройства NAPS2 |
| `source` | `duplex`, `feeder`, другое значение NAPS2 |
| `dpi` | `300` |
| `page_size` | `a4` |
| `bit_depth` | `gray`, `color`, `blackwhite` |

## Раздел `[archive]`

| Ключ | Назначение |
|---|---|
| `root` | Существующий корень архива |
| `confirmation` | Должен после resolve точно совпасть с `root` |
| `archive_id` | Логическая identity архива, совпадает с marker |
| `allowed_doc_types` | Разрешённые канонические типы документов |
| `min_document_year` | Минимально допустимый год |
| `max_document_year` | Максимально допустимый год |

Marker имеет вид:

```json
{
  "marker": "aerotech-docflow-archive-v1",
  "archive_id": "aerotech-primary-archive"
}
```

## Разделы `[storage]`, `[locking]`, `[logging]`, `[idempotency]`, `[cleanup]`

| Ключ | Назначение |
|---|---|
| `storage.copy_buffer_size` | Размер блока копирования в `.tmp` |
| `storage.keep_temp_on_error` | Оставлять архивный `.tmp` после ошибки; обычно `false` |
| `storage.reservation_stale_seconds` | Возраст `.reserve` до безопасной stale-проверки |
| `locking.stale_seconds` | Возраст lock до проверки безопасного takeover |
| `locking.wait_timeout_seconds` | Сколько ждать занятый scanner lock; `0` — сразу вернуть конфликт |
| `locking.retry_interval_seconds` | Интервал повторной попытки захвата lock |
| `locking.allow_stale_takeover` | Разрешить takeover только доказанно stale lock |
| `logging.enabled` | Обязателен в production |
| `logging.level` | `INFO`, для диагностики временно `DEBUG` |
| `logging.directory` | Каталог application logs вне архива |
| `logging.max_bytes` | Размер одного log-файла до rollover |
| `logging.backup_count` | Число файлов rollover |
| `logging.retention_months` | Срок хранения старых месячных логов |
| `idempotency.enabled` | Обязателен в production |
| `idempotency.directory` | Каталог JSON-состояний вне архива |
| `idempotency.stale_seconds` | Возраст зависшей операции до recovery-решения |
| `cleanup.quarantine_dir_name` | Подкаталог карантина старых входных PDF |
| `cleanup.managed_prefix` | Префикс принадлежащих приложению временных файлов |
| `cleanup.managed_suffix` | Суффикс принадлежащих приложению временных файлов |
| `cleanup.min_age_seconds` | Минимальный возраст до помещения в карантин |
| `cleanup.skip_if_lock_exists` | Не выполнять cleanup при существующем scanner lock |
| `cleanup.stable_checks` | Число проверок неизменности файла перед cleanup |
| `cleanup.stable_interval_seconds` | Интервал между проверками cleanup |

`idempotency.stale_seconds` и `reservation_stale_seconds` должны быть не меньше
суммы scanner timeout, kill grace, exit verify и защитного запаса 60 секунд.

## Как сменить профиль сканера

1. Остановите сервер `Ctrl+C`.
2. Проверьте профиль вручную в NAPS2.
3. Откройте elevated PowerShell.
4. Сделайте резервную копию конфига.
5. Измените только строку `profile`.
6. Выполните `show-config` и `preflight`.
7. Перезапустите сервер и проверьте `/health`.

Список профилей можно увидеть в:

```text
%APPDATA%\NAPS2\profiles.xml
```

Пример безопасного редактирования:

```powershell
$config = "C:\ProgramData\Aerotech Docflow\config\config.toml"
Copy-Item $config "$config.before-profile-change" -Force
notepad $config
```

Измените:

```toml
profile = "Canon G600 series Network"
```

Не изменяйте одновременно `archive.root`, если задача — только сменить сканер.

## Как применяются изменения

Конфиг читается при запуске процесса. После сохранения TOML работающий сервер не
перечитывает его автоматически. Правильная последовательность:

```text
остановить сервер → изменить → show-config → preflight → запустить сервер
```

Если изменение не видно, проверьте `overridden_by_environment`: старая
переменная окружения могла перекрыть TOML.

## Секреты

Текущий `config.toml` не содержит пароль Windows-службы или API-токены. Тем не
менее обычному оператору не следует давать право записи: подмена `archive.root`
или пути NAPS2 меняет поведение системы. Запись — администраторам, чтение —
учётной записи, под которой работает приложение.
