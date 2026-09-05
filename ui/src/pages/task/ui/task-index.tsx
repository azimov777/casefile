import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AuthorName, EntryBody, entryQueryOptions, type EntryHeading } from '@/entities/entry';
import { Badge, QueryState, RelativeTime, TaskText } from '@/shared/ui';
import styles from './task-index.module.css';

interface TaskIndexProps {
  taskKey: string;
  index: EntryHeading[];
  /** Обзорные проверки задачи: вердикту нужен текст его проверки. */
  checks: string[];
  /** Номер записи из адреса: ссылка `TRK-42#12` открывает карточку уже раскрытой. */
  openAt: number | null;
}

/**
 * Опись дела: заголовок каждой записи, тело — по клику.
 *
 * Так дело и задумано читать (`CONCEPT.md`, 4): полное дело весит столько, что карточка
 * открывалась бы секундами, а нужны из него обычно две-три записи.
 */
export function TaskIndex({ taskKey, index, checks, openAt }: TaskIndexProps) {
  // Раскрытое живёт в состоянии страницы, а не в адресе: адрес называет запись, ради
  // которой человек пришёл по ссылке, и замусоривать его каждым кликом незачем.
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(openAt === null ? [] : [openAt]),
  );

  // Ссылка `TRK-42#12` внутри той же карточки меняет адрес, не перемонтируя страницу,
  // поэтому раскрытие следит за параметром, а не только за первым рендером.
  useEffect(() => {
    if (openAt === null) return;
    setExpanded((previous) => (previous.has(openAt) ? previous : new Set(previous).add(openAt)));
  }, [openAt]);

  const toggle = useCallback((no: number) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (!next.delete(no)) next.add(no);
      return next;
    });
  }, []);

  if (index.length === 0) return <p className={styles.empty}>Дело пусто: записей ещё нет.</p>;

  return (
    <div className={styles.scroller}>
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
          <Badge mono>{heading.type}</Badge>
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
            {heading.title}
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
