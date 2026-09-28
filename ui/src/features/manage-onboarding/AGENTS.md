# src/features/manage-onboarding

Правка состояния знакомства своей учётной записи (`TRK-369`): «Пропустить» и
«Я разобрался» на экране «Начало» (`pages/start`).

## Папки

- `model/` — мутация `PATCH /api/v1/accounts/{id}/onboarding`

## Файлы

- `index.ts` — публичный интерфейс среза: `useUpdateOnboarding`, типы `OnboardingChange` и `OnboardingUpdate`
