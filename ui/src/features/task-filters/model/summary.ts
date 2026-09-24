import type { TFunction } from 'i18next';
import type { TaskFilters } from './filters';

/**
 * Условие отбора, названное словами: строка состояния отбора показывает такие чипами подряд.
 *
 * `id` нужен разметке ключом и тесту адресом: подпись переписать легко, а по `id`
 * проверка остаётся на месте.
 */
export type ConditionId =
  'status' | 'priority' | 'assignee' | 'text' | 'blocked' | 'questions' | 'remarks' | 'query';

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
  status: { status: [] },
  priority: { priority: [] },
  assignee: { assignee: '' },
  text: { text: '' },
  blocked: { blocked: false },
  questions: { withQuestions: false },
  remarks: { withRemarks: false },
  query: { query: '' },
} satisfies Record<ConditionId, Partial<TaskFilters>>;

/**
 * Что сейчас включено в отборе — списком, целиком.
 *
 * Ничего не сворачивается в счётчик вроде «ещё 2»: строка состояния — единственное, по
 * чему человек судит, полный ли перед ним список задач. Спрятанное условие означает
 * отфильтрованную выдачу, которую принимают за все задачи, и это худшая из ошибок,
 * которую интерфейс списка может допустить.
 *
 * Режим, сортировка и номер страницы сюда не входят: они меняют вид, порядок и место
 * в выдаче, а не её состав. Сортировка и без того стоит на панели отдельным полем, видимым всегда.
 *
 * Проект тоже не входит, и это решение UI-38: он стал местом в интерфейсе, а не
 * условием отбора. Место видно в боковой панели подсветкой и в верхней полосе словами;
 * чип «проект UI» рядом с ними был бы третьим именем того же самого — и снимался бы
 * так, что человек не понимал бы, куда он после этого попал.
 */
export function describeFilters(filters: TaskFilters, t: TFunction<'tasks'>): FilterCondition[] {
  const query = filters.query.trim();

  /*
   * Заполненный запрос отменяет структурный отбор целиком (`filtersToListParams`),
   * и тогда условие ровно одно — сам запрос. Перечислять рядом отменённые условия
   * значило бы показывать человеку то, что на выдачу не влияет: он читал бы пять
   * чипов, из которых работает один. Условия при этом не потеряны — они остались
   * в адресе и вернутся, как только запрос опустеет.
   */
  if (query !== '') return [{ id: 'query', label: t('filters.condition.query', { query }) }];

  const conditions: FilterCondition[] = [];
  const board = filters.view === 'board';

  // На доске статус — это столбец, и параметром он не уезжает (`filtersToListParams`).
  // Назвать его здесь значило бы соврать про выдачу: столбцы показаны все.
  if (!board && filters.status.length > 0) {
    conditions.push({
      id: 'status',
      label: t('filters.condition.status', { values: filters.status.join(', ') }),
    });
  }

  if (filters.priority.length > 0) {
    conditions.push({
      id: 'priority',
      label: t('filters.condition.priority', { values: filters.priority.join(', ') }),
    });
  }

  const assignee = filters.assignee.trim();
  if (assignee !== '') {
    conditions.push({
      id: 'assignee',
      label: t('filters.condition.assignee', { value: assignee }),
    });
  }

  const text = filters.text.trim();
  if (text !== '') {
    conditions.push({ id: 'text', label: t('filters.condition.text', { value: text }) });
  }

  if (filters.blocked) {
    conditions.push({ id: 'blocked', label: t('filters.condition.blocked') });
  }

  if (filters.withQuestions) {
    conditions.push({ id: 'questions', label: t('filters.condition.questions') });
  }

  if (filters.withRemarks) {
    conditions.push({ id: 'remarks', label: t('filters.condition.remarks') });
  }

  return conditions;
}
