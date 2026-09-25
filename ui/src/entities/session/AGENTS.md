# src/entities/session

Текущий сеанс: кто вошёл и годится ли ещё его токен.

## Папки

- `api/` — `bootstrap.ts`: первый кадр интерфейса и ключи запросов
- `model/` — токен и признак просроченного сеанса как состояние React

## Файлы

- `index.ts` — публичный интерфейс среза: `bootstrapQueryOptions`,
  `bootstrapWithArchivedQueryOptions` (панель с архивными проектами), `fetchBootstrap`,
  `sessionKeys`, `useSessionToken`, `useSessionExpired`, `markSessionExpired`,
  `resetSessionExpiry`, типы `Bootstrap`, `Participant`, `Project`
