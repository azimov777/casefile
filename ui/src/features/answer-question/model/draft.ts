/**
 * Черновик ответа: то, что человек начал писать, но ещё не отправил.
 *
 * Живёт в `sessionStorage`, а не в состоянии компонента: человек уходит с карточки
 * посмотреть соседнюю задачу и возвращается — потерять при этом набранный текст
 * значит отучить его писать длинные ответы.
 *
 * Рядом с текстом лежит ключ идемпотентности: если отправка оборвалась по сети,
 * повтор обязан идти с тем же ключом, иначе бэкенд заведёт второй ответ. Ключ
 * создаётся в момент первой отправки, а не при наборе.
 */

export interface AnswerDraft {
  body: string;
  refs: string;
  /** Ключ повтора текущей попытки отправки; пуст, пока не отправляли. */
  idempotencyKey: string;
}

export const EMPTY_DRAFT: AnswerDraft = { body: '', refs: '', idempotencyKey: '' };

/** Один вопрос — один черновик: ключ хранилища собран из задачи и номера записи. */
export function draftKey(taskKey: string, questionNo: number): string {
  return `tracker.answer.${taskKey}#${questionNo}`;
}

export function readDraft(key: string): AnswerDraft {
  try {
    const saved = window.sessionStorage.getItem(key);
    if (saved === null) return EMPTY_DRAFT;
    const parsed = JSON.parse(saved) as Partial<AnswerDraft>;
    return {
      body: typeof parsed.body === 'string' ? parsed.body : '',
      refs: typeof parsed.refs === 'string' ? parsed.refs : '',
      idempotencyKey: typeof parsed.idempotencyKey === 'string' ? parsed.idempotencyKey : '',
    };
  } catch {
    // Хранилище может быть недоступно (приватный режим) или содержать чужой мусор:
    // черновик — удобство, а не данные, и его потеря не должна ломать форму.
    return EMPTY_DRAFT;
  }
}

export function saveDraft(key: string, draft: AnswerDraft): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // См. выше: без черновика форма работает, без формы — нет.
  }
}

export function clearDraft(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // См. выше.
  }
}

/** Ссылки `refs` человек пишет строкой; бэкенд ждёт список. */
export function splitRefs(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((ref) => ref.trim())
    .filter((ref) => ref !== '');
}
