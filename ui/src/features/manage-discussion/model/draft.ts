/**
 * Ключи черновиков форм обсуждения. Сам черновик общий (`shared/lib`, `draft.ts`); своё у
 * каждой формы — о чём она, и это выражено ключом хранилища сеанса.
 */

/** Ответ на вопрос обсуждения: один вопрос — один черновик. */
export function replyDraftKey(address: string, questionNo: number): string {
  return `tracker.discussion.reply.${address}#${questionNo}`;
}

/** Заметка в обсуждение: одна на обсуждение, пока не отправлена. */
export function noteDraftKey(address: string): string {
  return `tracker.discussion.note.${address}`;
}
