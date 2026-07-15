# Двустороннее сканирование и исключение пустых страниц

## Цель

Нужно, чтобы Epson DS-790WN:

```text
1. сканировал документ с двух сторон;
2. не добавлял пустые страницы в итоговый PDF.
```

---

## Вариант A — рекомендуемый: профиль NAPS2

Лучший вариант для `duplex + exclude blank pages` — настроить профиль NAPS2.

Профиль, например:

```text
EPSON DS-790WN
```

В профиле нужно указать:

```text
Paper Source: Duplex
Bit Depth: Grayscale или Black & White
Page Size: A4
Resolution: 300 dpi или другое рабочее значение
Advanced → Exclude blank pages: включить
```

После этого Python запускает:

```powershell
& "C:\Program Files\NAPS2\NAPS2.Console.exe" `
  -o "D:\incoming\TEST.pdf" `
  -p "EPSON DS-790WN"
```

В коде:

```python
ScannerSettings(
    profile_name="EPSON DS-790WN",
    driver="escl",
    device_name="EPSON DS-790WN",
    source="duplex",
)
```

Если `profile_name` указан, `driver/device/source` не используются для команды. Все настройки берутся из профиля.

Тест:

```powershell
python -m tests.run_document_flow_epson_profile_test
```

---

## Вариант B — прямой CLI без профиля

Для прямого запуска можно указать источник:

```powershell
& "C:\Program Files\NAPS2\NAPS2.Console.exe" `
  -o "D:\incoming\TEST.pdf" `
  --noprofile `
  --driver escl `
  --device "EPSON DS-790WN" `
  --source duplex `
  --dpi 300 `
  --pagesize a4 `
  --bitdepth gray
```

В коде:

```python
ScannerSettings(
    profile_name=None,
    driver="escl",
    device_name="EPSON DS-790WN",
    source="duplex",
    dpi=300,
    page_size="a4",
    bit_depth="gray",
)
```

Тест:

```powershell
python -m tests.run_document_flow_epson_escl_duplex_test
```

Ограничение: исключение пустых страниц лучше настраивать именно в профиле NAPS2. Для прямого CLI мы задаём duplex, но blank-page removal надёжнее держать в профиле.

---

## Практическая рекомендация

Для рабочего сканера используем профиль:

```text
EPSON DS-790WN
```

В профиле включаем:

```text
Paper Source = Duplex
Exclude blank pages = ON
```

А в Python используем:

```python
profile_name="EPSON DS-790WN"
```

Так NAPS2 сам применяет настройки, которые уже проверены в GUI.
