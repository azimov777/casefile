# src/features/manage-onboarding

Состояние знакомства своей учётной записи целиком: `status` — «Пропустить» и
«Я разобрался» на экране «Начало» (`pages/start`, `TRK-369`) — и `hints` — механизм
пояснений экрана: скрытие по одному и все разом, возврат с экрана «Начало» (`TRK-362`).

## Папки

- `model/` — мутация `PATCH /api/v1/accounts/{id}/onboarding`, чтение учётной записи
  из `bootstrap`, перечень ключей пояснений
- `ui/` — компонент пояснения экрана и действие «Показать пояснения снова»

## Файлы

- `index.ts` — публичный интерфейс среза: `useUpdateOnboarding`, типы `OnboardingChange`
  и `OnboardingUpdate`; `HINT_KEYS`, тип `HintKey`; компоненты `ExplanationPanel`
  и `RestoreHintsAction`
