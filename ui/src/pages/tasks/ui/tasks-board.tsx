import { StatusMark, TASK_STATUSES, TaskCard, type Task, type TaskStatus } from '@/entities/task';
import { Button } from '@/shared/ui';
import { cn } from '@/shared/lib';

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
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3 overflow-x-auto pb-2">
        {TASK_STATUSES.map((status) => {
          const column = byStatus.get(status) ?? [];
          const open = !collapsed.includes(status);

          return (
            <section
              key={status}
              /*
               * `relative` — точка отсчёта для абсолютных потомков, прежде всего для
               * `sr-only` спанов, которыми знак статуса называет свой род диктору.
               * Абсолютного потомка обрезает прокручиваемый предок только тогда, когда
               * тот стоит в его цепочке содержащих блоков; пока столбец позиционирован
               * не был, содержащим блоком таких спанов оказывалось окно: доска их не
               * обрезала, и они растягивали документ — с шестым столбцом (UI-40)
               * страница на 1440 px поехала вбок на 103 px вместе с боковой панелью
               * и шапкой. `contain: paint` чинит симптом, но заводит контекст наложения
               * и обрезает тени, поэтому лечится цепочка.
               *
               * Ширина задана и не делится между столбцами: при `flex: 1 1 16rem`
               * раскрытие одного столбца сужало все остальные (замерено: 265 → 190 px),
               * и карточки в столбце, который человек в этот момент читал, переносили
               * текст по-другому. Не влезли — ряд столбцов прокручивается вбок.
               */
              className={cn(
                'relative flex w-(--ui-board-column) shrink-0 basis-(--ui-board-column) flex-col gap-2 rounded-control border border-line bg-sunken p-3',
                /*
                 * Свёрнутый и пустой столбец остаётся столбцом той же ширины (решение
                 * Д19): раньше он превращался в пилюлю по ширине содержимого, и ряд
                 * читался как набор разных вещей — `backlog 0`, `done 32`, `cancelled 0`.
                 * Гаснет он не прозрачностью, а отсутствием заливки: `opacity` смешивает
                 * текст с фоном и роняет контраст (`docs/notes/ui.md`).
                 */
                (!open || column.length === 0) && 'border-dashed bg-transparent',
              )}
              aria-label={status}
            >
              <h3 className="text-body">
                <button
                  type="button"
                  /*
                   * Знак раскрытия рисуется псевдоэлементом, а не узлом разметки: это
                   * оформление кнопки, и диктору его читать незачем — состояние он берёт
                   * из `aria-expanded`. Границы и заливки у кнопки нет вовсе, но названы
                   * они явно: без этого браузер рисует свои `ButtonBorder` и `ButtonFace`.
                   */
                  className="flex w-full items-baseline gap-2 border-none border-current bg-transparent p-0 text-left text-text before:text-muted before:content-['▾'] aria-[expanded=false]:before:content-['▸']"
                  aria-expanded={open}
                  onClick={() => onToggle(status, !open)}
                >
                  {/* Тот же знак, что в списке и на карточке: где бы человек ни
                      увидел `in_progress`, это один и тот же полукруг (решение Д20). */}
                  <StatusMark status={status} className="font-mono" />
                  <span className="text-meta whitespace-nowrap text-muted">
                    {/* «из ?»: сколько задач в статусе всего, знает только дочитанная
                        до конца выдача — врать точным числом до этого нельзя. */}
                    {hasMore ? `${column.length} из ?` : column.length}
                  </span>
                </button>
              </h3>

              {open ? (
                column.length === 0 ? (
                  <p className="text-meta text-muted italic">Пусто</p>
                ) : (
                  <ul className="flex list-none flex-col gap-2 p-0">
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

      <div className="flex flex-wrap items-center gap-3">
        {hasMore ? (
          <>
            <Button onClick={onMore} disabled={loadingMore}>
              {loadingMore ? 'Читаем…' : 'Ещё'}
            </Button>
            <span className="text-label text-muted">
              Показаны не все задачи отбора: столбцы дочитываются по кнопке.
            </span>
          </>
        ) : (
          <span className="text-label text-muted">Показаны все задачи отбора: {tasks.length}.</span>
        )}
      </div>
    </div>
  );
}
