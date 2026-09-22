# src/features/change-password

Смена своего пароля (`TRK-113`): прежний, новый и новый ещё раз. Бэкенд гасит прочие
сеансы человека и оставляет живым тот, из которого пароль сменили. Чужой пароль так не
меняют — это сброс администратором (`features/manage-people`).

## Папки

- `model/` — мутация `PUT /api/v1/accounts/{id}/password`
- `ui/` — форма смены пароля

## Файлы

- `index.ts` — публичный интерфейс среза: `ChangePasswordForm`, `useChangePassword`, тип `PasswordChange`
