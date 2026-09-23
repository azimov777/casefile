import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { Ref } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AuthorName,
  EntryBody,
  EntryHeadline,
  EntryKind,
  entryHeadline,
  entryQueryOptions,
  groupSectionEdits,
  sectionEditsHeadline,
  type EntryHeading,
  type SectionEditsRun,
} from '@/entities/entry';
import { cn, useExitHold } from '@/shared/lib';
import { QueryState, RelativeTime, Reveal, TaskText } from '@/shared/ui';

/** Императивная ручка `TaskIndex`: прыжок «в начало описи» стоит в шапке блока
 * (`task-page.tsx`, `INDEX_NAV`, UI-127) и дотягивается снаружи ровно до того узла,
 * куда раньше вела кнопка внутри самой описи, — второго пути прокрутки не заводим. */
export interface TaskIndexHandle {
  scrollToTop: () => void;
}

interface TaskIndexProps {
  taskKey: string;
  index: EntryHeading[];
  /** Обзорные проверки задачи: вердикту нужен текст его проверки. */
  checks: string[];
  /**
   * Номер записи из адреса: ссылка `TRK-42#12` или загрузка страницы с `?entry=N`
   * открывает карточку уже раскрытой и приводит запись в поле зрения. Собственный
   * клик по описи меняет тот же параметр (`onOpenChange`), но не через этот проп:
   * `TaskIndex` отличает пришедшее снаружи от своего клика сам (`internalChange`).
   */
  openAt: number | null;
  /**
   * Раскрытие записи человеком уходит в адрес. `null` — «раскрытого больше нет»:
   * закрыв ту запись, ради которой пришёл, человек не должен уносить её номер
   * в адресе дальше.
   */
  onOpenChange: (no: number | null) => void;
  /** Ручка на прыжок «в начало описи» — вызывается из шапки блока (`task-page.tsx`). */
  ref?: Ref<TaskIndexHandle>;
}

/**
 * Ячейка описи: поля, линия под строкой и выравнивание по верху — одинаковые
 * у заголовков и у данных. Раньше это был потомковый селектор `.table th, .table td`;
 * утилите не на чем висеть, кроме самой ячейки, поэтому набор назван один раз здесь.
 *
 * Линия остаётся и под раскрытой строкой. В модуле стояло `.opened > * {
 * border-bottom: none }`, но оно не действовало ни разу: `.opened > *` — это 0-1-0,
 * а `.table td` — 0-1-1, и граница выигрывала. Переносится наблюдаемое, а не
 * написанное: раскрытая строка меняет только заливку.
 *
 * Цвет назван стороной (`border-b-line`, а не `border-line`): `border-line` красит все
 * четыре стороны, и три из них перестали бы быть `currentColor`. Ширина у них нулевая,
 * на экране этого не видно — а в вычисленном стиле видно, и замер это ловит.
 */
const CELL =
  'border-b border-b-line px-3 py-2 text-left align-top @max-index:border-b-0 @max-index:p-0';

/**
 * Строка описи там, где пяти столбцам не хватает места (`--container-index`, UI-134):
 * та же `<tr>` становится флексом с переносом, и ячейки встают в порядке разметки —
 * номер, род, автор и время первой строкой, заголовок второй (он берёт всю ширину,
 * `HEADLINE`). Время прижато вправо (`ml-auto`): не поместившись в первую строку
 * рядом с длинным родом и автором, оно уходит к правому краю, а не висит слева одно. Поля и линию под строкой в этой ветке несёт строка, а не ячейка: у
 * ячеек флекса своих линий быть не должно, иначе под первой строкой карточки легла бы
 * вторая черта.
 *
 * До UI-134 узкая опись была таблицей в прокрутке вбок: на 390 px заголовок записи —
 * то, ради чего опись читают, — стоял целиком за правым краем.
 */
const ROW =
  '@max-index:flex @max-index:flex-wrap @max-index:items-baseline @max-index:gap-x-3 @max-index:gap-y-1 @max-index:border-b @max-index:border-b-line @max-index:px-3 @max-index:py-2';

/** Ячейка заголовка: в карточке — вся вторая строка. */
const HEADLINE = '@max-index:basis-full';

/**
 * Опись дела: заголовок каждой записи, тело — по клику.
 *
 * Так дело и задумано читать (`CONCEPT.md`, 4): полное дело весит столько, что карточка
 * открывалась бы секундами, а нужны из него обычно две-три записи.
 */
/** Столбцы описи по порядку: подписи к ним живут в словаре (`task.index.columns`). */
const INDEX_COLUMNS = ['no', 'type', 'author', 'when', 'headline'] as const;

export function TaskIndex({ taskKey, index, checks, openAt, onOpenChange, ref }: TaskIndexProps) {
  const { t } = useTranslation('task');

  // Раскрытых может быть несколько — сравнивают соседние записи. В адрес уходит
  // последняя раскрытая: адрес называет запись, ради которой человек здесь, и
  // перезагрузка возвращает её раскрытой.
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(openAt === null ? [] : [openAt]),
  );
  /**
   * Запись, к которой ведёт прокрутка. Отдельно от `expanded`: раскрытых бывает
   * несколько, а прокрутка нужна только той записи, к которой человек **пришёл** —
   * по ссылке `TRK-42#12` или по загрузке страницы с `?entry=N`. Собственный клик
   * по описи (`toggle`) адрес тоже меняет, но сюда не попадает: `internalChange`
   * метит его заранее, и разбор следующего `openAt` эту метку гасит, не трогая
   * прокрутку. Единственный путь прокрутки — сравнение этого поля с номером записи
   * в `IndexRow`, без второго условия рядом.
   */
  const [scrollTarget, setScrollTarget] = useState<number | null>(null);
  /**
   * Группы правок разделов, раскрытые человеком, — по номеру первой записи группы.
   * Группа раскрыта и тогда, когда раскрыта любая её запись: ссылка `TRK-106#8` ведёт
   * к записи внутри группы, и прятать её за свёрнутой строкой значило бы не довести
   * человека до того, за чем он шёл (UI-133). Поэтому это не всё состояние группы, а
   * только её собственный клик; остальное выводится из `expanded`.
   */
  const [openGroups, setOpenGroups] = useState<Set<number>>(() => new Set());
  /** Метка «следующая правка `openAt` — от своего клика, не от прихода снаружи». */
  const internalChange = useRef(false);
  /** Начало описи: сюда возвращает прыжок «в начало» — кнопка стоит в шапке блока
   * (`task-page.tsx`), а дотягивается до этого узла через `TaskIndexHandle`. */
  const scroller = useRef<HTMLDivElement>(null);

  useImperativeHandle(
    ref,
    () => ({
      scrollToTop: () => scroller.current?.scrollIntoView?.({ block: 'start' }),
    }),
    [],
  );

  // Ссылка `TRK-42#12` внутри той же карточки меняет адрес, не перемонтируя страницу,
  // поэтому раскрытие следит за параметром, а не только за первым рендером. Метка
  // читается и гасится здесь же, до раннего выхода: иначе клик, закрывший запись,
  // не названную в адресе (`openAt` не меняется, эффект не перезапускается), оставил
  // бы метку висеть и погасил бы прокрутку следующего настоящего перехода по ссылке.
  useEffect(() => {
    const internal = internalChange.current;
    internalChange.current = false;
    if (openAt === null) return;
    setExpanded((previous) => (previous.has(openAt) ? previous : new Set(previous).add(openAt)));
    if (!internal) setScrollTarget(openAt);
  }, [openAt]);

  const toggle = useCallback(
    (no: number) => {
      // Решение принимается снаружи обновления состояния: правка адреса — побочное
      // действие, а функцию обновления React вправе позвать дважды.
      const closing = expanded.has(no);

      setExpanded((previous) => {
        const next = new Set(previous);
        if (closing) next.delete(no);
        else next.add(no);
        return next;
      });

      // Закрыли ту запись, что названа в адресе, — адрес перестаёт её называть;
      // закрыли соседнюю — названная остаётся названной.
      const nextOpenAt = closing ? (openAt === no ? null : openAt) : no;
      // Метка ставится, только если `openAt` и правда меняется: иначе эффект выше
      // не перезапустится вовсе (тот же номер — тот же `Object.is`), метка останется
      // висеть и собьёт разбор следующего прихода снаружи.
      if (nextOpenAt !== openAt) internalChange.current = true;
      onOpenChange(nextOpenAt);
    },
    [expanded, onOpenChange, openAt],
  );

  /*
   * Группа сворачивается целиком: вместе с ней закрываются и раскрытые в ней записи,
   * иначе она осталась бы раскрытой через них (см. `openGroups`). Если среди них та,
   * что названа в адресе, адрес перестаёт её называть — как у одиночной записи.
   */
  const toggleGroup = useCallback(
    (first: number, members: number[]) => {
      const open = openGroups.has(first) || members.some((no) => expanded.has(no));
      setOpenGroups((previous) => {
        const next = new Set(previous);
        if (open) next.delete(first);
        else next.add(first);
        return next;
      });
      if (!open) return;
      setExpanded((previous) => {
        const next = new Set(previous);
        for (const no of members) next.delete(no);
        return next;
      });
      if (openAt !== null && members.includes(openAt)) {
        internalChange.current = true;
        onOpenChange(null);
      }
    },
    [expanded, onOpenChange, openAt, openGroups],
  );

  // Пустая опись стоит в той же поверхности-списке без полей, что и таблица, и поле
  // ей нужно то же, что у ячейки (`CELL`): без него «записей нет» прижималось к рамке
  // блока (UI-141).
  if (index.length === 0) return <p className="px-3 py-2 text-muted italic">{t('index.empty')}</p>;

  return (
    // Число записей и прыжки по описи стоят в шапке блока над таблицей
    // (`task-page.tsx`, `BLOCK_HEAD`/`INDEX_NAV`): там же общие поля блока и переход
    // в ленту. Ref на прокручиваемый узел — для прыжка «в начало» снаружи (UI-127),
    // сама прокрутка отдельной записи — `scrollTarget`, ниже (UI-126).
    <div className="@container overflow-x-auto" ref={scroller}>
      <table
        className="w-full border-collapse text-body @max-index:block"
        aria-label={t('index.count', { count: index.length })}
      >
        {/* В карточках шапка остаётся диктору: по ней он называет столбец ячейки. */}
        <thead className="@max-index:sr-only">
          <tr>
            {INDEX_COLUMNS.map((column) => (
              <th
                key={column}
                scope="col"
                className={cn(CELL, 'text-meta font-semibold whitespace-nowrap text-muted')}
              >
                {t(`index.columns.${column}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="@max-index:block">
          {groupSectionEdits(index).map((run) =>
            run.kind === 'one' ? (
              <IndexRow
                key={run.item.no}
                taskKey={taskKey}
                heading={run.item}
                checks={checks}
                open={expanded.has(run.item.no)}
                scrollTo={scrollTarget === run.item.no}
                onToggle={toggle}
              />
            ) : (
              <GroupRows
                key={`group-${run.first}`}
                taskKey={taskKey}
                run={run}
                checks={checks}
                open={openGroups.has(run.first) || run.items.some((item) => expanded.has(item.no))}
                expanded={expanded}
                scrollTarget={scrollTarget}
                onToggle={toggle}
                onToggleGroup={toggleGroup}
              />
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

interface GroupRowsProps {
  taskKey: string;
  run: Extract<SectionEditsRun<EntryHeading>, { kind: 'sections' }>;
  checks: string[];
  open: boolean;
  expanded: Set<number>;
  scrollTarget: number | null;
  onToggle: (no: number) => void;
  onToggleGroup: (first: number, members: number[]) => void;
}

/**
 * Правки разделов одного действия: одна строка описи вместо семи (UI-133).
 *
 * Строка группы стоит в тех же столбцах, что и запись: номера крайних записей, род,
 * автор и время действия — у записей одного вызова они одни, — и заголовок-кнопка
 * «Правка разделов» с именами разделов. Раскрытая группа показывает свои записи
 * обычными строками описи, со своим раскрытием каждая: записи не исчезают из дела и
 * остаются адресуемыми по номеру.
 */
function GroupRows({
  taskKey,
  run,
  checks,
  open,
  expanded,
  scrollTarget,
  onToggle,
  onToggleGroup,
}: GroupRowsProps) {
  const { t: brick } = useTranslation('ui');
  const [head] = run.items;
  if (head === undefined) return null;
  const members = run.items.map((item) => item.no);
  const headline = sectionEditsHeadline(
    run.items.map((item) => (item.facts.type === 'section_changed' ? item.facts.field : null)),
    brick,
  );
  const cell = open ? cn(CELL, 'bg-sunken') : CELL;

  return (
    <>
      <tr data-group={run.actionId} className={cn(ROW, open && 'bg-sunken')}>
        <th
          scope="row"
          className={cn(cell, 'w-[1%] @max-index:w-auto font-mono whitespace-nowrap text-muted')}
        >
          {brick('entry.group.range', { first: run.first, last: run.last })}
        </th>
        <td className={cell}>
          <EntryKind type={head.type} />
        </td>
        <td className={cell}>
          <AuthorName author={head.author} />
        </td>
        <td className={cn(cell, 'whitespace-nowrap text-muted @max-index:ml-auto')}>
          <RelativeTime value={head.created_at} />
        </td>
        <td className={cn(cell, HEADLINE)}>
          {/*
           * Тот же вид кнопки, что у строки записи (`IndexRow`): раскрытие группы и
           * раскрытие записи — одно действие для человека. Отличие одно — кнопка
           * флекс-контейнер: строка группы длинная (семь имён разделов), а собранный
           * заголовок — `inline-flex` с переносом, и в строчной кнопке он целиком
           * уезжал под треугольник, оставляя его одного на первой строке. Флексом
           * треугольник — свой элемент слева, заголовок переносится рядом с ним.
           */}
          <button
            type="button"
            className="flex cursor-pointer items-baseline gap-1 border-none border-current bg-transparent p-0 text-left text-text before:text-muted before:content-['▸'] hover:underline aria-expanded:before:content-['▾']"
            aria-expanded={open}
            aria-label={brick('entry.group.label', { first: run.first, last: run.last })}
            onClick={() => onToggleGroup(run.first, members)}
          >
            <EntryHeadline headline={headline} linked={false} />
          </button>
        </td>
      </tr>
      {open
        ? run.items.map((item) => (
            <IndexRow
              key={item.no}
              taskKey={taskKey}
              heading={item}
              checks={checks}
              open={expanded.has(item.no)}
              scrollTo={scrollTarget === item.no}
              onToggle={onToggle}
              nested
            />
          ))
        : null}
    </>
  );
}

interface IndexRowProps {
  taskKey: string;
  heading: EntryHeading;
  checks: string[];
  open: boolean;
  /**
   * Запись внутри раскрытой группы правок (UI-133): заголовок сдвинут вправо, и
   * строка читается частью группы над ней, а не соседней записью.
   */
  nested?: boolean;
  /**
   * Запись, к которой человек **пришёл** (ссылка, `?entry=N` при загрузке, «К свежей
   * записи»), показать не ниже сгиба. Собственный клик по описи сюда не попадает —
   * он только раскрывает: строка остаётся там, где по ней кликнули (UI-126).
   */
  scrollTo: boolean;
  onToggle: (no: number) => void;
}

function IndexRow({
  taskKey,
  heading,
  checks,
  open,
  nested = false,
  scrollTo,
  onToggle,
}: IndexRowProps) {
  // Заголовок описи собирается из фактов записи подписями пространства `ui`: одна
  // и та же строка стоит и здесь, и в ленте дела.
  const { t: brick } = useTranslation('ui');
  const row = useRef<HTMLTableRowElement>(null);
  /*
   * Тело записи доживает выход: без этого сворачивание убирало бы строку в том же
   * кадре. Держится строка целиком, а не её содержимое: пустая строка таблицы стояла
   * бы под каждой записью описи и добавляла бы каждой лишнюю линию и лишний ряд
   * для программы чтения с экрана. Второго запроса доживающий узел не делает —
   * ключ запроса тот же, и ответ берётся из кэша.
   */
  const details = useExitHold(open);
  const headline = entryHeadline(heading.facts, taskKey, brick);
  /* Раскрытая строка утоплена заливкой и так читается вместе со своим телом ниже. */
  const cell = open ? cn(CELL, 'bg-sunken') : CELL;

  useEffect(() => {
    if (!scrollTo) return;
    // В jsdom этого метода нет: страничный тест проверяет раскрытие, а не прокрутку.
    row.current?.scrollIntoView?.({ block: 'center' });
  }, [scrollTo]);

  return (
    <>
      <tr
        ref={row}
        data-nested={nested ? '' : undefined}
        className={cn(ROW, open && 'bg-sunken', nested && '@max-index:pl-8')}
      >
        {/* Ширина в 1% сжимает колонку номера по содержимому: остаток ширины таблицы
            забирает заголовок, самая длинная ячейка строки. */}
        <th scope="row" className={cn(cell, 'w-[1%] @max-index:w-auto font-mono text-muted')}>
          {heading.no}
        </th>
        <td className={cell}>
          {/* Род записи знаком (решение Д10): в описи их по двадцать подряд, и
              `verdict` от `section_changed` иначе отличается только чтением слова. */}
          <EntryKind type={heading.type} />
        </td>
        <td className={cell}>
          <AuthorName author={heading.author} />
        </td>
        <td className={cn(cell, 'whitespace-nowrap text-muted @max-index:ml-auto')}>
          <RelativeTime value={heading.created_at} />
        </td>
        <td className={cn(cell, HEADLINE, nested && 'pl-8')}>
          {/*
           * Заголовок записи — кнопка: раскрытие это действие, и с клавиатуры оно
           * тоже нужно. Фон и рамку кнопка называет явно: без объявленного фона
           * браузер рисует свой `ButtonFace` (`docs/notes/ui.md`, «Кнопка без
           * объявленного фона»), а рамка у неё своя по умолчанию — и снять её мало,
           * надо ещё вернуть цвет: `border: none` возвращал `currentColor`, а
           * `border-none` трогает только начертание и оставляет `buttonborder`.
           *
           * Треугольник перед заголовком — псевдоэлемент, а не узел разметки: диктор
           * читает состояние по `aria-expanded`, и второй, текстовый, знак того же
           * состояния он произнёс бы вслух.
           */}
          <button
            type="button"
            className="cursor-pointer border-none border-current bg-transparent p-0 text-left text-text before:text-muted before:content-['▸_'] hover:underline aria-expanded:before:content-['▾_']"
            aria-expanded={open}
            onClick={() => onToggle(heading.no)}
          >
            {/*
             * Заголовок собирается по фактам описи, а не берётся готовым: у служебных
             * записей, у ответа и вердикта его строит трекер и строит по-английски.
             * У записи агента заголовок написан автором — его и показываем.
             */}
            {headline.kind === 'built' ? (
              <EntryHeadline headline={headline} linked={false} />
            ) : (
              heading.title
            )}
          </button>
        </td>
      </tr>

      {details.held ? (
        <tr className="@max-index:block">
          {/*
           * Поля ячейки переехали внутрь обёртки (`p-0` снаружи, `px-3 py-2` внутри):
           * снаружи они держали бы высоту и свёрнутое состояние нулём бы не стало.
           * Линия под строкой и заливка остаются на ячейке — они видны и на нулевой
           * высоте ровно один кадр, пока строка уходит.
           */}
          <td
            className={cn(CELL, 'bg-sunken p-0 @max-index:block @max-index:border-b')}
            colSpan={5}
          >
            <Reveal hold={details}>
              <div className="px-3 py-2">
                <EntryDetails
                  taskKey={taskKey}
                  no={heading.no}
                  checks={checks}
                  title={heading.title}
                />
              </div>
            </Reveal>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * Тело одной записи: свой запрос на свой номер (`entries?nos=N`).
 *
 * Ключ запроса — номер, поэтому закрытая и снова раскрытая запись берётся из кэша,
 * а не спрашивается второй раз.
 */
function EntryDetails({
  taskKey,
  no,
  checks,
  title,
}: {
  taskKey: string;
  no: number;
  checks: string[];
  title: string;
}) {
  const entry = useQuery(entryQueryOptions(taskKey, no));
  const { t } = useTranslation('task');

  return (
    /*
     * Предел ширины тела записи — своё число, а не `--ui-text-max` (62ch): тот вдвое
     * уже и обрезал бы таблицы и блоки кода, которые в теле записи бывают.
     */
    <div className="flex max-w-[60rem] flex-col gap-2">
      <p className="font-semibold">
        <TaskText>{title}</TaskText>
      </p>
      <QueryState query={entry} loading={t('index.loadingEntry')} />
      {entry.data == null ? null : <EntryBody entry={entry.data} checks={checks} />}
    </div>
  );
}
