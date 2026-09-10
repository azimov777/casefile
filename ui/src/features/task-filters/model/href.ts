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
 * Страница не переносится никогда — кроме случая, когда меняют как раз её: `page`
 * в `changes` перебивает сброс, потому что стоит после него. Номер указывает на место
 * в конкретной выдаче, а любое изменение условий или вида делает выдачу другой:
 * перенесённый номер показал бы страницу, которой в новой выдаче нет. Возврат
 * в раздел по той же причине ведёт к началу списка, а не туда, где человек
 * остановился.
 */
export function tasksHref(
  search: URLSearchParams | string,
  changes: Partial<TaskFilters> = {},
): string {
  const current = readFilters(typeof search === 'string' ? new URLSearchParams(search) : search);
  const params = writeFilters({ ...current, page: 1, ...changes });
  const query = params.toString();
  return query === '' ? '/tasks' : `/tasks?${query}`;
}
