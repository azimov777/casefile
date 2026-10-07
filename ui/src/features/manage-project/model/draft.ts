/**
 * Ключ черновика записи в дело проекта или области. Сам черновик общий
 * (`shared/lib`, `draft.ts`); здесь только его имя: одно дело — один черновик. У проекта
 * имя прежнее — черновик, начатый до TRK-557, не теряется; у области ключом служит
 * её адрес `TRK/promotion`.
 */
export function noteDraftKey(holder: { kind: 'project' | 'area'; key: string }): string {
  return holder.kind === 'area'
    ? `tracker.area-note.${holder.key}`
    : `tracker.project-note.${holder.key}`;
}
