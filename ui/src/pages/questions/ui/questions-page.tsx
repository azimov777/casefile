import { useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import {
  questionsQueryOptions,
  remarksQueryOptions,
  type Question,
  type Remark,
} from '@/entities/entry';
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
 * Входящая: две половины одной картины — вопросы, которых ждут от человека, и
 * замечания, которых человек ждёт от агентов.
 *
 * Адресата в запрос вопросов не кладём — бэкенд подставляет владельца токена сам
 * (`../tracker/docs/FRONTEND.md`): «моя входящая» не должна знать своего имени. У
 * замечаний адресата нет вовсе, поэтому «мои» здесь означает «мной оставленные», и
 * подпись берётся из первого кадра: страница знает, кто вошёл, а бэкенд по замечанию
 * не догадывается.
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

  const author = bootstrap.data?.participant?.name ?? '';
  const remarks = useInfiniteQuery({
    ...remarksQueryOptions({ ...(queue === '' ? {} : { queue }), author }),
    // Пока неизвестно, кто вошёл, спрашивать нечего: без подписи выдача показала бы
    // чужие замечания под заголовком «мои».
    enabled: author !== '',
  });
  const myRemarks = remarks.data?.pages.flatMap((page) => page.items) ?? [];

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
      <h1 className={styles.heading}>Входящая</h1>

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

      <section aria-labelledby="questions-section" className={styles.section}>
        <h2 className={styles.sectionTitle} id="questions-section">
          Вопросы ко мне
        </h2>

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
      </section>

      {/*
       * Вторая половина: что человек сказал агентам и на что ему ещё не ответили.
       * Здесь только чтение — замечание оставляют на карточке задачи, глядя на то,
       * о чём оно.
       */}
      <section aria-labelledby="remarks-section" className={styles.section}>
        <h2 className={styles.sectionTitle} id="remarks-section">
          Мои замечания без разбора
        </h2>

        <QueryState
          query={remarks}
          loading="Читаем замечания…"
          empty={
            myRemarks.length === 0
              ? 'Неразобранных замечаний нет: всё, что вы сказали, уже разобрали.'
              : undefined
          }
        />

        <ul className={styles.list}>
          {myRemarks.map((remark) => (
            <li key={`${remark.task_key}#${remark.no}`}>
              <RemarkRow remark={remark} />
            </li>
          ))}
        </ul>

        {remarks.hasNextPage ? (
          <Button
            onClick={() => void remarks.fetchNextPage()}
            disabled={remarks.isFetchingNextPage}
          >
            {remarks.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
          </Button>
        ) : null}
      </section>
    </main>
  );
}

/** Замечание во входящей: к какой задаче, когда оставлено и о чём. */
function RemarkRow({ remark }: { remark: Remark }) {
  return (
    <article className={styles.remark}>
      <header className={styles.head}>
        <Link className={styles.task} to={`/tasks/${remark.task_key}`}>
          {remark.task_key}#{remark.no}
        </Link>
        <Badge tone="attention">ждёт разбора</Badge>
        <RelativeTime value={remark.created_at} />
      </header>

      <h3 className={styles.title}>{remark.title}</h3>
      <Markdown>{remark.body}</Markdown>
    </article>
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
