import { splitTags, type TaskFilters } from './filters';

/**
 * Условие отбора, названное словами: свёрнутая форма показывает такие подряд.
 *
 * `id` нужен разметке ключом и тесту адресом: подпись переписать легко, а по `id`
 * проверка остаётся на месте.
 */
export type ConditionId =
  | 'queue'
  | 'status'
  | 'priority'
  | 'assignee'
  | 'tags'
  | 'text'
  | 'blocked'
  | 'questions'
  | 'remarks'
  | 'query';

export interface FilterCondition {
  id: ConditionId;
  label: string;
}

/**
 * Чем снимается условие. Перечислено ключами через `satisfies Record<ConditionId, …>`:
 * новое условие в резюме обязано уронить сборку, а не остаться чипом, который нельзя
 * закрыть.
 *
 * Значение по-прежнему живёт в адресе страницы: снятие чипа отправляет эти изменения
 * тем же путём, что и форма, и никакого второго состояния не заводит.
 */
export const CONDITION_RESET = {
  queue: { queue: '' },
  status: { status: [] },
  priority: { priority: [] },
  assignee: { assignee: '' },
  tags: { tags: [] },
  text: { text: '' },
  blocked: { blocked: false },
  questions: { withQuestions: false },
  remarks: { withRemarks: false },
  query: { query: '' },
} satisfies Record<ConditionId, Partial<TaskFilters>>;

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
  const query = filters.query.trim();

  /*
   * Заполненный запрос отменяет структурный отбор целиком (`filtersToListParams`),
   * и тогда условие ровно одно — сам запрос. Перечислять рядом отменённые условия
   * значило бы показывать человеку то, что на выдачу не влияет: он читал бы пять
   * чипов, из которых работает один. Условия при этом не потеряны — они остались
   * в адресе и вернутся, как только запрос опустеет.
   */
  if (query !== '') return [{ id: 'query', label: `запрос: ${query}` }];

  const conditions: FilterCondition[] = [];
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

  if (filters.withRemarks) {
    conditions.push({ id: 'remarks', label: 'есть неразобранные замечания' });
  }

  return conditions;
}
