/**
 * Ключ черновика заметки в дело проекта. Сам черновик общий (`shared/lib`, `draft.ts`);
 * здесь только его имя: один проект — один черновик заметки.
 */
export function noteDraftKey(projectKey: string): string {
  return `tracker.project-note.${projectKey}`;
}
