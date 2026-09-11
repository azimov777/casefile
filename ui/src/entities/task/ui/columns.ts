/**
 * Столбцы списка задач по порядку. Здесь стоят имена ключей словаря, а не подписи:
 * подпись живёт в `ui.task.columns`, а порядок — свойство таблицы, и он обязан
 * совпадать с порядком ячеек в `task-row.tsx`.
 *
 * Лежат рядом со строкой, а рисует их таблица страницы: отдельным файлом, чтобы
 * горячая перезагрузка не теряла состояние.
 */
export const TASK_COLUMNS = [
  'key',
  'title',
  'status',
  'assignee',
  'priority',
  'features',
  'activity',
] as const;

export type TaskColumn = (typeof TASK_COLUMNS)[number];
