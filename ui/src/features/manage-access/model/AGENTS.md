# src/features/manage-access/model

## Файлы

- `use-access-actions.ts` — `useRegisterAgent`, `useIssueToken` (мимо кэша запросов), `useRevokeToken`, `useSetProjectAccess` (кладёт ответ в кэш чтения); инвалидация списка доступов и реестра участников
- `problem.ts` — `denialReason` — знакомая экрану причина `403 permission_denied` из `details.reason`
