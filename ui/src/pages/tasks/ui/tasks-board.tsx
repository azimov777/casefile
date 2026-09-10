import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  StatusMark,
  TASK_STATUSES,
  TaskCard,
  tasksColumnQueryOptions,
  tasksTotalQueryOptions,
  type TaskListParams,
  type TaskStatus,
} from '@/entities/task';
import { QueryState, Reveal, type QueryLike } from '@/shared/ui';
import { useLanguage } from '@/shared/i18n';
import { cn, formatNumber, useExitHold } from '@/shared/lib';
import { useEndReach } from '../model/end-reach';

interface TasksBoardProps {
  /** Отбор человека без статуса: свой статус дописывает к нему сам столбец. */
  params: TaskListParams;
  /**
   * Отказ уже объяснён формой отбора — столбцы о нём молчат. Иначе один и тот же
   * разбор запроса объяснялся бы разом в шести местах: непрочитанный столбец
   * не знает, что он такой не один.
   */
  explained: boolean;
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
 *
 * Задач доска не получает и не раздаёт: каждый столбец читает свой отбор сам и своим
 * курсором (UI-70). Общего дочитывания под доской поэтому нет вовсе — способ дочитать
 * столбец ровно один, и это его прокрутка.
 */
export function TasksBoard({ params, explained, collapsed, onToggle }: TasksBoardProps) {
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
   * ряд забирает остаток (`flex-1` при `min-h-0`).
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
      className="flex flex-col fold:h-(--ui-board-height)"
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
            params={params}
            explained={explained}
            open={!collapsed.includes(status)}
            onToggle={onToggle}
          />
        ))}
      </div>
    </div>
  );
}

interface BoardColumnProps {
  status: TaskStatus;
  params: TaskListParams;
  explained: boolean;
  open: boolean;
  onToggle: (status: TaskStatus, open: boolean) => void;
}

/**
 * Столбец доски: заголовок со счётчиком и карточки под ним.
 *
 * Свой компонент, а не кусок перебора, потому что читает он сам: свой отбор, свой
 * курсор, своё число. Здесь же живёт раскрытие, которое держит карточки до конца
 * выхода (`useExitHold`), — хук в теле перебора не живёт.
 */
function BoardColumn({ status, params, explained, open, onToggle }: BoardColumnProps) {
  const reveal = useExitHold(open);
  const { t } = useTranslation('tasks');
  const area = useRef<HTMLElement>(null);
  // Число в заголовке идёт за языком, как и всякое число в интерфейсе (UI-79).
  const { language } = useLanguage();

  /*
   * Раскрытый столбец читает карточки страницами, свёрнутый — только своё число.
   * Свёрнуты по умолчанию двое (`done`, `cancelled`), и вычитывать их выдачу ради
   * одного числа в заголовке значило бы читать сотню строк, которых никто не просил.
   */
  const pages = useInfiniteQuery({ ...tasksColumnQueryOptions(status, params), enabled: open });
  const counted = useQuery({
    ...tasksTotalQueryOptions({ ...params, status: [status] }),
    enabled: !open,
  });

  const tasks = pages.data?.pages.flatMap((page) => page.items) ?? [];
  /*
   * Число в заголовке — от бэкенда, а не от длины прочитанного: `meta.total` считает
   * всю выдачу по отбору (TRK-41). Раскрытому столбцу оно приезжает вместе с первой
   * страницей, свёрнутому — отдельным запросом; прочитанное остаётся в кэше, поэтому
   * свёртывание уже читанного столбца числа не роняет.
   */
  const total = pages.data?.pages[0]?.meta?.total ?? counted.data ?? null;
  const empty = total === 0 || (pages.data !== undefined && tasks.length === 0);

  const failed = pages.error !== null && pages.error !== undefined;

  /*
   * Сторож в конце столбца зовёт следующую страницу. Он снимается на время запроса
   * и после отказа: оставленный, он позвал бы снова в том же кадре, в котором вернулся
   * отказ, — и это был бы цикл запросов, которого задача запрещает. Возвращает сторожа
   * удачный повтор по кнопке.
   */
  const end = useEndReach({
    area,
    enabled: open && pages.hasNextPage && !pages.isFetchingNextPage && !failed,
    onReach: () => void pages.fetchNextPage(),
  });

  /**
   * Состояние дочитывания. Отдельно от состояния столбца: «читаем» здесь значит
   * «читаем следующую страницу», а повтор после отказа зовёт её же, а не перечитывает
   * весь столбец с начала.
   */
  const more: QueryLike = {
    isPending: pages.isFetchingNextPage,
    isFetching: pages.isFetchingNextPage,
    error: explained || pages.data === undefined ? null : pages.error,
    refetch: () => void pages.fetchNextPage(),
  };

  return (
    <section
      ref={area}
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
       * внутри него, соседние столбцы и страница при этом стоят. Она же корень
       * наблюдателя, который дочитывает столбец по мере прокрутки: ниже точки
       * остановки прокрутки у столбца нет вовсе, и корнем там становится окно
       * (`useEndReach`, `scrollingArea`). Отдельного `tabIndex` под прокрутку
       * не нужно — кнопка свёртывания стоит внутри самого прокручиваемого столбца,
       * и с фокусом на ней он ходит стрелками и `PageDown`.
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
        (!reveal.held || empty) && 'border-dashed bg-transparent',
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
            {/* Сколько задач в статусе, говорит бэкенд. Пока не сказал, врать нечем:
                раскрытый столбец говорит «столько-то из ?» о прочитанном, свёрнутый
                не говорит и этого — он не читал ничего. */}
            {total === null
              ? open
                ? t('board.ofUnknown', { count: tasks.length })
                : t('board.unknown')
              : formatNumber(total, language)}
          </span>
        </button>
      </h3>

      {reveal.held ? (
        <Reveal leaving={reveal.leaving} entering={reveal.entering}>
          {pages.data === undefined ? (
            /*
             * Первого ответа ещё нет — или не будет вовсе. И то и другое сказано
             * словами, а отказ ещё и с кнопкой повтора: молчащий столбец неотличим
             * от пустого. Молчит он ровно в одном случае — когда тот же отказ уже
             * объяснён формой отбора у поля запроса.
             */
            <div className="mt-2">
              {explained ? null : <QueryState query={pages} loading={t('board.reading')} />}
            </div>
          ) : tasks.length === 0 ? (
            <p className="mt-2 text-meta text-muted italic">{t('board.empty')}</p>
          ) : (
            <>
              <ul className="mt-2 flex list-none flex-col gap-2 p-0">
                {tasks.map((task) => (
                  <li key={task.key}>
                    <TaskCard task={task} />
                  </li>
                ))}
              </ul>

              {/*
               * Сторож конца: узел под последней карточкой. Дочитывание начинается,
               * когда до него остаётся четверть высоты столбца, — то есть по мере
               * прокрутки, а не по нажатию. Диктору узел не нужен: то же самое ему
               * скажет состояние под ним.
               *
               * `h-px`, а не пустая высота: узел нулевой высоты наблюдатель считает
               * видимым и внутри обрезанного места, поэтому раскрытие столбца читало
               * страницу за страницей, пока едет движение (замерено: 30 карточек
               * вместо 10). У узла с высотой обрезание отнимает всё пересечение,
               * и движение остаётся движением, а не поводом читать.
               */}
              <div ref={end} className="h-px" aria-hidden="true" />

              {more.isPending || more.error !== null ? (
                <div className="mt-2">
                  <QueryState query={more} loading={t('board.readingMore')} compact />
                </div>
              ) : null}
            </>
          )}
        </Reveal>
      ) : null}
    </section>
  );
}
