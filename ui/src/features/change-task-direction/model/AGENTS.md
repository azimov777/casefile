# src/features/change-task-direction/model

## Файлы

- `use-change-direction.ts` — `PATCH /api/v1/tasks/{key}` с одним полем `direction` (адрес или `null`) без версии задачи; перечитывание `['task', key]` и `['tasks']`
