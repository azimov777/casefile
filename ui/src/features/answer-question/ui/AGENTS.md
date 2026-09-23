# src/features/answer-question/ui

## Файлы

- `answer-form.tsx` — форма ответа поверх общего `Composer`: куда отправлять и чем упрекать за пустоту; `onCancel` обязателен — сворачивание формы решает вызывающий (`QuestionAnswer` на карточке, `QuestionRow` во входящей, `UI-156`)
- `answer-receipt.tsx` — подтверждение ответа поверх общего `Receipt`: слова и адрес вопроса
