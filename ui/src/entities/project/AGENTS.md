# src/entities/project

Проект: карточка из контракта — ключ, название, описание и нынешние атрибуты. Список
проектов для панели приходит в `bootstrap` (`entities/session`), дело проекта читается
средствами записи дела (`entities/entry`).

## Папки

- `api/` — типы карточки и атрибута, ключи запросов и чтение проекта

## Файлы

- `index.ts` — публичный интерфейс среза: `projectQueryOptions`, `projectKeys`, типы `ProjectDetail`, `ProjectAttribute`
