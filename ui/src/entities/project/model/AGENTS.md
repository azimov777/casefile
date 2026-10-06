# src/entities/project/model

## Файлы

- `decisions.ts` — ссылка на решение проекта `TRK#15`: адрес экрана проекта с раскрытой записью (`decisionHref`), номер записи (`decisionNo`), условие языка запросов «задачи по решению» (`decisionTasksQuery`)
- `decisions.test.ts` — адрес решения, строка не той формы, условие отбора задач
- `description.ts` — предел описания проекта `PROJECT_DESCRIPTION_LIMIT` (копия предела бэкенда ради остатка в поле) `descriptionLength` — кодовые точки обрезанной строки, как меряет бэкенд, и `descriptionTooLong`
- `description.test.ts` — длина меряется после обрезки и кодовыми точками, а не половинками суррогатных пар
