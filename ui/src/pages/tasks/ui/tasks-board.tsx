import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
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
  const byStatus = new Map<TaskStatus, Task[]>(TASK_STATUSES.map((status) => [status, []]));
  for (const task of tasks) {
    const status = task.status;
    if (status === null || status === undefined) continue;
    byStatus.get(status)?.push(task);
  }

  /*
   * Доска высотой в остаток окна: столбец прокручивается внутри себя, а страница
   * под ним не двигается вовсе (UI-68).
   *
   * Остаток считается замером, а не одним `calc`, потому что над доской нет ни одной
   * величины, известной заранее: верхняя полоса задана минимумом и растёт от
   * увеличенного текста, заголовок с формой отбора переносится по ширине окна и
   * раскрывается по нажатию. Замеряется только отступ доски от верха документа —
   * своя высота доски в него не входит, поэтому обратной связи «выросла — пересчитали —
   * снова выросла» здесь нет. Всё, что ниже ряда столбцов, раздаёт уже флексбокс:
   * подвал занимает своё, ряд забирает остаток (`flex-1` при `min-h-0`).
   */
  const boardRef = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);

  useLayoutEffect(() => {
    const board = boardRef.current;
    if (board === null) return;
    const measure = () => {
      setTop(Math.round(board.getBoundingClientRect().top + window.scrollY));
    };
    measure();

    /*
     * Наблюдают за родителем, а не за `document.body`: `body` объявлен `height: 100%`
     * (`shared/styles/reset.css`), его рамка равна окну всегда, и раскрытая форма
     * отбора его не меняет — доска съезжала вниз, оставаясь прежней высоты, и страница
     * снова начинала прокручиваться. Родитель растёт вместе с тем, что стоит над
     * доской, и это ровно то событие, из-за которого замер устарел.
     */
    const above = board.parentElement;
    const observer = new ResizeObserver(() => {
      // Через кадр: пересчёт идёт из обработчика наблюдателя, и без этого браузер
      // ругается на не доставленные за проход уведомления.
      window.requestAnimationFrame(measure);
    });
    if (above !== null) observer.observe(above);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);

  return (
    <div
      ref={boardRef}
      style={
        { '--ui-board-height': `calc(100dvh - ${top}px - var(--ui-page-tail))` } as CSSProperties
      }
      className="flex flex-col gap-4 fold:h-(--ui-board-height)"
    >
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
       *
       * `fold:flex-1` при `fold:min-h-0` — ряд забирает остаток доски под собой,
       * а `min-h-0` снимает с него пол по содержимому, иначе прокручиваться было бы
       * нечему. Обе утилиты стоят от точки остановки: ниже неё у доски нет своей
       * высоты, и `flex-1` без неё схлопнул бы ряд в ноль.
       */}
      <div className="flex items-stretch gap-3 overflow-x-auto pb-2 fold:min-h-0 fold:flex-1">
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
       *
       * `fold:overflow-y-auto` — своя прокрутка столбца (UI-68): карточки уезжают
       * внутри него, соседние столбцы и страница при этом стоят. Отдельного
       * `tabIndex` под это не нужно — кнопка свёртывания стоит внутри самого
       * прокручиваемого столбца, и с фокусом на ней он ходит стрелками и `PageDown`.
       * Ниже точки остановки прокрутки у столбца нет вовсе: там доске остаётся
       * полторы карточки, и страница отдаёт столбцу весь экран (`docs/notes/ui.md`,
       * «Две прокрутки уживаются ровно тогда, когда у страницы прокрутки не остаётся»).
       */
      className={cn(
        'relative flex w-(--ui-board-column) shrink-0 basis-(--ui-board-column) flex-col rounded-control border border-line bg-sunken p-3 fold:min-h-0 fold:overflow-y-auto',
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
            {hasMore ? `${column.length} из ?` : column.length}
          </span>
        </button>
      </h3>

      {reveal.held ? (
        <Reveal leaving={reveal.leaving} entering={reveal.entering}>
          {column.length === 0 ? (
            <p className="mt-2 text-meta text-muted italic">Пусто</p>
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
