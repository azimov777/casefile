# src/entities/project

Проект: карточка из контракта — ключ, название, описание, нынешние атрибуты и решения
проекта со статусом (TRK-554). Список
проектов для панели приходит в `bootstrap` (`entities/session`), дело проекта читается
средствами записи дела (`entities/entry`).

## Папки

- `api/` — типы карточки, атрибута и решения проекта, ключи запросов и чтение проекта
- `model/` — предел описания и его длина так, как её меряет бэкенд; адрес решения и отбор задач по нему
- `ui/` — статус решения проекта плашкой

## Файлы

- `index.ts` — публичный интерфейс среза: `projectQueryOptions`, `projectKeys`, `PROJECT_DESCRIPTION_LIMIT`, `descriptionLength`, `descriptionTooLong`, `decisionHref`, `decisionNo`, `decisionTasksQuery`, `DecisionStatusMark`, типы `ProjectDetail`, `ProjectAttribute`, `ProjectDecision`, `DecisionStatus`
