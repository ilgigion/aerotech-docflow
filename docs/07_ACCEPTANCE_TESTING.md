# 07. Приёмочные испытания перед production

Приёмка выполняется только на отдельном тестовом архиве. Runner не использует
значение `ARCHIVE_ROOT` текущего терминала и создаёт для каждого прогона новый
каталог внутри `acceptance_runs`.

## Начало нового прогона

```powershell
python -m tests.acceptance.run_acceptance_tests start
```

Команда не обращается к NAPS2 и физическому сканеру. Она:

- создаёт уникальный каталог `acceptance_runs\ДАТА_ВРЕМЯ_COMMIT`;
- записывает commit, ветку, состояние рабочей копии и `source_diff.patch`;
- создаёт отдельные `incoming`, `archive`, `idempotency` и каталоги логов;
- создаёт защищённые PDF и сохраняет их SHA-256;
- запускает `compileall`, полный unit suite и автоматические проверки сценариев
  совпадения имени, недоступного архива и искусственного `ENOSPC`;
- формирует `REPORT.md`, `report.json` и план ручных испытаний.

До проведения ручных сценариев итоговый вердикт намеренно будет
**«НЕ ДОПУСКАТЬ»**.

## Где хранятся логи и доказательства

Внутри каталога каждого прогона сохраняются:

```text
acceptance.log                         полный журнал runner-а и storage
automated/compileall.log               команда и результат compileall
automated/unit_tests.log               полный вывод unit suite
automated/storage_probes.json          факты по сценариям 7, 8 и 9
test_environment/server_logs/          отдельные месячные логи document_flow/API
scenario_XX/manual_attempts/...         входной JSON, HTTP-ответ, файлы до/после
scenario_XX/manual_evidence/            скриншоты, видео и другие вложения
protected_before.sha256                 хэши защищённых файлов до испытаний
protected_after.sha256                  хэши защищённых файлов после испытаний
manifest.json                           версия кода и тестовое окружение
REPORT.md                               итоговая таблица по 12 сценариям
```

`acceptance_runs/` исключён из Git, но файлы остаются на диске. После завершения
приёмки каталог прогона следует целиком скопировать в место долговременного
хранения. Не удаляйте его до решения о допуске.

## Запуск тестового API

В каталоге прогона runner создаёт `start_test_api.ps1`. Остановите ранее
запущенный API и выполните:

```powershell
cd acceptance_runs\<RUN_ID>
.\start_test_api.ps1
```

Скрипт принудительно направляет scanner, archive, idempotency и server logs в
каталог этого прогона. Production-архив не используется.

## Запрос с автоматической фиксацией доказательств

В другом PowerShell:

```powershell
python -m tests.acceptance.run_acceptance_tests request `
  --run "D:\PROG_PROJECTS\aerotech-docflow\acceptance_runs\<RUN_ID>" `
  --scenario 1 `
  --task-id "ACC-001" `
  --doc-type "НКЛ" `
  --document-number "001" `
  --confirm-real-scan
```

Runner сохраняет тело запроса, ответ, HTTP status и снимки тестового архива до и
после. Флаг `--confirm-real-scan` обязателен, чтобы физический скан нельзя было
запустить случайно.

Для localhost runner использует HTTP-клиент с `trust_env=False`: переменные
`HTTP_PROXY`/`HTTPS_PROXY`, установленные VPN, не могут перенаправить запрос к
`127.0.0.1` через внешний прокси. Для сетевого сканера VPN всё равно следует
отключить, если он меняет доступность устройства.

Для сценария повторного запроса дважды выполните команду с одинаковыми полями и
одинаковым `--idempotency-key`. Для конкурентного сценария запустите две команды
почти одновременно из разных терминалов с разными `task_id`.

## Фиксация ручного результата

```powershell
python -m tests.acceptance.run_acceptance_tests record `
  --run "D:\PROG_PROJECTS\aerotech-docflow\acceptance_runs\<RUN_ID>" `
  --scenario 1 `
  --status PASSED `
  --notes "Создан один PDF, имя и каталог проверены" `
  --evidence "C:\evidence\scenario-01.png"
```

Допустимые статусы: `PASSED`, `FAILED`, `BLOCKED`. Для `PASSED` и `FAILED`
runner требует сохранённый HTTP attempt либо файл доказательства. Одни слова без
доказательства не принимаются.

Ручного вмешательства требуют сценарии 1–6, 10 и 12. Сценарии 7–9 и 11
проверяются автоматически на отдельной файловой структуре. При желании сценарий
8 можно дополнительно повторить с отключением тестового диска и приложить
доказательства.

Для сценария 10 используется воспроизводимый offline crash-runner; NAPS2 и
физический сканер он не запускает:

```powershell
python -m tests.acceptance.run_scenario10 --run "D:\...\acceptance_runs\<RUN_ID>"
```

Для сценария 12 новый run автоматически содержит интерактивный ASCII-скрипт,
совместимый с Windows PowerShell 5.1. Пустой Enter не запускает скан — оператор
должен явно ввести `SCAN`:

```powershell
& "D:\...\acceptance_runs\<RUN_ID>\scenario_12\run_20_documents.ps1"
python -m tests.acceptance.check_scenario12 --run "D:\...\acceptance_runs\<RUN_ID>"
```

## Финальная проверка

После всех сценариев остановите API и выполните:

```powershell
python -m tests.acceptance.run_acceptance_tests finalize `
  --run "D:\PROG_PROJECTS\aerotech-docflow\acceptance_runs\<RUN_ID>"
```

Runner повторно вычислит SHA-256 защищённых файлов и обновит таблицу. Допуск
невозможен, если:

- хотя бы один сценарий не имеет статуса `PASSED`;
- изменился любой защищённый PDF;
- автоматическая проверка завершилась ошибкой;
- прогон начат на грязной рабочей копии.

Для окончательной приёмки сначала зафиксируйте тестируемую версию commit-ом,
затем начните новый прогон. Commit из `manifest.json` должен совпадать с версией,
которую планируется развернуть.
