# src/entities/direction/api

## Файлы

- `direction.ts` — типы карточки направления с атрибутами (`DirectionDetailRead`), строки списка (`DirectionRead`) и направления в карточке задачи (`TaskDirectionRead`); ключи: карточка под `['direction', адрес]`, список под префиксом проекта; `directionQueryOptions` — `GET /api/v1/projects/{project_key}/directions/{direction_key}`, `directionsQueryOptions` — список направлений проекта с архивными или без
