# src/features/manage-installation

Перенос установки: скачать архив всех её данных и принять его в свежую установку
(`docs/moving.md`, TRK-100, UI-135). Обе операции — только администратору
(`bootstrap.account.is_admin`), и решает это флаг из первого кадра, а не отказ `403`.

Архив несёт хеши паролей и токенов всей установки, поэтому обе операции идут
**мимо кэша запросов** — тем же образцом, что выпуск токена в `features/manage-access`:
состояние действия держит сам хук, а не `QueryClient` или `MutationCache`.

## Папки

- `api/` — выгрузка и приём архива
- `model/` — состояние двух действий, сохранение файла в браузере, разбор выбранного файла
- `ui/` — подтверждение приёма и панель его итога

## Файлы

- `index.ts` — публичный интерфейс среза: `useExportArchive`, `useImportArchive`,
  `readArchiveFile`, `exportInstallationArchive`, `ImportDialog`, `ImportResult`, типы
  `InstallationArchive`, `InstallationArchiveUpload`, `ArchiveImportRead`
