/**
 * Ключ черновика записи в дело проекта или направления. Сам черновик общий
 * (`shared/lib`, `draft.ts`); здесь только его имя: одно дело — один черновик. У проекта
 * имя прежнее — черновик, начатый до TRK-557, не теряется; у направления ключом служит
 * его адрес `TRK/promotion`.
 */
export function noteDraftKey(holder: { kind: 'project' | 'direction'; key: string }): string {
  return holder.kind === 'direction'
    ? `tracker.direction-note.${holder.key}`
    : `tracker.project-note.${holder.key}`;
}
