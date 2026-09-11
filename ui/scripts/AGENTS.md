# scripts

Команды, которыми ветки задач сливают руками. Всё, что нужно прогонам и сборке, живёт
не здесь: контур сквозных тестов поднимает `e2e/global-setup.ts`, образ собирает
`docker/Dockerfile`, установку целиком поднимает `../docker-compose.prod.yml`.

## Файлы

- `merge-task-branch.sh` — слияние ветки задачи в `main`: без коммита, `pnpm check` затем
  `pnpm e2e` на результате, коммит только на двойном зелёном со строкой `Merge-verified:`
  (`docs/CONVENTIONS.md`, «Слияние ветки задачи в main»); проверяет согласие с прозой
  `testing/merge-script.test.ts`
