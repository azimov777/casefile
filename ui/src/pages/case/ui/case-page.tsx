import { useEffect, useMemo } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useLocation, useParams, useSearchParams } from 'react-router';
import {
  ENTRY_TYPES,
  EntryCard,
  caseFeedQueryOptions,
  type Entry,
  type EntryType,
} from '@/entities/entry';
import { taskPackageQueryOptions } from '@/entities/task';
import { ApiError } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
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
  const { hash } = useLocation();

  const types = useMemo(() => readTypes(searchParams.getAll('type')), [searchParams]);
  const params = useMemo(() => (types.length > 0 ? { types } : {}), [types]);

  const feed = useInfiniteQuery(caseFeedQueryOptions(key, params));
  // Проверки нужны вердиктам: их номера в записи есть, а текст живёт в задаче.
  const task = useQuery(taskPackageQueryOptions(key));

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const answers = groupAnswers(entries);
  const highlighted = readEntryNo(hash);

  // Браузер прокручивает к якорю сам только если элемент уже есть; лента приезжает
  // позже адреса, поэтому прокрутка повторяется, когда записи наконец пришли.
  useEffect(() => {
    if (highlighted === null || entries.length === 0) return;
    const target = document.getElementById(`entry-${highlighted}`);
    target?.scrollIntoView?.({ block: 'center' });
  }, [highlighted, entries.length]);

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
      <div className={styles.top}>
        <div>
          <p className={styles.breadcrumbs}>
            <Link to={`/tasks/${key}`}>{key}</Link>
          </p>
          <h1 className={styles.heading}>Дело {key}</h1>
        </div>
      </div>

      <CaseFilters
        selected={types}
        onChange={(next) => {
          const updated = new URLSearchParams(searchParams);
          updated.delete('type');
          for (const type of next) updated.append('type', type);
          setSearchParams(updated, { replace: true });
        }}
      />

      <QueryState
        query={feed}
        loading="Читаем дело…"
        empty={entries.length === 0 ? 'По этим типам записей в деле нет.' : undefined}
      />

      <div className={styles.feed}>
        {entries.map((entry) => {
          // Ответ живёт под своим вопросом. Отдельной записью он показывается только
          // тогда, когда вопроса рядом нет: отбор по типу `answer` или страница,
          // на которой вопрос остался выше.
          if (
            entry.type === 'answer' &&
            entries.some((other) => other.no === entry.payload.question_no)
          ) {
            return null;
          }

          return (
            <EntryCard
              key={entry.no}
              entry={entry}
              checks={task.data?.task.checks ?? []}
              highlighted={highlighted === entry.no}
            >
              {entry.type === 'question' ? (
                <AnswersUnderQuestion answers={answers.get(entry.no) ?? []} checks={[]} />
              ) : null}
            </EntryCard>
          );
        })}
      </div>

      <div className={styles.paging}>
        {feed.hasNextPage ? (
          <Button onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
            {feed.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
          </Button>
        ) : entries.length === 0 ? null : (
          <span className={styles.end}>Это всё дело: записей {entries.length}.</span>
        )}
      </div>
    </main>
  );
}

/** Ответы под вопросом: тот же вид записи, но вложенный. */
function AnswersUnderQuestion({ answers, checks }: { answers: Entry[]; checks: string[] }) {
  if (answers.length === 0) {
    return <p className={styles.waiting}>Ответа пока нет.</p>;
  }

  return (
    <div className={styles.answers}>
      {answers.map((answer) => (
        <EntryCard key={answer.no} entry={answer} checks={checks} />
      ))}
    </div>
  );
}

/** Ответы по номеру вопроса, на который отвечают. */
function groupAnswers(entries: Entry[]): Map<number, Entry[]> {
  const byQuestion = new Map<number, Entry[]>();
  for (const entry of entries) {
    if (entry.type !== 'answer') continue;
    const no = entry.payload.question_no;
    byQuestion.set(no, [...(byQuestion.get(no) ?? []), entry]);
  }
  return byQuestion;
}

/** Типы из адреса: чужое значение отбрасывается, как и в отборе задач. */
function readTypes(values: string[]): EntryType[] {
  return values.filter((value): value is EntryType => (ENTRY_TYPES as string[]).includes(value));
}

/** Номер записи из якоря `#12`. */
function readEntryNo(hash: string): number | null {
  const no = Number(hash.replace('#', ''));
  return Number.isInteger(no) && no > 0 ? no : null;
}
