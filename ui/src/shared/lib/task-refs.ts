/**
 * Ссылки на задачи и записи в свободном тексте: `TRK-42` и `TRK-42#12`.
 *
 * Такие ссылки агенты пишут руками в телах записей, заголовках и разделах, а бэкенд
 * их не размечает: в контракте это просто текст (`refs` рядом — отдельный список,
 * и он не говорит, где именно в теле ссылка стоит). Значит превращать текст в ссылку —
 * дело интерфейса, и делать это надо в одном месте на всё приложение.
 */

/** Куда указывает ссылка: на задачу или на конкретную запись её дела. */
export interface TaskRef {
  key: string;
  /** Номер записи внутри задачи; `null` — ссылка на задачу целиком. */
  entryNo: number | null;
}

export type TextPart =
  { kind: 'text'; value: string } | { kind: 'ref'; value: string; ref: TaskRef };

/**
 * Ключ задачи в верхнем регистре: `КЛЮЧ-номер`, ключ очереди — латиница и цифры
 * (`../tracker/app/domain/queues.py`, `QUEUE_KEY_PATTERN`). Нижний регистр бэкенд
 * принимает, но канонический вид — верхний, и только его мы считаем ссылкой:
 * иначе в ссылку превращалось бы любое `pull-2` из текста.
 */
const TASK_REF = /\b([A-Z][A-Z0-9]{1,15})-(\d+)(?:#(\d+))?\b/g;

/** Разбирает строку на обычный текст и ссылки, сохраняя порядок и исходное написание. */
export function splitTaskRefs(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;

  for (const match of text.matchAll(TASK_REF)) {
    const at = match.index;
    if (at > last) parts.push({ kind: 'text', value: text.slice(last, at) });

    const [value, queue, number, entry] = match;
    parts.push({
      kind: 'ref',
      value,
      ref: { key: `${queue}-${number}`, entryNo: entry === undefined ? null : Number(entry) },
    });
    last = at + value.length;
  }

  if (last < text.length) parts.push({ kind: 'text', value: text.slice(last) });
  return parts;
}

/**
 * Адрес карточки задачи; ссылка на запись открывает карточку и раскрывает эту запись.
 *
 * Номер записи едет параметром, а не якорем `#12`, хотя в тексте ссылка выглядит именно
 * так: якорь для браузера — цель прокрутки к элементу с таким `id`, а нам нужно раскрыть
 * запись и дочитать её тело. Это состояние страницы, и живёт оно там же, где остальное
 * состояние адреса (`CONVENTIONS.md`, «Состояние»).
 */
export function taskRefHref(ref: TaskRef): string {
  const path = `/tasks/${ref.key}`;
  return ref.entryNo === null ? path : `${path}?entry=${ref.entryNo}`;
}
