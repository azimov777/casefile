# src/features/task-filters

Отбор задач: условия, порядок, режим отображения и курсор как состояние адреса страницы. Своего состояния
у отбора нет — перезагрузка и присланная ссылка обязаны показать одно и то же.

## Папки

- `model/` — отбор в адресе, перевод в параметры API, разбор отказа разбора запроса,
  условия словами и память о развёрнутости формы
- `ui/` — свёрнутая строка отбора и форма под ней

## Файлы

- `index.ts` — публичный интерфейс среза: `TaskFiltersForm`, `useTaskFilters`,
  `readFilters`, `writeFilters`, `filtersToListParams`, `hasConditions`,
  `readQueryProblem`, `caretLine`, `describeFilters`, `queryOverrides`, `TASK_SORTS`,
  `EMPTY_FILTERS`, `DEFAULT_SORT`, `OPEN_QUESTIONS_CONDITION`, типы `TaskFilters`, `TaskView`,
  `TaskFiltersControl`, `QueryProblem`, `FilterCondition`
