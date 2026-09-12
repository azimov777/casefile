# src/pages/connect/model

## Файлы

- `skill-command.ts` — команда установки скила дисциплины файлом: `SKILL_COMMAND`
  объектом `{ bashZsh, powerShell }`, тексты не собираются одной заготовкой под обе
  оболочки — разбор расхождений (`&&`, `mkdir -p`, запись файла) в комментарии (`UI-118`)
- `skill-command.test.ts` — обе строки читают тот же файл; PowerShell без `&&`,
  без `mkdir -p`, без `>`/`Set-Content -Encoding utf8`, с явным `-Force` и с
  `[Console]::OutputEncoding` до вызова `docker`
