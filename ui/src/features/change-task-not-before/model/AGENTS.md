# src/features/change-task-not-before/model

## Файлы

- `use-change-not-before.ts` — `PATCH /api/v1/tasks/{key}` с одним полем `not_before` (ISO 8601 со смещением или `null`) без версии задачи; перечитывание `['task', key]` и `['tasks']`
- `local-moment.ts` — стенное время поля `datetime-local` в ISO 8601 со смещением пояса браузера и обратно; пояс берётся у самого момента
- `local-moment.test.ts` — пояс `Europe/Berlin`: летнее и зимнее смещение, разбор ответа в стенное время, негодное значение
