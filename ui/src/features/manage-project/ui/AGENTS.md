# src/features/manage-project/ui

## Файлы

- `create-project.tsx` — «Новый проект» и окно: ключ с образцом в подсказке, название, описание; заведённый открывается
- `edit-project.tsx` — «Изменить» у карточки и окно: название и описание, ключа нет
- `description-field.tsx` — поле описания с остатком до предела и числом лишних знаков сверх него
- `archive-project.tsx` — `ProjectArchiving`: одна кнопка «В архив» (`alertdialog`) или «Восстановить» по `archived_at`, окно с обязательной причиной
- `attribute-dialogs.tsx` — окна атрибута: заведение без причины, изменение и снятие (`alertdialog`) с обязательной причиной
- `reason-field.tsx` — обязательное поле причины: упрёк под полем, связанный `aria-describedby`
- `note-form.tsx` — заметка в дело проекта на `Composer` с подтверждением `Receipt` на месте формы
