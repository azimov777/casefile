# src/features/manage-project/api

## Файлы

- `projects.ts` — `POST /projects` с ключом повтора, `PATCH /projects/{key}`, `POST /projects/{key}/archive` и `/restore` с причиной; владелец `Holder` — проект или область: `PUT …/attributes/{name}` (причина — только при изменении), `POST …/attributes/{name}/remove`, `POST …/entries` типа `note` или `decision`; область: `POST /projects/{key}/areas` с ключом повтора, `PATCH`, `/archive` и `/restore` по адресу
