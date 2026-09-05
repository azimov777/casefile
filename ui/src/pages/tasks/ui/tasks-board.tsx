import { useState } from 'react';
import { TASK_STATUSES, TaskCard, type Task, type TaskStatus } from '@/entities/task';
import { Button } from '@/shared/ui';
import styles from './tasks-board.module.css';

interface TasksBoardProps {
  tasks: Task[];
  /** Прочитано не всё: столбцы честно говорят, что за ними может быть ещё. */
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
}

/**
 * Столбцы, свёрнутые по умолчанию: закрытая и отменённая задача интересны реже
 * остальных, а места занимают столько же.
 *
 * Словарь по значению статуса, а не список: перечень и порядок столбцов приходят
 * из перечисления контракта, и здесь сказано только про особенных, каждый по имени.
 * Снятый статус исчезнет из доски сам; добавленный появится развёрнутым.
 */
const COLLAPSED_BY_DEFAULT: Partial<Record<TaskStatus, true>> = {
  done: true,
  cancelled: true,
};

/**
 * Доска: те же задачи одной очереди, разложенные по столбцам статусов.
 *
 * Перечень и порядок столбцов берутся из перечисления статуса сгенерированного клиента
 * (`TASK_STATUSES`), а не из своего списка: перечисление уже менялось и может измениться
 * снова — доска обязана пережить это перегенерацией клиента, без правки кода
 * (`../tracker/docs/FRONTEND.md`, «Доска без доски»).
 */
export function TasksBoard({ tasks, hasMore, loadingMore, onMore }: TasksBoardProps) {
  const [opened, setOpened] = useState<Partial<Record<TaskStatus, boolean>>>({});

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
          const open = opened[status] ?? COLLAPSED_BY_DEFAULT[status] !== true;

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
                  onClick={() => setOpened((previous) => ({ ...previous, [status]: !open }))}
                >
                  <code className={styles.status}>{status}</code>
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
