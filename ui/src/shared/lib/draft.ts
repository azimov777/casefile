/**
 * Черновик записи: то, что человек начал писать, но ещё не отправил.
 *
 * Живёт в `sessionStorage`, а не в состоянии компонента: человек уходит с карточки
 * посмотреть соседнюю задачу и возвращается — потерять при этом набранный текст
 * значит отучить его писать длинные ответы и замечания.
 *
 * Рядом с текстом лежит ключ идемпотентности: если отправка оборвалась по сети,
 * повтор обязан идти с тем же ключом, иначе бэкенд заведёт вторую запись. Ключ
 * создаётся в момент первой отправки, а не при наборе.
 *
 * Здесь, в `shared`, а не в срезе формы: черновик нужен каждой форме записи, а
 * второй его экземпляр рядом означал бы два места, где чинить приватный режим
 * браузера и чужой мусор в хранилище.
 */

export interface Draft {
  body: string;
  /** Ключ повтора текущей попытки отправки; пуст, пока не отправляли. */
  idempotencyKey: string;
}

export const EMPTY_DRAFT: Draft = { body: '', idempotencyKey: '' };

export function readDraft(key: string): Draft {
  try {
    const saved = window.sessionStorage.getItem(key);
    if (saved === null) return EMPTY_DRAFT;
    const parsed = JSON.parse(saved) as Partial<Draft>;
    return {
      body: typeof parsed.body === 'string' ? parsed.body : '',
      idempotencyKey: typeof parsed.idempotencyKey === 'string' ? parsed.idempotencyKey : '',
    };
  } catch {
    // Хранилище может быть недоступно (приватный режим) или содержать чужой мусор:
    // черновик — удобство, а не данные, и его потеря не должна ломать форму.
    return EMPTY_DRAFT;
  }
}

export function saveDraft(key: string, draft: Draft): void {
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
/**
 * Заголовок записи человека из её текста: первая непустая строка, обрезанная по длине.
 *
 * Так же поступает трекер со сводкой (`../docs/CONCEPT.md`, 3.4): заголовок
 * выводится из написанного, а не спрашивается отдельно. Обрезка — по границе слова,
 * чтобы в описи не стояло полслова с многоточием посреди корня.
 *
 * Общая у замечания к задаче и заметки в дело проекта: обе — одно поле текста, и
 * второе поле ради строки описи было бы формой, которую человек закроет.
 */
export function titleFromText(body: string, limit = 120): string {
  const first =
    body
      .split('\n')
      .find((line) => line.trim() !== '')
      ?.trim() ?? '';
  if (first.length <= limit) return first;

  const cut = first.slice(0, limit);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > limit / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
