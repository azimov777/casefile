# src/entities/file/api

## Файлы

- `upload.ts` — тело формы `multipart` (`fileForm`) и загрузка файла в проект (`uploadFile`): нужна вкладке «Файлы» и вложениям к записям
- `files.ts` — тип карточки файла, отбор списка и его умолчание, ключи запросов, `filesQueryOptions` (страницы по курсору), `fileQueryOptions`, `fetchFileBlob` (байты через общий клиент: чтение считается открытием файла)
