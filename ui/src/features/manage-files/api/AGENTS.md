# src/features/manage-files/api

## Файлы

- `files.ts` — `uploadFile` (живёт в `entities/file`, здесь пересылается), `replaceFile` (форма собирается `FormData`, а не генератором), `deleteFile`, `deleteFiles` (выбранные, все или ни одного), `deleteMatching` (отбор и подтверждённое число)
