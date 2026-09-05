import { useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { questionsQueryOptions, type Question } from '@/entities/entry';
import { bootstrapQueryOptions } from '@/entities/session';
import { AnswerForm } from '@/features/answer-question';
import { Badge, Button, Markdown, QueryState, RelativeTime } from '@/shared/ui';
import styles from './questions-page.module.css';

/**
 * Входящая: вопросы без ответа, адресованные текущему участнику.
 *
 * Адресата в запрос не кладём — бэкенд подставляет владельца токена сам
 * (`../tracker/docs/FRONTEND.md`): «моя входящая» не должна знать своего имени.
 */
export function QuestionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const bootstrap = useQuery(bootstrapQueryOptions());

  const queue = searchParams.get('queue') ?? '';
  const blocking = searchParams.get('blocking') === 'true';

  const params = useMemo(
    () => ({
      ...(queue === '' ? {} : { queue }),
      ...(blocking ? { blocking: true } : {}),
    }),
    [queue, blocking],
  );

  const questions = useInfiniteQuery(questionsQueryOptions(params));
  const items = questions.data?.pages.flatMap((page) => page.items) ?? [];

  function apply(changes: { queue?: string; blocking?: boolean }) {
    const updated = new URLSearchParams(searchParams);
    if (changes.queue !== undefined) {
      if (changes.queue === '') updated.delete('queue');
      else updated.set('queue', changes.queue);
    }
    if (changes.blocking !== undefined) {
      if (changes.blocking) updated.set('blocking', 'true');
      else updated.delete('blocking');
    }
    setSearchParams(updated, { replace: true });
  }

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Открытые вопросы</h1>

      <form className={styles.filters} aria-label="Отбор вопросов">
        <label className={styles.field}>
          <span className={styles.label}>Очередь</span>
          <select
            className={styles.select}
            value={queue}
            onChange={(event) => apply({ queue: event.target.value })}
          >
            <option value="">все очереди</option>
            {(bootstrap.data?.queues ?? []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.key} — {item.title}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.check}>
          <input
            type="checkbox"
            checked={blocking}
            onChange={(event) => apply({ blocking: event.target.checked })}
          />
          только блокирующие
        </label>
      </form>

      <QueryState
        query={questions}
        loading="Читаем входящую…"
        empty={items.length === 0 ? 'Вопросов без ответа нет: агенты вас не ждут.' : undefined}
      />

      <ul className={styles.list}>
        {items.map((question) => (
          <li key={`${question.task_key}#${question.no}`}>
            <QuestionRow question={question} />
          </li>
        ))}
      </ul>

      {questions.hasNextPage ? (
        <Button
          onClick={() => void questions.fetchNextPage()}
          disabled={questions.isFetchingNextPage}
        >
          {questions.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
        </Button>
      ) : null}
    </main>
  );
}

/** Вопрос во входящей: откуда он, о чём и чем на него ответить. */
function QuestionRow({ question }: { question: Question }) {
  const [answering, setAnswering] = useState(false);

  return (
    <article className={styles.question}>
      <header className={styles.head}>
        <Link className={styles.task} to={`/tasks/${question.task_key}`}>
          {question.task_key}#{question.no}
        </Link>
        {question.payload.blocking ? <Badge tone="danger">блокирующий</Badge> : null}
        <RelativeTime value={question.created_at} />
      </header>

      <h2 className={styles.title}>{question.title}</h2>

      {/* Тело без обёртки записи: адресат здесь всегда один и тот же — тот, кто смотрит
          входящую, — и повторять «Кому: owner» у каждого вопроса незачем. */}
      <Markdown>{question.body}</Markdown>

      {answering ? (
        <AnswerForm
          taskKey={question.task_key}
          questionNo={question.no}
          onAnswered={() => setAnswering(false)}
        />
      ) : (
        <div>
          <Button onClick={() => setAnswering(true)}>Ответить</Button>
        </div>
      )}
    </article>
  );
}
