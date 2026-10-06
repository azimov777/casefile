# src/features/manage-project/api

## Файлы

- `projects.ts` — `POST /projects` с ключом повтора, `PATCH /projects/{key}`, `POST /projects/{key}/archive` и `/restore` с причиной; владелец `Holder` — проект или направление: `PUT …/attributes/{name}` (причина — только при изменении), `POST …/attributes/{name}/remove`, `POST …/entries` типа `note` или `decision`; направление (TRK-557): `POST /projects/{key}/directions` с ключом повтора, `PATCH`, `/archive` и `/restore` по адресу
