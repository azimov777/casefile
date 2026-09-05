# src/features/task-filters

Отбор задач: условия, порядок, режим отображения и курсор как состояние адреса страницы. Своего состояния
у отбора нет — перезагрузка и присланная ссылка обязаны показать одно и то же.

## Папки

- `model/` — отбор в адресе, перевод в параметры API, разбор отказа разбора запроса
- `ui/` — форма отбора и подсказка у поля запроса

## Файлы

- `index.ts` — публичный интерфейс среза: `TaskFiltersForm`, `useTaskFilters`,
  `readFilters`, `writeFilters`, `filtersToListParams`, `hasConditions`, `splitTags`,
  `readQueryProblem`, `caretLine`, `TASK_SORTS`, `EMPTY_FILTERS`, `DEFAULT_SORT`,
  `OPEN_QUESTIONS_CONDITION`, типы `TaskFilters`, `TaskView`, `TaskFiltersControl`, `QueryProblem`
