/**
 * Ключ черновика ответа.
 *
 * Сам черновик — общий (`shared/lib`, `draft.ts`): он одинаков у всех форм записи.
 * Своё у ответа ровно одно — на что он отвечает, и это выражено ключом хранилища:
 * один вопрос — один черновик.
 */
export function draftKey(taskKey: string, questionNo: number): string {
  return `tracker.answer.${taskKey}#${questionNo}`;
}
