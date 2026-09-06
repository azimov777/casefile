import { useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { questionsQueryOptions, type Question } from '@/entities/entry';
import { bootstrapQueryOptions } from '@/entities/session';
import {
  AnswerForm,
  AnswerReceipt,
  useAnswering,
  withHeld,
  type Answering,
} from '@/features/answer-question';
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
  const loaded = questions.data?.pages.flatMap((page) => page.items) ?? [];

  // Вопросы, по которым отправка уже пошла, остаются на экране вместе со своим
  // подтверждением, даже когда выдача их больше не содержит: удачный ответ убирает
  // вопрос из входящей, а человеку надо увидеть, чем всё кончилось.
  const answering = useAnswering<Question>();
  const items = withHeld(loaded, answering.held, questionId);

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
        {items.map((question, at) => (
          <li key={questionId(question)}>
            <QuestionRow question={question} at={at} answering={answering} />
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

/** Тождество вопроса на всё приложение: задача и номер записи. */
function questionId(question: Question): string {
  return `${question.task_key}#${question.no}`;
}

interface QuestionRowProps {
  question: Question;
  /** Место в списке: закреплённый вопрос вернётся именно сюда. */
  at: number;
  answering: Answering<Question>;
}

/** Вопрос во входящей: откуда он, о чём и чем на него ответить. */
function QuestionRow({ question, at, answering }: QuestionRowProps) {
  const id = questionId(question);
  const [open, setOpen] = useState(false);
  const answered = answering.answerOf(id);

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

      {answered !== undefined ? (
        <AnswerReceipt
          taskKey={question.task_key}
          questionNo={question.no}
          answered={answered}
          onClose={() => {
            answering.close(id);
            setOpen(false);
          }}
        />
      ) : open || answering.isHeld(id) ? (
        <AnswerForm
          taskKey={question.task_key}
          questionNo={question.no}
          onBegin={() => answering.begin(id, question, at)}
          onFailed={() => answering.fail(id)}
          onAnswered={(result) => answering.complete(id, result)}
        />
      ) : (
        <div>
          <Button onClick={() => setOpen(true)}>Ответить</Button>
        </div>
      )}
    </article>
  );
}
