# 12. Тесты и допуск в production

## Уровни проверки

1. **unit** — без физического сканера и реального архива;
2. **package** — собранный EXE, manifest, CLI и `/health`;
3. **test archive** — storage/recovery на отдельном каталоге;
4. **hardware acceptance** — NAPS2 и реальный сканер;
5. **production acceptance** — выбранная учётная запись, сеть и архив.

Unit-тест не заменяет аппаратную приёмку, а успешный скан в NAPS2 GUI не
заменяет проверку полного API/document flow.

## Unit-тесты

Из исходного проекта:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m tests.unit.run_all_unit_tests
```

Ожидается `ALL UNIT TESTS OK`. Тесты покрывают naming, storage, отказ диска,
идемпотентность, path safety, publish recovery, correlation operation ID,
archive hardening, logging, cleanup и API.

## Проверка пакета

Проверьте manifest:

```powershell
$package = "D:\PROG_PROJECTS\aerotech-docflow\dist\AerotechDocflow"
$entries = Get-Content "$package\build-manifest.json" -Raw -Encoding UTF8 |
    ConvertFrom-Json

foreach ($entry in $entries) {
    $file = Join-Path $package $entry.Path
    if ((Get-FileHash $file -Algorithm SHA256).Hash -ne $entry.SHA256) {
        throw "Hash mismatch: $($entry.Path)"
    }
}
```

Затем `show-config`, `preflight`, ручной запуск и `/health`.

## Обязательные 12 сценариев

| ID | Сценарий | Критический результат |
|---:|---|---|
| 1 | Обычный скан | один валидный PDF, правильное имя/папка/ответ |
| 2 | Пустой ADF | нет успеха и архивного PDF |
| 3 | Замятие/остановка | частичный PDF не принят, следующий запуск возможен |
| 4 | Повтор запроса | нет второго физического скана |
| 5 | Два запроса | нет параллельного NAPS2, второй контролируемо отклонён |
| 6 | Падение после lock | безопасный recovery, чужой lock не удалён |
| 7 | Совпадение имени | старый PDF неизменен, безопасный суффикс |
| 8 | Недоступный архив | source сохранён, успех не возвращён |
| 9 | Нет места | нет частичного final, source сохранён |
| 10 | Падение в трёх точках | нет повреждённого success, продолжение возможно |
| 11 | Защита архива | контрольные суммы чужих PDF совпадают |
| 12 | Серия 20–30 | нет пропусков, дублей и зависших lock |

## Жёсткие критерии запрета

Нельзя выпускать версию, если хотя бы один сценарий показывает:

- удаление или overwrite существующего PDF;
- признание повреждённого PDF успешным;
- вечную блокировку без понятного recovery;
- несколько физических сканов на один повтор;
- `succeeded` до завершения archive publish;
- невозможность связать task и final file;
- критическую ошибку только в консоли без лога/ответа.

## Доказательства

Для каждого сценария:

```text
ID
ожидание
команда или входной JSON
HTTP-ответ
operation_id
лог
созданные файлы
SHA-256 до/после
статус PASSED/FAILED/BLOCKED
Git commit и версия package
```

Не отмечайте `PASSED` только по словам оператора. Нужен воспроизводимый артефакт.

## После изменения конфигурации или обновления

Повторная полная приёмка нужна, если изменились:

- scanner driver/profile/device;
- учётная запись службы;
- archive filesystem или SMB server;
- storage/idempotency/lock код;
- PyInstaller/Python/NAPS2;
- права каталогов;
- схема TOML;
- способ сетевого доступа.

Для косметической документации достаточно unit/package проверки, если код и
deployment state не менялись.
