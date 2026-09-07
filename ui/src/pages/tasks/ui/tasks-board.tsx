import { StatusMark, TASK_STATUSES, TaskCard, type Task, type TaskStatus } from '@/entities/task';
import { Button } from '@/shared/ui';
import styles from './tasks-board.module.css';

interface TasksBoardProps {
  tasks: Task[];
  /** Прочитано не всё: столбцы честно говорят, что за ними может быть ещё. */
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  /**
   * Свёрнутые столбцы. Приходят из адреса, а не из своего `useState`: свёрнутое
   * состояние — это то, что человек увидит по пересланной ссылке, и терять его на
   * переходе в таблицу и обратно незачем.
   */
  collapsed: TaskStatus[];
  onToggle: (status: TaskStatus, open: boolean) => void;
}

/**
 * Доска: те же задачи одной очереди, разложенные по столбцам статусов.
 *
 * Перечень и порядок столбцов берутся из перечисления статуса сгенерированного клиента
 * (`TASK_STATUSES`), а не из своего списка: перечисление уже менялось и может измениться
 * снова — доска обязана пережить это перегенерацией клиента, без правки кода
 * (`../tracker/docs/FRONTEND.md`, «Доска без доски»).
 */
export function TasksBoard({
  tasks,
  hasMore,
  loadingMore,
  onMore,
  collapsed,
  onToggle,
}: TasksBoardProps) {
  const byStatus = new Map<TaskStatus, Task[]>(TASK_STATUSES.map((status) => [status, []]));
  for (const task of tasks) {
    const status = task.status;
    if (status === null || status === undefined) continue;
    byStatus.get(status)?.push(task);
  }

  return (
    <div className={styles.board}>
      <div className={styles.columns}>
        {TASK_STATUSES.map((status) => {
          const column = byStatus.get(status) ?? [];
          const open = !collapsed.includes(status);

          return (
            <section
              key={status}
              className={`${styles.column} ${open ? '' : styles.collapsed}`}
              aria-label={status}
            >
              <h3 className={styles.head}>
                <button
                  type="button"
                  className={styles.toggle}
                  aria-expanded={open}
                  onClick={() => onToggle(status, !open)}
                >
                  {/* Тот же знак, что в списке и на карточке: где бы человек ни
                      увидел `in_progress`, это один и тот же полукруг (решение Д20). */}
                  <StatusMark status={status} className={styles.status} />
                  <span className={styles.count}>
                    {/* «из ?»: сколько задач в статусе всего, знает только дочитанная
                        до конца выдача — врать точным числом до этого нельзя. */}
                    {hasMore ? `${column.length} из ?` : column.length}
                  </span>
                </button>
              </h3>

              {open ? (
                column.length === 0 ? (
                  <p className={styles.empty}>Пусто</p>
                ) : (
                  <ul className={styles.cards}>
                    {column.map((task) => (
                      <li key={task.key}>
                        <TaskCard task={task} />
                      </li>
                    ))}
                  </ul>
                )
              ) : null}
            </section>
          );
        })}
      </div>

      <div className={styles.paging}>
        {hasMore ? (
          <>
            <Button onClick={onMore} disabled={loadingMore}>
              {loadingMore ? 'Читаем…' : 'Ещё'}
            </Button>
            <span className={styles.note}>
              Показаны не все задачи отбора: столбцы дочитываются по кнопке.
            </span>
          </>
        ) : (
          <span className={styles.note}>Показаны все задачи отбора: {tasks.length}.</span>
        )}
      </div>
    </div>
  );
}
