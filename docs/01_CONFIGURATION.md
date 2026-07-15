# 01. Конфигурация

Все рабочие пути и параметры должны задаваться через переменные окружения или настройки запуска. Пример находится в `.env.example`.

## Рекомендуемые параметры для текущего рабочего сканера

```powershell
$env:NAPS2_EXECUTABLE = "C:\Program Files\NAPS2\NAPS2.Console.exe"
$env:NAPS2_PROFILE = "EPSON DS-790WN"
$env:SCANNER_INCOMING_DIR = "D:\incoming"
$env:ARCHIVE_ROOT = "D:\archive_test"
$env:SCANNER_TIMEOUT_SECONDS = "180"
```

Если используется профиль NAPS2, то `SCANNER_DRIVER`, `SCANNER_DEVICE_NAME`, `SCANNER_SOURCE`, `SCANNER_DPI`, `SCANNER_PAGE_SIZE`, `SCANNER_BIT_DEPTH` не участвуют в команде NAPS2.

## Профиль NAPS2

В профиле `EPSON DS-790WN` рекомендуется:

```text
Драйвер: ESCL
Источник бумаги: Двустороннее сканирование
Размер страницы: A4
Разрешение: 300 dpi
Исключить пустые страницы: включено, если нужно
Автосохранение: выключено
```

Автосохранение NAPS2 не нужно, потому что путь PDF задаёт backend через `-o`.

## Архив

По умолчанию:

```text
D:\archive_test\2026\УПД\УПД_260710_101025_2455B.pdf
```

Для production позже заменить `ARCHIVE_ROOT` на боевой путь.
