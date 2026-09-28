# src/features/manage-onboarding/model

## Файлы

- `hint-keys.ts` — перечень ключей пояснений одним местом (`HINT_KEYS`, тип `HintKey`); ключи: `questions` (Входящая, `TRK-362`), `tasks`, `board`, `task`, `case`, `project`, `connect`, `access` (остальные экраны, `TRK-363`)
- `use-onboarding-hints.ts` — учётная запись вошедшего из `bootstrap` для чтения `onboarding.hints`; `null` до ответа и без учётной записи
- `use-update-onboarding.ts` — мутация: `status` в `pending`/`completed`/`skipped` и/или подсказки скрытия, инвалидация `bootstrap` после успеха
- `use-walk.ts` — план прохода (`useWalkPlan`: проект `START` или первый активный, первая задача проекта, готовность) и состояние по адресу (`useWalk`: номер шага из параметра `walk`), `TRK-364`
- `walk-steps.ts` — порядок шагов прохода одним местом (`WALK_STEP_DEFS`), имя параметра `walk`, сборка шагов под установку (`buildWalkSteps`), адрес шага (`walkHref`), разбор номера (`parseWalk`), `TRK-364`
