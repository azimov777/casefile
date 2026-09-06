/**
 * Откуда человек пришёл в задачу: адрес списка вместе с отбором.
 *
 * Живёт в состоянии перехода (`Link state`), а не в хранилище браузера. Состояние
 * перехода браузер держит в истории: оно переживает перезагрузку страницы и кнопки
 * «назад» и «вперёд», но не переживает вход по чужой ссылке в новой вкладке. Это
 * ровно та память, которая тут нужна: отбор помнится, пока человек идёт своей
 * дорогой, и честно отсутствует, когда дороги не было.
 */

/** Ключ в состоянии перехода. Один на всё приложение. */
const LIST_SEARCH = 'listSearch';

/** Что положить в `state` ссылки, ведущей из списка в задачу. */
export function listReturnState(search: string): Record<string, string> {
  return { [LIST_SEARCH]: search };
}

/**
 * Адрес возврата в список. `null` означает «человек пришёл не из списка» — тогда
 * звать его надо ко всем задачам и говорить об этом словами, а не притворяться,
 * что отбор где-то есть.
 */
export function listReturnHref(state: unknown): string | null {
  if (typeof state !== 'object' || state === null) return null;
  const search = (state as Record<string, unknown>)[LIST_SEARCH];
  if (typeof search !== 'string' || search === '') return null;
  return search.startsWith('?') ? `/tasks${search}` : `/tasks?${search}`;
}
