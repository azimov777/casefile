import { Link } from 'react-router';
import { taskRefHref } from '@/shared/lib';
import { Badge, Markdown, TaskText } from '@/shared/ui';
import type { Entry } from '../api/entries';
import styles from './entry-body.module.css';

interface EntryBodyProps {
  entry: Entry;
  /**
   * Обзорные проверки задачи: вердикт называет проверку номером, а человеку нужен её
   * текст. Список приходит из карточки, а не из записи — в записи его нет.
   */
  checks?: string[];
}

/**
 * Тело записи в том виде, какого требует её тип (`CONCEPT.md`, 4).
 *
 * Разбор по `type` исчерпывающий: объединение размечено, и забытый тип записи станет
 * ошибкой сборки в `assertNever`, а не пустым местом на экране в тот день, когда
 * бэкенд заведёт новый тип.
 */
export function EntryBody({ entry, checks = [] }: EntryBodyProps) {
  switch (entry.type) {
    case 'summary':
      return (
        <dl className={styles.parts}>
          <Part title="Сделано" value={entry.payload.done} />
          <Part title="Осталось" value={entry.payload.remaining} />
          <Part title="Что мешает" value={entry.payload.blockers} />
          <Part title="Следующий шаг" value={entry.payload.next_step} />
        </dl>
      );

    case 'question':
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            <span>Кому: </span>
            {entry.payload.addressees.map((name) => (
              <Badge key={name} mono>
                {name}
              </Badge>
            ))}
            {entry.payload.blocking ? <Badge tone="danger">блокирующий</Badge> : null}
          </p>
          <Text body={entry.body} />
        </div>
      );

    case 'answer':
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            Ответ на{' '}
            <Link to={taskRefHref({ key: entry.task_key, entryNo: entry.payload.question_no })}>
              {entry.task_key}#{entry.payload.question_no}
            </Link>
          </p>
          <Text body={entry.body} />
        </div>
      );

    case 'verdict': {
      const check = checks[entry.payload.check_no - 1];
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            <span>Проверка {entry.payload.check_no}</span>
            <Badge tone={entry.payload.outcome === 'passed' ? 'neutral' : 'danger'} mono>
              {entry.payload.outcome}
            </Badge>
          </p>
          {check === undefined ? null : (
            <div className={styles.check}>
              {/* Тем же markdown, что и в разделе «Обзорные проверки»: это одна и та же
                  строка, и показывать её двумя разными способами — врать глазу. */}
              <Markdown>{check}</Markdown>
            </div>
          )}
          <Text body={entry.body} />
        </div>
      );
    }

    case 'status_changed':
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            <Badge mono>{entry.payload.from}</Badge>
            <span>→</span>
            <Badge mono>{entry.payload.to}</Badge>
          </p>
          {entry.payload.reason == null || entry.payload.reason === '' ? (
            <p className={styles.absent}>Причина не названа: переход её не требовал.</p>
          ) : (
            <p>
              <TaskText>{entry.payload.reason}</TaskText>
            </p>
          )}
        </div>
      );

    case 'section_changed':
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            Поле <Badge mono>{entry.payload.field}</Badge>
          </p>
          <div className={styles.diff}>
            <Side title="Было" value={entry.payload.before} />
            <Side title="Стало" value={entry.payload.after} />
          </div>
        </div>
      );

    /*
     * Правка обвязки: то же «было / стало», что у раздела, и намеренно тем же видом.
     * Различие между ними не в том, как это выглядит, а в том, что за этим стоит:
     * задание — договор с агентом, метки — бухгалтерия. Отличать их читателю
     * помогает подпись типа записи, а не второй способ показать пару значений.
     */
    case 'field_changed':
      return (
        <div className={styles.block}>
          <p className={styles.meta}>
            Поле <Badge mono>{entry.payload.field}</Badge>
          </p>
          <div className={styles.diff}>
            <Side title="Было" value={entry.payload.before} />
            <Side title="Стало" value={entry.payload.after} />
          </div>
        </div>
      );

    case 'assignee_changed':
      return (
        <p className={styles.meta}>
          <Assignee value={entry.payload.before} />
          <span>→</span>
          <Assignee value={entry.payload.after} />
        </p>
      );

    case 'link_added':
    case 'link_removed':
      return (
        <p className={styles.meta}>
          <Badge mono>{entry.payload.kind}</Badge>
          <Link to={`/tasks/${entry.payload.other}`}>{entry.payload.other}</Link>
        </p>
      );

    // `created`, `decision`, `attempt`, `finding`, `artifact`, `note`: заголовок и тело.
    // У них общая форма и общая нагрузка — пустая.
    case 'created':
    case 'decision':
    case 'attempt':
    case 'finding':
    case 'artifact':
    case 'note':
      return (
        <div className={styles.block}>
          <Text body={entry.body} />
          <Refs refs={entry.refs ?? []} />
        </div>
      );

    default:
      return assertNever(entry);
  }
}

function Part({ title, value }: { title: string; value: string }) {
  return (
    <div className={styles.part}>
      <dt className={styles.partTitle}>{title}</dt>
      <dd className={styles.partValue}>
        <Markdown>{value}</Markdown>
      </dd>
    </div>
  );
}

/** Пустое тело — не ошибка: у служебных записей содержание лежит в нагрузке. */
function Text({ body }: { body: string }) {
  if (body.trim() === '') return <p className={styles.absent}>Тела у этой записи нет.</p>;
  return <Markdown>{body}</Markdown>;
}

/** Указатели записи: ключи задач и записей кликабельны, адреса открываются как есть. */
function Refs({ refs }: { refs: string[] }) {
  if (refs.length === 0) return null;

  return (
    <p className={styles.meta}>
      <span>Указатели: </span>
      {refs.map((ref) => (
        <span key={ref} className={styles.ref}>
          {/^https?:\/\//.test(ref) ? (
            <a href={ref} target="_blank" rel="noreferrer noopener">
              {ref}
            </a>
          ) : (
            <TaskText>{ref}</TaskText>
          )}
        </span>
      ))}
    </p>
  );
}

/** Сторона сравнения: `checks` приходит списком, остальные разделы — строкой. */
function Side({ title, value }: { title: string; value?: string | string[] | null }) {
  return (
    <div className={styles.side}>
      <span className={styles.partTitle}>{title}</span>
      {value === null || value === undefined || value === '' ? (
        <p className={styles.absent}>пусто</p>
      ) : Array.isArray(value) ? (
        <ol className={styles.list}>
          {value.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ol>
      ) : (
        <Markdown>{value}</Markdown>
      )}
    </div>
  );
}

function Assignee({ value }: { value?: string | null }) {
  if (value === null || value === undefined || value === '') {
    return <span className={styles.absent}>не назначена</span>;
  }
  return <Badge mono>{value}</Badge>;
}

function assertNever(entry: never): never {
  throw new Error(`Неизвестный тип записи: ${JSON.stringify(entry)}`);
}
