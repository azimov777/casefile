import { readFilters, writeFilters, type TaskFilters } from './filters';

/**
 * Адрес списка задач с изменёнными условиями — **одно правило на все точки навигации**.
 *
 * Раньше их было два: локальный переключатель менял `view` через отбор в адресе,
 * а шапка собирала `/tasks?view=board` с нуля и по дороге теряла очередь, статусы
 * и порядок. Два способа сказать одно и то же расходятся при первом же новом
 * условии — и разошлись: доска открывалась пустой от отбора, но человек об этом
 * не предупреждался.
 *
 * Курсор не переносится никогда. Он указывает на страницу конкретной выдачи, а любое
 * изменение условий или вида делает выдачу другой: перенесённый курсор показал бы
 * страницу, которой в новой выдаче нет. Возврат в раздел по той же причине ведёт
 * к началу списка, а не на ту страницу, где человек остановился.
 */
export function tasksHref(
  search: URLSearchParams | string,
  changes: Partial<TaskFilters> = {},
): string {
  const current = readFilters(typeof search === 'string' ? new URLSearchParams(search) : search);
  const params = writeFilters({ ...current, ...changes, cursor: '' });
  const query = params.toString();
  return query === '' ? '/tasks' : `/tasks?${query}`;
}
