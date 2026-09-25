# src/entities/project

Проект: карточка из контракта — ключ, название, описание и нынешние атрибуты. Список
проектов для панели приходит в `bootstrap` (`entities/session`), дело проекта читается
средствами записи дела (`entities/entry`).

## Папки

- `api/` — типы карточки и атрибута, ключи запросов и чтение проекта
- `model/` — предел описания и его длина так, как её меряет бэкенд

## Файлы

- `index.ts` — публичный интерфейс среза: `projectQueryOptions`, `projectKeys`, `PROJECT_DESCRIPTION_LIMIT`, `descriptionLength`, `descriptionTooLong`, типы `ProjectDetail`, `ProjectAttribute`
