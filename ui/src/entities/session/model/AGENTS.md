# src/entities/session/model

Состояние сеанса, живущее вне React: его меняют перехватчик `401` и соседняя вкладка.

## Файлы

- `expiry.ts` — признак «сохранённый токен больше не годится» с подпиской
- `use-session-expired.ts` — тот же признак как состояние React
- `use-session-token.ts` — токен как состояние React
