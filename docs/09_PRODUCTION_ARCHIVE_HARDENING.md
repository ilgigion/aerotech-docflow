# Production archive hardening RC1

Техническое усиление выполнено после аудита commit `31c14f04`. Эта версия
защищает файловый и scanner-контур, но не объявляется полностью допущенной в
production до настройки OpenSSH/авторизации и физической приёмки точного commit.

## Реализовано

1. Production fail-closed configuration:
   - обязательные пути, version, allowlist типов и диапазон лет;
   - запрет `archive_test`;
   - существующий корень архива и точное подтверждение пути;
   - проверка read-only marker и `archive_id` реального архива;
   - обязательные idempotency, logging и безопасные stale timeout.
2. Lossy identity (`/`, `\\`, whitespace replacement и другие изменения) больше
   не принимается HTTP API молча; fingerprint различает исходные значения.
3. `succeeded` с отсутствующим final PDF останавливается с
   `manual_recovery_required`, без второго физического скана.
4. Idempotency stale учитывает hostname и живой PID; takeover обновляет owner.
5. Scanner lock и idempotency marker публикуются только после полной записи и
   `fsync`; malformed lock работает fail-closed.
6. Destination reservation публикуется полностью, stale учитывает живой PID,
   release проверяет operation/PID/hostname/path.
7. Архивная копия проверяется по размеру, SHA-256 и строгому `pypdf` до
   no-clobber публикации.
8. Destination проверяется после resolve и не может выйти из `ARCHIVE_ROOT`
   через junction/symlink промежуточного каталога.
9. Recovery не удаляет произвольные `*.tmp`/`*.reserve`; managed PDF temp без
   owner удаляется только явным административным override.
10. Runtime-логи поддерживают ограничение размера, backup и retention;
    production требует явных положительных значений.
11. Один `operation_id` проходит от HTTP до document flow и внутренних логов.

## Автоматические доказательства

- `python -m compileall -q app tests` — passed;
- `python -m tests.unit.run_all_unit_tests` — passed;
- `python -m pip check` — no broken requirements;
- acceptance storage scenarios 7/8/9/11 — passed в отдельном тестовом архиве;
- controlled crash stages `after_temp_copy`, `during_copy`, `after_publish` —
  passed: по одному PDF, incoming пуст, lock/tmp/reserve отсутствуют.

Черновые доказательства до фиксации commit:
`acceptance_runs/20260716_171656_31c14f04`.

## Остаётся до полного production-допуска

- OpenSSH policy, ключи, `PermitOpen`, Windows firewall и API-аутентификация;
- HTTP body/rate/concurrency limits;
- статус операции при потере SSH-соединения;
- lockfile с hashes/SBOM и автоматический dependency audit;
- Windows ACL для архива/incoming/log/idempotency;
- проверка hard-link на фактическом боевом томе;
- новый чистый acceptance run точного commit и физические сценарии 1–6, 10, 12.

## Перед подключением реального архива

1. Создать отдельные incoming/log/idempotency каталоги и назначить ACL.
2. Создать read-only `.aerotech-docflow-archive.json` по инструкции
   `docs/01_CONFIGURATION.md`.
3. Заполнить production environment.
4. Выполнить `python -m app.preflight`.
5. Провести приёмку на отдельной тестовой папке точного release commit.
6. Только после допуска заменить тестовый archive root на подтверждённый боевой.
