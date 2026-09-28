# src/features/manage-onboarding/model

## Файлы

- `hint-keys.ts` — перечень ключей пояснений одним местом (`HINT_KEYS`, тип `HintKey`); первый и пока единственный ключ — `questions` (Входящая, `TRK-362`)
- `use-onboarding-hints.ts` — учётная запись вошедшего из `bootstrap` для чтения `onboarding.hints`; `null` до ответа и без учётной записи
- `use-update-onboarding.ts` — мутация: `status` в `pending`/`completed`/`skipped` и/или подсказки скрытия, инвалидация `bootstrap` после успеха
