# src/features/change-task-area/model

## Файлы

- `use-change-area.ts` — `PATCH /api/v1/tasks/{key}` с одним полем `area` (адрес или `null`) без версии задачи; перечитывание `['task', key]` и `['tasks']`
