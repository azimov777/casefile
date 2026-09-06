import { splitTags, type TaskFilters } from './filters';

/**
 * Условие отбора, названное словами: свёрнутая форма показывает такие подряд.
 *
 * `id` нужен разметке ключом и тесту адресом: подпись переписать легко, а по `id`
 * проверка остаётся на месте.
 */
export interface FilterCondition {
  id: string;
  label: string;
  /**
   * Условие названо, но на бэкенд не уезжает: так ведут себя структурные условия при
   * заполненном поле запроса (`filtersToListParams`). Показывать их обычной плашкой
   * значило бы соврать про выдачу, а прятать — соврать про то, что человек включил.
   */
  inactive: boolean;
}

/**
 * Что сейчас включено в отборе — списком, целиком.
 *
 * Ничего не сворачивается в счётчик вроде «ещё 2»: свёрнутый вид — единственное, по
 * чему человек судит, полный ли перед ним список задач. Спрятанное условие означает
 * отфильтрованную выдачу, которую принимают за все задачи, и это худшая из ошибок,
 * которую интерфейс списка может допустить.
 *
 * Режим, сортировка и курсор сюда не входят: они меняют вид и порядок, а не состав
 * выдачи. Сортировка и без того стоит на панели отдельным полем, видимым всегда.
 */
export function describeFilters(filters: TaskFilters): FilterCondition[] {
  const conditions: Omit<FilterCondition, 'inactive'>[] = [];
  const board = filters.view === 'board';

  if (filters.queue !== '') {
    conditions.push({ id: 'queue', label: `очередь ${filters.queue}` });
  }

  // На доске статус — это столбец, и параметром он не уезжает (`filtersToListParams`).
  // Назвать его здесь значило бы соврать про выдачу: столбцы показаны все.
  if (!board && filters.status.length > 0) {
    conditions.push({ id: 'status', label: `статус ${filters.status.join(', ')}` });
  }

  if (filters.priority.length > 0) {
    conditions.push({ id: 'priority', label: `приоритет ${filters.priority.join(', ')}` });
  }

  const assignee = filters.assignee.trim();
  if (assignee !== '') {
    conditions.push({ id: 'assignee', label: `исполнитель ${assignee}` });
  }

  const tags = filters.tags.flatMap(splitTags);
  if (tags.length > 0) {
    conditions.push({
      id: 'tags',
      label: `${tags.length === 1 ? 'тег' : 'теги'} ${tags.join(', ')}`,
    });
  }

  const text = filters.text.trim();
  if (text !== '') {
    conditions.push({ id: 'text', label: `текст «${text}»` });
  }

  if (filters.blocked) {
    conditions.push({ id: 'blocked', label: 'только заблокированные' });
  }

  if (filters.withQuestions) {
    conditions.push({ id: 'questions', label: 'есть открытые вопросы' });
  }

  const query = filters.query.trim();
  if (query !== '') {
    // Заполненный запрос отменяет структурный отбор целиком (`filtersToListParams`),
    // и человеку об этом говорится здесь же: иначе он читал бы список условий, из
    // которых действует одно последнее.
    conditions.push({ id: 'query', label: `запрос: ${query}` });
  }

  // Заполненный запрос отменяет структурный отбор целиком. Сказано это не отдельной
  // строкой — она переносила бы список на вторую строку и двигала таблицу вниз, — а
  // на самих условиях, которые сейчас не работают.
  const overridden = query !== '';
  return conditions.map((condition) => ({
    ...condition,
    inactive: overridden && condition.id !== 'query',
  }));
}
