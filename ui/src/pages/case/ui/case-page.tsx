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
  const answers = groupAnswers(entries);

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
              highlighted={wanted === entry.no}
            >
              {entry.type === 'question' ? (
                <AnswersUnderQuestion
                  answers={answers.get(entry.no) ?? []}
                  checks={[]}
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
 * Ответы под вопросом: тот же вид записи, но вложенный.
 *
 * Помечается именно названный ответ, а не вопрос целиком: ссылка вида `DEMO-4#9`
 * ведёт к ответу, а показан он здесь — внутри своего вопроса, и человек должен
 * увидеть, что нашёл именно то, за чем шёл.
 */
function AnswersUnderQuestion({
  answers,
  checks,
  highlighted,
}: {
  answers: Entry[];
  checks: string[];
  highlighted: number | null;
}) {
  if (answers.length === 0) {
    return <p className={styles.waiting}>Ответа пока нет.</p>;
  }

  return (
    <div className={styles.answers}>
      {answers.map((answer) => (
        <EntryCard
          key={answer.no}
          entry={answer}
          checks={checks}
          highlighted={highlighted === answer.no}
        />
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
