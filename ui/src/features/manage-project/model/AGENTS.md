# src/features/manage-project/model

## Файлы

- `rights.ts` — `useProjectRights`: `manage` у набора `main`, `write` у любого; до первого кадра прав нет
- `use-project-actions.ts` — мутации создания, правки, атрибута, снятия, заметки, архива и восстановления (эти две перечитывают ещё списки задач, вопросов и замечаний); ключ повтора окна `useOnceKey`, перечитывание `['project', key]` и `bootstrap`
- `draft.ts` — ключ черновика заметки: один проект — один черновик
