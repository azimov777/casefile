# src/features/manage-installation/model

## Файлы

- `use-archive-actions.ts` — `useExportArchive` (выгрузка и сохранение файлом, мимо кэша
  запросов), `useImportArchive` (приём и инвалидация всего кэша после него)
- `save-file.ts` — `saveJsonFile` (диалог браузера «Сохранить как» через `<a download>`),
  `archiveFilename` (имя файла по календарному дню)
- `save-file.test.ts` — тело сохранённого файла, имя и адрес ссылки, отложенное
  освобождение адреса; ведущие нули в дате
- `read-archive-file.ts` — `readArchiveFile`: выбранный файл как тело приёма, без правки
  и без проверки схемы — та же ошибка, что и у бэкенда на нечитаемый файл
- `read-archive-file.test.ts` — файл разбирается как есть; файл не JSON — код
  `archive_format_unsupported`
