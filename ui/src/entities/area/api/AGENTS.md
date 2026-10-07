# src/entities/area/api

## Файлы

- `area.ts` — типы карточки области с атрибутами (`AreaDetailRead`), строки списка (`AreaRead`) и области в карточке задачи (`TaskAreaRead`); ключи: карточка под `['area', адрес]`, список под префиксом проекта; `areaQueryOptions` — `GET /api/v1/projects/{project_key}/areas/{area_key}`, `areasQueryOptions` — список областей проекта с архивными или без
