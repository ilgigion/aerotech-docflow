# Диагностика и восстановление после прерывания сканирования

## Цель

Если оператор прервал процесс во время сканирования, система должна не оставлять сервер и сканер в зависшем состоянии.

Текущая защита состоит из нескольких уровней:

1. `document_flow.py` держит `.scanner.lock` через context manager.
2. `scanner.py` запускает NAPS2 как дочерний процесс.
3. При `timeout` `scanner.py` убивает именно запущенный NAPS2-процесс.
4. При `Ctrl+C` / `KeyboardInterrupt` `scanner.py` тоже убивает NAPS2.
5. После исключения `document_flow.py` освобождает `.scanner.lock`.
6. `storage.py` использует `.reserve` и `.tmp`, чтобы не оставлять неполные финальные PDF.

## Что изменено в scanner.py

### 1. Нормальная кодировка stdout/stderr NAPS2

На русской Windows NAPS2 часто пишет текст в `cp866`. Если читать через `cp1251`, получается:

```text
‚ Ї®¤ взЁЄҐ ­Ґв «Ёбв®ў.
```

Теперь по умолчанию на Windows используется:

```text
cp866
```

И сообщение читается как:

```text
В податчике нет листов.
```

Переопределить можно через env:

```powershell
$env:NAPS2_OUTPUT_ENCODING = "cp866"
```

### 2. Обработка KeyboardInterrupt

Если во время сканирования нажать `Ctrl+C`, `scanner.py` теперь:

```text
1. ловит KeyboardInterrupt;
2. вызывает taskkill по PID запущенного NAPS2;
3. возвращает ScannerInterruptedError;
4. lock освобождается в document_flow.py.
```

Это уменьшает риск ситуации, когда Python уже остановлен, а NAPS2 продолжает держать сканер.

### 3. Timeout убивает конкретный NAPS2 PID

При зависании больше `timeout_seconds` выполняется:

```powershell
taskkill /PID <pid> /T /F
```

Важно: штатный код убивает не все NAPS2-процессы, а только тот процесс, который сам запустил.

## Что всё равно невозможно гарантировать на 100%

Если зависание произошло глубоко внутри драйвера, сетевого стека или самого сканера, программное завершение NAPS2 может быть недостаточным.

В редких случаях всё равно потребуется:

```text
1. нажать Cancel/Stop на сканере;
2. выключить/включить сканер;
3. перезапустить службу Windows Image Acquisition;
4. перезагрузить ПК.
```

Но после этой доработки обычный `Ctrl+C` и обычный timeout уже не должны оставлять NAPS2-процесс без контроля.

## Диагностика состояния

Новый файл:

```text
app/scanner_recovery.py
```

Скрипт:

```text
tests/run_scanner_recovery_diagnostics.py
```

Запуск диагностики:

```powershell
python -m tests.run_scanner_recovery_diagnostics
```

Показывает:

```text
.scanner.lock
NAPS2-процессы
PF_*.pdf в incoming
*.tmp в архиве
*.reserve в архиве
```

## Ручное восстановление

Только убить NAPS2-процессы:

```powershell
python -m tests.run_scanner_recovery_diagnostics --kill-naps2
```

Убить NAPS2 и удалить lock:

```powershell
python -m tests.run_scanner_recovery_diagnostics --kill-naps2 --remove-lock
```

Убить NAPS2, удалить lock и убрать `.tmp/.reserve` из архива:

```powershell
python -m tests.run_scanner_recovery_diagnostics --kill-naps2 --remove-lock --cleanup-artifacts
```

Важно: `--remove-lock` и `--cleanup-artifacts` использовать только когда точно нет активного сканирования.

## Нормальная проверка после сбоя

1. Проверить диагностику:

```powershell
python -m tests.run_scanner_recovery_diagnostics
```

2. Убедиться, что:

```text
NAPS2 processes: none
lock_exists: False
Archive *.tmp files: none
Archive *.reserve files: none
```

3. Проверить ручной запуск NAPS2:

```powershell
& "C:\Program Files\NAPS2\NAPS2.Console.exe" `
  -o "D:\incoming\RECOVERY_TEST_001.pdf" `
  --noprofile `
  --driver escl `
  --device "EPSON DS-790WN" `
  --source duplex `
  --dpi 300 `
  --pagesize a4 `
  --bitdepth gray
```

Если файл уже существует, использовать новое имя или добавить `--force`.

## Рекомендация для текущего проекта

Для рабочего Epson сейчас использовать:

```text
--driver escl
--device "EPSON DS-790WN"
--source duplex
--dpi 300
--pagesize a4
--bitdepth gray
```

Timeout держать не меньше:

```text
300 секунд
```

Пустые страницы пока не удаляем программно. Это остаётся системной настройкой сканера/NAPS2.
