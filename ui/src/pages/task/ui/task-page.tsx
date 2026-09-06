import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { EntryBody, type Question } from '@/entities/entry';
import { TaskNav, taskPackageQueryOptions } from '@/entities/task';
import {
  AnswerForm,
  AnswerReceipt,
  useAnswering,
  withHeld,
  type Answering,
} from '@/features/answer-question';
import { ApiError } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
import { caseHref, readEntryNo } from '@/shared/lib';
import { TaskHeader } from './task-header';
import { TaskIndex } from './task-index';
import { TaskLinks } from './task-links';
import { TaskSections } from './task-sections';
import styles from './task-page.module.css';

/**
 * Карточка задачи: один запрос пакета преемника на открытие экрана
 * (`../tracker/docs/FRONTEND.md`, «Карточка задачи одним запросом»).
 *
 * Сводка и открытые вопросы приходят целиком и показываются сразу: ради них человек
 * карточку и открыл. Остальные записи — заголовками в описи, тела по клику.
 */
export function TaskPage() {
  const { key = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const pkg = useQuery(taskPackageQueryOptions(key));

  // До ранних возвратов: хук нельзя позвать условно. Держит вопросы, по которым
  // отправка началась, — они остаются на экране вместе с подтверждением, даже когда
  // перечитанный пакет их уже не содержит.
  const answering = useAnswering<Question>();

  const openAt = readEntryNo(searchParams.get('entry'));

  /**
   * Раскрытие записи в описи попадает в адрес — тем же параметром, которым запись
   * называет внешняя ссылка. Раньше клик и ссылка делали одно и то же двумя разными
   * способами: ссылка меняла адрес, клик — нет, и перезагрузка теряла раскрытое.
   *
   * `replace`, а не новая запись истории: раскрытие записи — это не «страница»,
   * и кнопка «назад» после трёх кликов по описи должна вести в список, а не
   * разворачивать их обратно по одному.
   */
  const rememberOpen = useCallback(
    (no: number | null) => {
      setSearchParams(
        (current) => {
          const updated = new URLSearchParams(current);
          if (no === null) updated.delete('entry');
          else updated.set('entry', String(no));
          return updated;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  if (pkg.error instanceof ApiError && pkg.error.code === 'task_not_found') {
    return (
      <main className={styles.screen}>
        <h1 className={styles.missing}>Задачи {key} нет</h1>
        <Callout>
          Задачи с таким ключом нет: возможно, ключ набран с опечаткой или задача из другой
          установки.
        </Callout>
        <Link to="/tasks">Вернуться к списку задач</Link>
      </main>
    );
  }

  if (pkg.data === undefined) {
    return (
      <main className={styles.screen}>
        <QueryState query={pkg} loading={`Загружаем задачу ${key}…`} />
      </main>
    );
  }

  const { task, features, transitions, summary, links, index } = pkg.data;
  const questions = withHeld(pkg.data.questions, answering.held, (question) =>
    questionId(task.key, question),
  );

  return (
    <main className={styles.screen}>
      <TaskNav taskKey={task.key} view="card" />
      <TaskHeader task={task} features={features} transitions={transitions} />

      <div className={styles.layout}>
        <section
          className={
            summary == null
              ? `${styles.block} ${styles.blockEmpty} ${styles.summary}`
              : `${styles.block} ${styles.summary}`
          }
          aria-labelledby="summary"
        >
          <h2 className={styles.title} id="summary">
            Последняя сводка
          </h2>
          {summary == null ? (
            <p className={styles.empty}>Сводки ещё нет: по этой задаче никто не отчитывался.</p>
          ) : (
            <EntryBody entry={summary} />
          )}
        </section>

        <section
          className={
            questions.length === 0
              ? `${styles.block} ${styles.blockEmpty} ${styles.questionsBlock}`
              : `${styles.block} ${styles.questionsBlock}`
          }
          aria-labelledby="questions"
        >
          <h2 className={styles.title} id="questions">
            Открытые вопросы
          </h2>
          {questions.length === 0 ? (
            <p className={styles.empty}>Вопросов без ответа нет.</p>
          ) : (
            <ul className={styles.questions}>
              {questions.map((question, at) => (
                <li key={question.no} className={styles.question}>
                  <p className={styles.questionTitle}>
                    {task.key}#{question.no} · {question.title}
                  </p>
                  <EntryBody entry={question} />
                  <QuestionAnswer
                    taskKey={task.key}
                    question={question}
                    at={at}
                    answering={answering}
                    askedFor={openAt === question.no}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={`${styles.block} ${styles.sections}`} aria-labelledby="sections">
          <h2 className={styles.title} id="sections">
            Задание
          </h2>
          <TaskSections task={task} />
        </section>

        <section className={`${styles.block} ${styles.links}`} aria-labelledby="links">
          <h2 className={styles.title} id="links">
            Связи
          </h2>
          <TaskLinks links={links} />
        </section>

        <section className={`${styles.block} ${styles.case}`} aria-labelledby="case">
          <div className={styles.blockHead}>
            <h2 className={styles.title} id="case">
              Дело
            </h2>
            {/* Переход в ленту живёт в липкой навигации сверху: здесь он был на
              1300-м пикселе прокрутки и находился только теми, кто дочитал. */}
            <Link to={caseHref(task.key)}>Открыть всё дело лентой</Link>
          </div>
          <TaskIndex
            taskKey={task.key}
            index={index}
            checks={task.checks}
            openAt={openAt}
            onOpenChange={rememberOpen}
          />
        </section>
      </div>
    </main>
  );
}

/** Номер записи из адреса. Мусор — то же самое, что его отсутствие. */
/** Тождество вопроса: задача и номер записи — то же, что во входящей. */
function questionId(taskKey: string, question: Question): string {
  return `${taskKey}#${question.no}`;
}

interface QuestionAnswerProps {
  taskKey: string;
  question: Question;
  at: number;
  answering: Answering<Question>;
  /** Адрес называет именно этот вопрос: человека звали отвечать сюда. */
  askedFor: boolean;
}

/**
 * Под вопросом стоит либо кнопка «Ответить», либо форма, либо подтверждение.
 *
 * Форма раскрывается по кнопке, а не стоит раскрытой всегда: поле в пять строк
 * с кнопками — это около 180 пикселей, то есть половина того, чем карточка платит
 * за первый экран. Человек, открывший карточку посмотреть, что происходит, платить
 * за это не должен.
 *
 * Но если адрес называет этот вопрос — человек пришёл по уведомлению или по ссылке
 * из входящей, то есть уже решив отвечать, — форма раскрыта сразу, и лишнего клика
 * между «меня спросили» и «отвечаю» нет.
 */
function QuestionAnswer({ taskKey, question, at, answering, askedFor }: QuestionAnswerProps) {
  const id = questionId(taskKey, question);
  const answered = answering.answerOf(id);
  const [open, setOpen] = useState(askedFor);

  // Ссылка на другой вопрос той же задачи меняет адрес, не перемонтируя страницу.
  useEffect(() => {
    if (askedFor) setOpen(true);
  }, [askedFor]);

  if (answered !== undefined) {
    return (
      <AnswerReceipt
        taskKey={taskKey}
        questionNo={question.no}
        answered={answered}
        onClose={() => {
          answering.close(id);
          setOpen(false);
        }}
      />
    );
  }

  if (!open && !answering.isHeld(id)) {
    return (
      <div>
        <Button onClick={() => setOpen(true)}>Ответить</Button>
      </div>
    );
  }

  return (
    <AnswerForm
      taskKey={taskKey}
      questionNo={question.no}
      onBegin={() => answering.begin(id, question, at)}
      onFailed={() => answering.fail(id)}
      onAnswered={(result) => answering.complete(id, result)}
    />
  );
}
