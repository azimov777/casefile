# src/features/manage-onboarding/ui

## Файлы

- `explanation-panel.tsx` — пояснение экрана (`ExplanationPanel`): текст, закрытие этого пояснения, «Скрыть все пояснения» (`TRK-362`); при проходе показано и скрытым, с полосой над ним и без кнопок скрытия (`TRK-364`)
- `restore-hints-action.tsx` — «Показать пояснения снова» на экране «Начало» (`RestoreHintsAction`, `TRK-362`)
- `start-walk-action.tsx` — «Пройти по экранам» на экране «Начало» (`StartWalkAction`): ссылка на первый шаг; нет у человека без учётной записи (`TRK-364`)
- `walk-bar.tsx` — полоса прохода над пояснением (`WalkBar`): «Шаг N из total», «Назад», «Далее», «Закончить» (`TRK-364`)
