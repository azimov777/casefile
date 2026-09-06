import { useEffect, useMemo } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import {
  ENTRY_TYPES,
  EntryCard,
  caseFeedQueryOptions,
  type Entry,
  type EntryType,
} from '@/entities/entry';
import { TaskNav, taskPackageQueryOptions } from '@/entities/task';
import { ApiError } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
import { readEntryNo } from '@/shared/lib';
import { CaseFilters } from './case-filters';
import styles from './case-page.module.css';

/**
 * Дело лентой: все записи по порядку, каждая нарисована по своему типу.
 *
 * Страницами по курсору бэкенда: дело растёт, и «прочитать всё одним запросом» однажды
 * перестанет помещаться в ответ.
 */
export function CasePage() {
  const { key = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const types = useMemo(() => readTypes(searchParams.getAll('type')), [searchParams]);
  const params = useMemo(() => (types.length > 0 ? { types } : {}), [types]);

  const feed = useInfiniteQuery(caseFeedQueryOptions(key, params));
  // Проверки нужны вердиктам: их номера в записи есть, а текст живёт в задаче.
  const task = useQuery(taskPackageQueryOptions(key));

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const replies = groupReplies(entries);

  /**
   * Запись, названная в адресе. Параметр `entry`, а не якорь `#N`: то же действие
   * человека — «покажи запись N» — называется в адресе одинаково и здесь, и в описи
   * карточки. Якорь вдобавок обрабатывал бы браузер сам, а нам нужно ещё дочитать
   * до записи страницы ленты.
   */
  const wanted = readEntryNo(searchParams.get('entry'));
  const found = entries.some((entry) => entry.no === wanted);

  /**
   * Дочитываем ленту, пока названная запись не найдётся или дело не кончится.
   *
   * Лента страничная, и запись с последней страницы иначе просто не приехала бы:
   * человек, пришедший по ссылке «см. #7», смотрел бы в ленту без седьмой записи
   * и не понимал, почему.
   */
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = feed;
  useEffect(() => {
    if (wanted === null || found) return;
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [wanted, found, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Прокрутка повторяется, когда записи наконец пришли: до этого прокручивать не к чему.
  useEffect(() => {
    if (wanted === null || !found) return;
    document.getElementById(`entry-${wanted}`)?.scrollIntoView?.({ block: 'center' });
  }, [wanted, found]);

  /**
   * Дело дочитано до конца, а записи всё нет. Причин ровно две, и человеку надо
   * сказать какая: она не попала в отбор по типу — или её в деле нет вовсе.
   * Пустого экрана без объяснения здесь не бывает.
   */
  const missing = wanted !== null && !found && !hasNextPage && !feed.isFetching;

  if (task.error instanceof ApiError && task.error.code === 'task_not_found') {
    return (
      <main className={styles.screen}>
        <h1 className={styles.heading}>Дела {key} нет</h1>
        <Callout>Задачи с таким ключом нет, а значит нет и дела.</Callout>
        <Link to="/tasks">Вернуться к списку задач</Link>
      </main>
    );
  }

  return (
    <main className={styles.screen}>
      <TaskNav taskKey={key} view="case" />

      <h1 className={styles.heading}>Дело {key}</h1>

      <CaseFilters
        selected={types}
        onChange={(next) => {
          const updated = new URLSearchParams(searchParams);
          updated.delete('type');
          for (const type of next) updated.append('type', type);
          setSearchParams(updated, { replace: true });
        }}
      />

      {missing ? (
        <Callout tone={types.length > 0 ? 'neutral' : 'danger'}>
          {types.length > 0 ? (
            <>
              Записи {key}#{wanted} не видно: она не попадает в отбор по типу.{' '}
              <button
                type="button"
                className={styles.reset}
                onClick={() => {
                  const updated = new URLSearchParams(searchParams);
                  updated.delete('type');
                  setSearchParams(updated, { replace: true });
                }}
              >
                Показать все типы
              </button>
            </>
          ) : (
            <>
              Записи {key}#{wanted} в деле нет: возможно, номер набран с опечаткой или ссылка ведёт
              в другую задачу.
            </>
          )}
        </Callout>
      ) : null}

      <QueryState
        query={feed}
        loading="Читаем дело…"
        empty={entries.length === 0 ? 'По этим типам записей в деле нет.' : undefined}
      />

      <div className={styles.feed}>
        {entries.map((entry) => {
          // Отклик живёт под тем, на что отвечает: ответ под вопросом, резолюция под
          // замечанием. Отдельной записью он показывается только тогда, когда его
          // записи рядом нет: отбор по типу или страница, на которой она осталась выше.
          const answersTo = repliesTo(entry);
          if (answersTo !== null && entries.some((other) => other.no === answersTo)) {
            return null;
          }

          return (
            <EntryCard
              key={entry.no}
              entry={entry}
              checks={task.data?.task.checks ?? []}
              highlighted={wanted === entry.no}
            >
              {entry.type === 'question' || entry.type === 'remark' ? (
                <RepliesUnder
                  replies={replies.get(entry.no) ?? []}
                  waiting={entry.type === 'question' ? 'Ответа пока нет.' : 'Разбора пока нет.'}
                  highlighted={wanted}
                />
              ) : null}
            </EntryCard>
          );
        })}
      </div>

      <div className={styles.paging}>
        {hasNextPage ? (
          <Button onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Читаем…' : 'Ещё'}
          </Button>
        ) : entries.length === 0 ? null : (
          <span className={styles.end}>Это всё дело: записей {entries.length}.</span>
        )}
      </div>
    </main>
  );
}

/**
 * Отклики под записью, на которую отвечают: тот же вид записи, но вложенный.
 *
 * Помечается именно названный отклик, а не запись целиком: ссылка вида `DEMO-4#9`
 * ведёт к ответу, а показан он здесь — внутри своего вопроса, и человек должен
 * увидеть, что нашёл именно то, за чем шёл.
 *
 * Ответ и резолюция показываются одинаково намеренно: для читателя это одно и то же
 * событие — «на это ответили», — и два разных вида различали бы то, что различать
 * не нужно. Разными остаются слова ожидания: вопрос ждёт ответа, замечание — разбора.
 */
function RepliesUnder({
  replies,
  waiting,
  highlighted,
}: {
  replies: Entry[];
  waiting: string;
  highlighted: number | null;
}) {
  if (replies.length === 0) {
    return <p className={styles.waiting}>{waiting}</p>;
  }

  return (
    <div className={styles.answers}>
      {replies.map((reply) => (
        <EntryCard
          key={reply.no}
          entry={reply}
          checks={[]}
          highlighted={highlighted === reply.no}
        />
      ))}
    </div>
  );
}

/**
 * Номер записи, под которой стоит отклик, или `null`, если запись самостоятельна.
 *
 * Одно место на обе пары контракта: `answer` → `question_no`, `resolution` →
 * `remark_no`. Третья пара, если она появится, добавляется сюда — и лента подхватит
 * её и в группировке, и в скрытии дубля.
 */
function repliesTo(entry: Entry): number | null {
  if (entry.type === 'answer') return entry.payload.question_no;
  if (entry.type === 'resolution') return entry.payload.remark_no;
  return null;
}

/** Отклики по номеру записи, на которую отвечают. */
function groupReplies(entries: Entry[]): Map<number, Entry[]> {
  const byEntry = new Map<number, Entry[]>();
  for (const entry of entries) {
    const no = repliesTo(entry);
    if (no === null) continue;
    byEntry.set(no, [...(byEntry.get(no) ?? []), entry]);
  }
  return byEntry;
}

/** Типы из адреса: чужое значение отбрасывается, как и в отборе задач. */
function readTypes(values: string[]): EntryType[] {
  return values.filter((value): value is EntryType => (ENTRY_TYPES as string[]).includes(value));
}
