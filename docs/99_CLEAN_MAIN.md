# 99. Как сделать эту версию main

Ниже безопасный порядок, чтобы не потерять текущую историю.

## 1. Сделать резервную ветку текущего состояния

```powershell
cd C:\path\to\aerotech-docflow

git status

git switch -c backup-before-clean-main

git add -A

git commit -m "Backup before clean main"
```

Если коммитить мусор не нужно, можно вместо этого просто сделать zip/копию папки проекта.

## 2. Создать ветку clean-main

```powershell
git switch main
git switch -c clean-main
```

## 3. Очистить рабочую папку, не удаляя служебные вещи

Из корня проекта:

```powershell
Get-ChildItem -Force | Where-Object {
    $_.Name -notin @(".git", ".env", ".venv", "venv")
} | Remove-Item -Recurse -Force
```

## 4. Скопировать файлы clean-main

Распакуй архив рядом, например в `_clean_main`, затем:

```powershell
Get-ChildItem -Force .\_clean_main\aerotech-docflow-clean-main | Where-Object {
    $_.Name -notin @(".git", ".env", ".venv", "venv")
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination . -Recurse -Force
}
```

## 5. Проверить

```powershell
python -m compileall app tests
python -m tests.unit.run_all_unit_tests
```

## 6. Закоммитить чистую версию

```powershell
git status
git add -A
git commit -m "Clean scanner core baseline"
```

## 7. Сделать её main

Если можно переписать локальный `main`:

```powershell
git switch main
git reset --hard clean-main
```

Если remote `origin/main` тоже нужно заменить этой версией:

```powershell
git push origin main --force-with-lease
```

Перед `--force-with-lease` убедись, что никто другой не работает с `main`.

## Что не входит

Эта версия не содержит HTTP API, веб-сервер, очередь и worker. Эти части нужно добавлять позже отдельным этапом.
