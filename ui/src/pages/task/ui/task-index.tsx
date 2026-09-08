import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AuthorName,
  EntryBody,
  EntryHeadline,
  EntryKind,
  entryHeadline,
  entryQueryOptions,
  type EntryHeading,
} from '@/entities/entry';
import { cn } from '@/shared/lib';
import { Button, QueryState, RelativeTime, TaskText } from '@/shared/ui';

interface TaskIndexProps {
  taskKey: string;
  index: EntryHeading[];
  /** Обзорные проверки задачи: вердикту нужен текст его проверки. */
  checks: string[];
  /** Номер записи из адреса: ссылка `TRK-42#12` открывает карточку уже раскрытой. */
  openAt: number | null;
  /**
   * Раскрытие записи человеком уходит в адрес. `null` — «раскрытого больше нет»:
   * закрыв ту запись, ради которой пришёл, человек не должен уносить её номер
   * в адресе дальше.
   */
  onOpenChange: (no: number | null) => void;
}

/**
 * Опись длиннее этого читается прокруткой, и по ней имеет смысл прыгать. Короткая
 * видна целиком, и два действия над ней были бы шумом там, где всё и так на экране.
 */
const LONG_INDEX = 12;

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
const CELL = 'border-b border-b-line px-3 py-2 text-left align-top';

/**
 * Опись дела: заголовок каждой записи, тело — по клику.
 *
 * Так дело и задумано читать (`CONCEPT.md`, 4): полное дело весит столько, что карточка
 * открывалась бы секундами, а нужны из него обычно две-три записи.
 */
export function TaskIndex({ taskKey, index, checks, openAt, onOpenChange }: TaskIndexProps) {
  // Раскрытых может быть несколько — сравнивают соседние записи. В адрес уходит
  // последняя раскрытая: адрес называет запись, ради которой человек здесь, и
  // перезагрузка возвращает её раскрытой.
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(openAt === null ? [] : [openAt]),
  );
  /** Начало описи: сюда возвращает прыжок «в начало», не трогая прокрутку страницы. */
  const scroller = useRef<HTMLDivElement>(null);

  // Ссылка `TRK-42#12` внутри той же карточки меняет адрес, не перемонтируя страницу,
  // поэтому раскрытие следит за параметром, а не только за первым рендером.
  useEffect(() => {
    if (openAt === null) return;
    setExpanded((previous) => (previous.has(openAt) ? previous : new Set(previous).add(openAt)));
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
      onOpenChange(closing ? (openAt === no ? null : openAt) : no);
    },
    [expanded, onOpenChange, openAt],
  );

  if (index.length === 0) return <p className="text-muted italic">Дело пусто: записей ещё нет.</p>;

  // Последняя запись всего дела: опись приходит пакетом задачи целиком, поэтому это
  // именно последняя, а не последняя из подгруженных (`../tracker/docs/FRONTEND.md`).
  const lastNo = index[index.length - 1]?.no ?? null;

  return (
    /* Прыжки над описью, а не под ней: «к свежей записи» нужно до чтения, а не после. */
    <div className="flex flex-col gap-2">
      {index.length > LONG_INDEX && lastNo !== null ? (
        /*
         * Два прыжка по описи: к свежей записи и обратно к началу. Свежая раскрывается
         * и читается точечно — своим запросом на свой номер, а не чтением всего дела
         * до неё. Прыгает человек, а не экран: живой поток опись не прокручивает.
         */
        <div className="flex flex-wrap gap-2">
          <Button tone="quiet" onClick={() => onOpenChange(lastNo)}>
            К свежей записи
          </Button>
          <Button
            tone="quiet"
            onClick={() => scroller.current?.scrollIntoView?.({ block: 'start' })}
          >
            В начало описи
          </Button>
        </div>
      ) : null}

      <div className="overflow-x-auto" ref={scroller}>
        <table className="w-full border-collapse text-body">
          <caption className="px-3 pt-2 text-left text-meta text-muted">
            Записей в деле: {index.length}
          </caption>
          <thead>
            <tr>
              {['№', 'Тип', 'Автор', 'Когда', 'Заголовок'].map((column) => (
                <th
                  key={column}
                  scope="col"
                  className={cn(CELL, 'text-meta font-semibold whitespace-nowrap text-muted')}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {index.map((heading) => (
              <IndexRow
                key={heading.no}
                taskKey={taskKey}
                heading={heading}
                checks={checks}
                open={expanded.has(heading.no)}
                scrollTo={openAt === heading.no}
                onToggle={toggle}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface IndexRowProps {
  taskKey: string;
  heading: EntryHeading;
  checks: string[];
  open: boolean;
  /** Запись, названную в адресе, показать человеку, а не оставить где-то ниже сгиба. */
  scrollTo: boolean;
  onToggle: (no: number) => void;
}

function IndexRow({ taskKey, heading, checks, open, scrollTo, onToggle }: IndexRowProps) {
  const row = useRef<HTMLTableRowElement>(null);
  const headline = entryHeadline(heading.facts, taskKey);
  /* Раскрытая строка утоплена заливкой и так читается вместе со своим телом ниже. */
  const cell = open ? cn(CELL, 'bg-sunken') : CELL;

  useEffect(() => {
    if (!scrollTo) return;
    // В jsdom этого метода нет: страничный тест проверяет раскрытие, а не прокрутку.
    row.current?.scrollIntoView?.({ block: 'center' });
  }, [scrollTo]);

  return (
    <>
      <tr ref={row}>
        {/* Ширина в 1% сжимает колонку номера по содержимому: остаток ширины таблицы
            забирает заголовок, самая длинная ячейка строки. */}
        <th scope="row" className={cn(cell, 'w-[1%] font-mono text-muted')}>
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
        <td className={cn(cell, 'whitespace-nowrap text-muted')}>
          <RelativeTime value={heading.created_at} />
        </td>
        <td className={cell}>
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

      {open ? (
        <tr>
          <td className={cn(CELL, 'bg-sunken')} colSpan={5}>
            <EntryDetails taskKey={taskKey} no={heading.no} checks={checks} title={heading.title} />
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

  return (
    /*
     * Предел ширины тела записи — своё число, а не `--ui-text-max` (62ch): тот вдвое
     * уже и обрезал бы таблицы и блоки кода, которые в теле записи бывают.
     */
    <div className="flex max-w-[60rem] flex-col gap-2">
      <p className="font-semibold">
        <TaskText>{title}</TaskText>
      </p>
      <QueryState query={entry} loading="Читаем запись…" />
      {entry.data == null ? null : <EntryBody entry={entry.data} checks={checks} />}
    </div>
  );
}
