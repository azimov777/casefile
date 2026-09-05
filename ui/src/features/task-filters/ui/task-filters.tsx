import { useEffect, useId, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { bootstrapQueryOptions } from '@/entities/session';
import { TASK_PRIORITIES, TASK_STATUSES } from '@/entities/task';
import { Button } from '@/shared/ui';
import { TASK_SORTS, splitTags, type TaskFilters } from '../model/filters';
import { caretLine, type QueryProblem } from '../model/query-problem';
import styles from './task-filters.module.css';

interface TaskFiltersFormProps {
  filters: TaskFilters;
  onApply: (changes: Partial<TaskFilters>) => void;
  onReset: () => void;
  /** Отказ разбора отбора: показывается под полем запроса, а не поверх таблицы. */
  problem: QueryProblem | null;
}

/** Текстовые поля до отправки: они применяются по «Применить», а не по каждой букве. */
interface Draft {
  assignee: string;
  tags: string;
  text: string;
  query: string;
}

export function TaskFiltersForm({ filters, onApply, onReset, problem }: TaskFiltersFormProps) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const queues = bootstrap.data?.queues ?? [];

  // На доске статус — это столбец, а порядок задан её устройством. Показывать поля,
  // которые сейчас ни на что не влияют, значит врать: они спрятаны, но из адреса
  // не стёрты и вернутся вместе с таблицей.
  const board = filters.view === 'board';

  const [draft, setDraft] = useState(() => toDraft(filters));
  const problemId = useId();

  // Отбор меняется и мимо формы: «сбросить», кнопка «назад», открытая ссылка.
  useEffect(() => {
    setDraft(toDraft(filters));
  }, [filters]);

  /**
   * Любое изменение отбора отправляет и напечатанное, но ещё не применённое.
   * Иначе флажок, поставленный после набора текста, молча стирал бы этот текст:
   * в адрес он не попал, а форма перечиталась бы из адреса.
   */
  function applyWith(changes: Partial<TaskFilters>) {
    onApply({
      assignee: draft.assignee,
      tags: splitTags(draft.tags),
      text: draft.text,
      query: draft.query,
      ...changes,
    });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    applyWith({});
  }

  function toggle<T extends string>(list: T[], value: T, on: boolean): T[] {
    return on ? [...list, value] : list.filter((item) => item !== value);
  }

  return (
    <form className={styles.panel} aria-label="Отбор задач" onSubmit={submit}>
      <div className={styles.line}>
        <label className={styles.field}>
          <span className={styles.label}>Очередь</span>
          <select
            className={styles.select}
            value={filters.queue}
            onChange={(event) => applyWith({ queue: event.target.value })}
          >
            <option value="">все очереди</option>
            {queues.map((queue) => (
              <option key={queue.key} value={queue.key}>
                {queue.key} — {queue.title}
              </option>
            ))}
          </select>
        </label>

        {board ? null : (
          <label className={styles.field}>
            <span className={styles.label}>Сортировка</span>
            <select
              className={styles.select}
              value={filters.sort}
              onChange={(event) => applyWith({ sort: event.target.value })}
            >
              {TASK_SORTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className={styles.line}>
        {board ? (
          <p className={styles.note}>На доске показаны все статусы: каждый своим столбцом.</p>
        ) : (
          <fieldset className={styles.group}>
            <legend className={styles.label}>Статус</legend>
            {TASK_STATUSES.map((status) => (
              <label key={status} className={styles.check}>
                <input
                  type="checkbox"
                  checked={filters.status.includes(status)}
                  onChange={(event) =>
                    applyWith({ status: toggle(filters.status, status, event.target.checked) })
                  }
                />
                <code>{status}</code>
              </label>
            ))}
          </fieldset>
        )}

        <fieldset className={styles.group}>
          <legend className={styles.label}>Приоритет</legend>
          {TASK_PRIORITIES.map((priority) => (
            <label key={priority} className={styles.check}>
              <input
                type="checkbox"
                checked={filters.priority.includes(priority)}
                onChange={(event) =>
                  applyWith({
                    priority: toggle(filters.priority, priority, event.target.checked),
                  })
                }
              />
              <code>{priority}</code>
            </label>
          ))}
        </fieldset>
      </div>

      <div className={styles.line}>
        <label className={styles.field}>
          <span className={styles.label}>Исполнитель</span>
          <input
            className={styles.input}
            value={draft.assignee}
            onChange={(event) => setDraft({ ...draft, assignee: event.target.value })}
            placeholder="имя целиком"
            autoComplete="off"
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Теги</span>
          <input
            className={styles.input}
            value={draft.tags}
            onChange={(event) => setDraft({ ...draft, tags: event.target.value })}
            placeholder="через запятую"
            autoComplete="off"
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Текст</span>
          <input
            className={styles.input}
            value={draft.text}
            onChange={(event) => setDraft({ ...draft, text: event.target.value })}
            placeholder="в названии или описании"
            autoComplete="off"
          />
        </label>

        <label className={styles.check}>
          <input
            type="checkbox"
            checked={filters.blocked}
            onChange={(event) => applyWith({ blocked: event.target.checked })}
          />
          заблокирована
        </label>

        <label className={styles.check}>
          <input
            type="checkbox"
            checked={filters.withQuestions}
            onChange={(event) => applyWith({ withQuestions: event.target.checked })}
          />
          есть открытые вопросы
        </label>
      </div>

      <div className={styles.line}>
        <label className={`${styles.field} ${styles.wide}`}>
          <span className={styles.label}>Запрос на языке бэкенда</span>
          <input
            className={styles.input}
            value={draft.query}
            onChange={(event) => setDraft({ ...draft, query: event.target.value })}
            placeholder="queue: DEMO and status: open and blocked: false"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={problem !== null}
            aria-describedby={problem === null ? undefined : problemId}
          />
        </label>
        <Button type="submit">Применить</Button>
        <Button tone="quiet" onClick={onReset}>
          Сбросить
        </Button>
      </div>

      {problem === null ? null : <QueryProblemHint id={problemId} problem={problem} />}
    </form>
  );
}

/**
 * Что сказал бэкенд о негодном отборе: фраза по коду, место в строке и допустимое.
 * Позиция называется и словами, и указателем: указатель виден глазами, слова
 * читаются программой чтения с экрана.
 */
function QueryProblemHint({ id, problem }: { id: string; problem: QueryProblem }) {
  return (
    <div className={styles.problem} id={id} role="alert">
      <p>
        {problem.message}
        {problem.position === null ? null : ` Ошибка в символе ${problem.position + 1}.`}
      </p>

      {problem.position === null || problem.query === '' ? null : (
        <pre className={styles.caret} aria-hidden="true">
          {`${problem.query}\n${caretLine(problem.query, problem.position)}`}
        </pre>
      )}

      {problem.allowed.length === 0 ? null : <p>Допустимо: {problem.allowed.join(', ')}</p>}
    </div>
  );
}

function toDraft(filters: TaskFilters): Draft {
  return {
    assignee: filters.assignee,
    tags: filters.tags.join(', '),
    text: filters.text,
    query: filters.query,
  };
}
