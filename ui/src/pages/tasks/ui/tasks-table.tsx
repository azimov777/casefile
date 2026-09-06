import { TASK_COLUMNS, TaskRow, type Task } from '@/entities/task';
import styles from './tasks-table.module.css';

interface TasksTableProps {
  tasks: Task[];
  /** Показанное устарело: идёт запрос или последний был отклонён. */
  stale: boolean;
}

/**
 * Таблица списка. Заголовки берутся у представления строки: порядок ячеек и порядок
 * столбцов обязаны совпадать, и держать их в двух местах значило бы однажды разойтись.
 */
export function TasksTable({ tasks, stale }: TasksTableProps) {
  return (
    <div className={styles.scroller}>
      <table className={styles.table} aria-busy={stale}>
        <caption className={styles.caption}>Задач по отбору: {tasks.length}</caption>
        <thead>
          <tr>
            {TASK_COLUMNS.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <TaskRow key={task.key} task={task} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
