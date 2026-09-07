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
import { Button, QueryState, RelativeTime, TaskText } from '@/shared/ui';
import styles from './task-index.module.css';

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

  if (index.length === 0) return <p className={styles.empty}>Дело пусто: записей ещё нет.</p>;

  // Последняя запись всего дела: опись приходит пакетом задачи целиком, поэтому это
  // именно последняя, а не последняя из подгруженных (`../tracker/docs/FRONTEND.md`).
  const lastNo = index[index.length - 1]?.no ?? null;

  return (
    <div className={styles.section}>
      {index.length > LONG_INDEX && lastNo !== null ? (
        /*
         * Два прыжка по описи: к свежей записи и обратно к началу. Свежая раскрывается
         * и читается точечно — своим запросом на свой номер, а не чтением всего дела
         * до неё. Прыгает человек, а не экран: живой поток опись не прокручивает.
         */
        <div className={styles.actions}>
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

      <div className={styles.scroller} ref={scroller}>
        <table className={styles.table}>
          <caption className={styles.caption}>Записей в деле: {index.length}</caption>
          <thead>
            <tr>
              <th scope="col">№</th>
              <th scope="col">Тип</th>
              <th scope="col">Автор</th>
              <th scope="col">Когда</th>
              <th scope="col">Заголовок</th>
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
  const headline = entryHeadline(heading.type, heading.facts, taskKey);

  useEffect(() => {
    if (!scrollTo) return;
    // В jsdom этого метода нет: страничный тест проверяет раскрытие, а не прокрутку.
    row.current?.scrollIntoView?.({ block: 'center' });
  }, [scrollTo]);

  return (
    <>
      <tr ref={row} className={open ? styles.opened : undefined}>
        <th scope="row" className={styles.no}>
          {heading.no}
        </th>
        <td>
          {/* Род записи знаком (решение Д10): в описи их по двадцать подряд, и
              `verdict` от `section_changed` иначе отличается только чтением слова. */}
          <EntryKind type={heading.type} />
        </td>
        <td>
          <AuthorName author={heading.author} />
        </td>
        <td className={styles.when}>
          <RelativeTime value={heading.created_at} />
        </td>
        <td>
          <button
            type="button"
            className={styles.title}
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
        <tr className={styles.bodyRow}>
          <td colSpan={5}>
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
    <div className={styles.body}>
      <p className={styles.bodyTitle}>
        <TaskText>{title}</TaskText>
      </p>
      <QueryState query={entry} loading="Читаем запись…" />
      {entry.data == null ? null : <EntryBody entry={entry.data} checks={checks} />}
    </div>
  );
}
