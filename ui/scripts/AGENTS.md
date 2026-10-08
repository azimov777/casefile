# scripts

Команда, которой сливают ветку задачи с основной работой в `ui/`. Подъём контура сквозных тестов —
`e2e/global-setup.ts`, образ — `docker/Dockerfile`, установка целиком — `../docker-compose.prod.yml`.

## Файлы

- `merge-task-branch.sh` — слияние ветки задачи в `main`: без коммита, `pnpm check` и `pnpm e2e` на результате,
  коммит только на двойном зелёном со строкой `Merge-verified:`; сверяет `testing/merge-script.test.ts`
