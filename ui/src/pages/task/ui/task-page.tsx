import { Link, useParams, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { EntryBody } from '@/entities/entry';
import { taskPackageQueryOptions } from '@/entities/task';
import { ApiError } from '@/shared/api';
import { Callout, QueryState } from '@/shared/ui';
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
  const [searchParams] = useSearchParams();
  const pkg = useQuery(taskPackageQueryOptions(key));

  const openAt = readEntryNo(searchParams.get('entry'));

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

  const { task, features, transitions, summary, questions, links, index } = pkg.data;

  return (
    <main className={styles.screen}>
      <TaskHeader task={task} features={features} transitions={transitions} />

      <section className={styles.block} aria-labelledby="summary">
        <h2 className={styles.title} id="summary">
          Последняя сводка
        </h2>
        {summary == null ? (
          <p className={styles.empty}>Сводки ещё нет: по этой задаче никто не отчитывался.</p>
        ) : (
          <EntryBody entry={summary} />
        )}
      </section>

      <section className={styles.block} aria-labelledby="questions">
        <h2 className={styles.title} id="questions">
          Открытые вопросы
        </h2>
        {questions.length === 0 ? (
          <p className={styles.empty}>Вопросов без ответа нет.</p>
        ) : (
          <ul className={styles.questions}>
            {questions.map((question) => (
              <li key={question.no} className={styles.question}>
                <p className={styles.questionTitle}>
                  {task.key}#{question.no} · {question.title}
                </p>
                <EntryBody entry={question} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.block} aria-labelledby="sections">
        <h2 className={styles.title} id="sections">
          Задание
        </h2>
        <TaskSections task={task} />
      </section>

      <section className={styles.block} aria-labelledby="links">
        <h2 className={styles.title} id="links">
          Связи
        </h2>
        <TaskLinks links={links} />
      </section>

      <section className={styles.block} aria-labelledby="case">
        <h2 className={styles.title} id="case">
          Дело
        </h2>
        <TaskIndex taskKey={task.key} index={index} checks={task.checks} openAt={openAt} />
      </section>
    </main>
  );
}

/** Номер записи из адреса. Мусор — то же самое, что его отсутствие. */
function readEntryNo(value: string | null): number | null {
  if (value === null) return null;
  const no = Number(value);
  return Number.isInteger(no) && no > 0 ? no : null;
}
