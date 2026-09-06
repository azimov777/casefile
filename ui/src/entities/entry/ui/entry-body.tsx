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

    // На какой вопрос отвечено — сказано заголовком, со ссылкой на сам вопрос.
    case 'answer':
      return (
        <div className={styles.block}>
          <Text body={entry.body} />
        </div>
      );

    case 'verdict': {
      const check = checks[entry.payload.check_no - 1];
      return (
        <div className={styles.block}>
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

    /*
     * Откуда и куда сказано заголовком (`entryHeadline`), и повторять это бейджами
     * значило бы занять три строки одним фактом. В теле остаётся то, чего в заголовке
     * быть не может: причина перехода — свободный текст, и он показывается целиком.
     */
    case 'status_changed':
      if (entry.payload.reason == null || entry.payload.reason === '') return null;
      return (
        <p className={styles.block}>
          <TaskText>{entry.payload.reason}</TaskText>
        </p>
      );

    case 'section_changed':
      return (
        <div className={styles.diff}>
          <Side title="Было" value={entry.payload.before} />
          <Side title="Стало" value={entry.payload.after} />
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
        <div className={styles.diff}>
          <Side title="Было" value={entry.payload.before} />
          <Side title="Стало" value={entry.payload.after} />
        </div>
      );

    // Смена исполнителя и связь целиком умещаются в заголовке: имена участников,
    // вид связи и ключ задачи — всё это он и называет. Тела у них не бывает.
    case 'assignee_changed':
    case 'link_added':
    case 'link_removed':
    case 'created':
      return null;

    /*
     * Разбор замечания. Исход и адрес работы называет заголовок; в теле — объяснение,
     * ради которого разбор и читают: что именно поправили, чего не хватило, почему не
     * будут менять. Ссылку на продолжение здесь не повторяем: она уже в заголовке, и
     * второй такой же ключ рядом читается как два разных.
     */
    case 'resolution':
      return (
        <div className={styles.block}>
          <Text body={entry.body} />
          <Refs refs={entry.refs ?? []} />
        </div>
      );

    // `decision`, `attempt`, `finding`, `artifact`, `remark`, `note`: заголовок и тело.
    // У них общая форма и общая нагрузка — пустая.
    case 'decision':
    case 'attempt':
    case 'finding':
    case 'artifact':
    case 'remark':
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

function assertNever(entry: never): never {
  throw new Error(`Неизвестный тип записи: ${JSON.stringify(entry)}`);
}
