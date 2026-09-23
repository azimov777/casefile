# src/features/manage-installation/model

## Файлы

- `use-archive-actions.ts` — `useExportArchive` (выгрузка и сохранение файлом, мимо кэша
  запросов), `useImportArchive` (приём и инвалидация всего кэша после него)
- `save-file.ts` — `saveJsonFile` (диалог браузера «Сохранить как» через `<a download>`),
  `archiveFilename` (имя файла по календарному дню)
- `read-archive-file.ts` — `readArchiveFile`: выбранный файл как тело приёма, без правки
  и без проверки схемы — та же ошибка, что и у бэкенда на нечитаемый файл
