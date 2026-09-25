# src/entities/project/model

## Файлы

- `description.ts` — предел описания проекта `PROJECT_DESCRIPTION_LIMIT` (копия предела бэкенда ради остатка в поле) `descriptionLength` — кодовые точки обрезанной строки, как меряет бэкенд, и `descriptionTooLong`
- `description.test.ts` — длина меряется после обрезки и кодовыми точками, а не половинками суррогатных пар
