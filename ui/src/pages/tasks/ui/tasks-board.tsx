import { useTranslation } from 'react-i18next';
import { StatusMark, TASK_STATUSES, TaskCard, type Task, type TaskStatus } from '@/entities/task';
import { Button, Reveal } from '@/shared/ui';
import { cn, useExitHold } from '@/shared/lib';

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
  const { t } = useTranslation('tasks');
  const byStatus = new Map<TaskStatus, Task[]>(TASK_STATUSES.map((status) => [status, []]));
  for (const task of tasks) {
    const status = task.status;
    if (status === null || status === undefined) continue;
    byStatus.get(status)?.push(task);
  }

  return (
    <div className="flex flex-col gap-4">
      {/*
       * `items-stretch`, а не Tailwind по умолчанию (`items-start` стояло здесь до
       * UI-67): столбец — это рамка ровно по числу карточек, флекс-ряд без выравнивания
       * растягивает высоту ряда до самого длинного столбца, но не растягивает в неё
       * остальные. Короткий столбец рядом с длинным гас пустотой уже на второй
       * карточке, ничем не отличимой от пустоты соседа, — доска читалась как один
       * общий поток в шести колонках, а не как шесть отдельных отборов по статусу.
       * `items-stretch` растягивает саму секцию столбца (заливку и границу) до высоты
       * ряда; карточки внутри неё по-прежнему пакуются сверху (`flex-col`, без
       * `flex-grow` на списке), поэтому лишняя высота уходит в пустое место под
       * последней карточкой, а не растягивает сами карточки.
       */}
      <div className="flex items-stretch gap-3 overflow-x-auto pb-2">
        {TASK_STATUSES.map((status) => (
          <BoardColumn
            key={status}
            status={status}
            column={byStatus.get(status) ?? []}
            hasMore={hasMore}
            open={!collapsed.includes(status)}
            onToggle={onToggle}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {hasMore ? (
          <>
            <Button onClick={onMore} disabled={loadingMore}>
              {loadingMore ? t('board.loadingMore') : t('board.more')}
            </Button>
            <span className="text-label text-muted">{t('board.partial')}</span>
          </>
        ) : (
          <span className="text-label text-muted">{t('board.all', { count: tasks.length })}</span>
        )}
      </div>
    </div>
  );
}

interface BoardColumnProps {
  status: TaskStatus;
  column: Task[];
  hasMore: boolean;
  open: boolean;
  onToggle: (status: TaskStatus, open: boolean) => void;
}

/**
 * Столбец доски: заголовок со счётчиком и карточки под ним.
 *
 * Свой компонент, а не кусок перебора, потому что раскрытие держит свои карточки
 * до конца выхода (`useExitHold`), а хук в теле перебора не живёт.
 */
function BoardColumn({ status, column, hasMore, open, onToggle }: BoardColumnProps) {
  const reveal = useExitHold(open);
  const { t } = useTranslation('tasks');

  return (
    <section
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
       *
       * Промежутка `gap-2` между заголовком и карточками нет: он стоит на самих
       * карточках (`mt-2`) и потому уезжает вместе с местом. Промежуток между
       * соседями держался бы, пока стоит сосед, и свёртывание кончалось бы
       * скачком в восемь пикселей.
       */
      className={cn(
        'relative flex w-(--ui-board-column) shrink-0 basis-(--ui-board-column) flex-col rounded-control border border-line bg-sunken p-3',
        /*
         * Свёрнутый и пустой столбец остаётся столбцом той же ширины (решение
         * Д19): раньше он превращался в пилюлю по ширине содержимого, и ряд
         * читался как набор разных вещей — `backlog 0`, `done 32`, `cancelled 0`.
         * Гаснет он не прозрачностью, а отсутствием заливки: `opacity` смешивает
         * текст с фоном и роняет контраст (`docs/notes/ui.md`).
         *
         * Считается это по тому, держат ли карточки, а не по самому раскрытию:
         * пока свёртывание едет, столбец ещё со своими карточками, и рамка,
         * ставшая пунктирной в первом кадре, объявила бы его пустым раньше времени.
         *
         * С UI-67 высота у всех шести столбцов одна — по самому длинному
         * (`items-stretch` на ряду), — и различие полного, пустого и свёрнутого
         * столбца держится **только** на этой паре классов: заливка есть или нет,
         * граница сплошная или пунктирная. Высота им общая и раньше не давала
         * ничего, кроме случайного совпадения на коротких столбцах; теперь она
         * не даёт и его.
         */
        (!reveal.held || column.length === 0) && 'border-dashed bg-transparent',
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
            {hasMore ? t('board.ofUnknown', { count: column.length }) : column.length}
          </span>
        </button>
      </h3>

      {reveal.held ? (
        <Reveal leaving={reveal.leaving} entering={reveal.entering}>
          {column.length === 0 ? (
            <p className="mt-2 text-meta text-muted italic">{t('board.empty')}</p>
          ) : (
            <ul className="mt-2 flex list-none flex-col gap-2 p-0">
              {column.map((task) => (
                <li key={task.key}>
                  <TaskCard task={task} />
                </li>
              ))}
            </ul>
          )}
        </Reveal>
      ) : null}
    </section>
  );
}
