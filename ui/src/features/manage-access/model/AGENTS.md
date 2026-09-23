# src/features/manage-access/model

## Файлы

- `once-key.ts` — `useOnceKey`: ключ повтора, привязанный к отпечатку запроса; в памяти, а не в `sessionStorage` — повтор тем же ключом отдаёт тот же секрет
- `use-access-actions.ts` — `useRegisterAgent`, `useIssueToken` (мимо кэша запросов), `useRevokeToken`; инвалидация списка доступов и реестра участников
- `problem.ts` — поля, на которые жалуется отказ: `details.fields` домена и `details.errors` схемы запроса; `denialReason` — знакомая экрану причина `403 permission_denied` из `details.reason`
