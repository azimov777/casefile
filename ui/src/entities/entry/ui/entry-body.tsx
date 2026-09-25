import { cva } from 'class-variance-authority';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Markdown, TaskText } from '@/shared/ui';
import type { Entry } from '../api/entries';

interface EntryBodyProps {
  entry: Entry;
  /**
   * Обзорные проверки задачи: вердикт называет проверку номером, а человеку нужен её
   * текст. Список приходит из карточки, а не из записи — в записи его нет.
   */
  checks?: string[];
}

/** Тело записи, у которой оно одно: текст, а под ним указатели. */
const BLOCK = 'flex flex-col gap-2';

/** Служебная приписка к телу: кому задан вопрос, куда ведут указатели. */
const META = 'flex flex-wrap items-center gap-2 text-meta text-muted';

/**
 * Надстрочная подпись части. Набрана заглавными, поэтому с разрядкой: без неё буквы
 * слипаются. Цвет подписи задаёт место — он называет либо уровень, либо исход стороны.
 */
const PART_TITLE = 'text-label font-semibold tracking-caps uppercase';

/** Идентификаторы записи: ключи и адреса в указателях. */
const REF = 'font-mono text-meta';

/**
 * Тело записи в том виде, какого требует её тип (`CONCEPT.md`, 4).
 *
 * Разбор по `type` исчерпывающий: объединение размечено, и забытый тип записи станет
 * ошибкой сборки в `assertNever`, а не пустым местом на экране в тот день, когда
 * бэкенд заведёт новый тип.
 */
export function EntryBody({ entry, checks = [] }: EntryBodyProps) {
  const { t } = useTranslation('ui');

  switch (entry.type) {
    case 'summary':
      return (
        /*
         * Подписи частей сводки стоят над текстом, а не колонкой слева (решение Д8).
         * Колонка занимала не меньше 8rem: на узком экране текст ужимался до 190 px,
         * и сводка из четырёх абзацев растягивалась за 1000 px в высоту. Надстрочная
         * метка отдаёт тексту всю ширину в обеих раскладках.
         */
        <dl className="grid gap-3">
          <Part title={t('entry.summary.done')} value={entry.payload.done} />
          <Part title={t('entry.summary.remaining')} value={entry.payload.remaining} />
          <Part title={t('entry.summary.blockers')} value={entry.payload.blockers} />
          <Part title={t('entry.summary.nextStep')} value={entry.payload.next_step} />
          {/*
           * Пятая часть — только у закрывающей сводки (TRK-78): у промежуточных и у всех
           * дел, закрытых до её появления, ключа в нагрузке нет вовсе. `Part` в этом
           * случае не рисуется совсем, а не пустым блоком — отсутствие значения здесь
           * обычный случай, а не пробел, который надо чем-то заполнить.
           */}
          {entry.payload.unmeasured == null || entry.payload.unmeasured === '' ? null : (
            <Part title={t('entry.summary.unmeasured')} value={entry.payload.unmeasured} />
          )}
        </dl>
      );

    case 'question':
      return (
        <div className={BLOCK}>
          <p className={META}>
            <span>{t('entry.addressees')} </span>
            {entry.payload.addressees.map((name) => (
              <Badge key={name} mono>
                {name}
              </Badge>
            ))}
            {entry.payload.blocking ? <Badge tone="danger">{t('entry.blocking')}</Badge> : null}
          </p>
          <Text body={entry.body} />
        </div>
      );

    // На какой вопрос отвечено — сказано заголовком, со ссылкой на сам вопрос.
    case 'answer':
      return (
        <div className={BLOCK}>
          <Text body={entry.body} />
        </div>
      );

    case 'verdict': {
      const check = checks[entry.payload.check_no - 1];
      return (
        <div className={BLOCK}>
          {check === undefined ? null : (
            <div className="border-l-2 border-line-strong pl-3">
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
      /*
       * Не `BLOCK` (`flex flex-col`): здесь единственный ребёнок — строка текста, а не
       * несколько блоков, которые надо развести отступом. `TaskText` разбирает причину
       * на текстовые узлы и ссылки `KEY#N` и отдаёт их фрагментом без обёртки; во
       * флекс-колонке каждый узел — текст до ссылки, сама ссылка, текст после —
       * становится своим флекс-элементом и переносится строкой, и «(», ссылка «)»
       * причины вида «текст (KEY#N)» вставали друг под другом (UI-159). Обычный `<p>`
       * оставляет их строчным потоком, как в абзаце.
       */
      return (
        <p className="wrap-anywhere">
          <TaskText>{entry.payload.reason}</TaskText>
        </p>
      );

    case 'section_changed':
      return (
        <Diff>
          <Side title={t('entry.was')} value={entry.payload.before} tone="was" />
          <Side title={t('entry.now')} value={entry.payload.after} tone="now" />
        </Diff>
      );

    /*
     * Правка обвязки: то же «было / стало», что у раздела, и намеренно тем же видом.
     * Различие между ними не в том, как это выглядит, а в том, что за этим стоит:
     * задание — договор с агентом, метки — бухгалтерия. Отличать их читателю
     * помогает подпись типа записи, а не второй способ показать пару значений.
     */
    case 'field_changed':
      return (
        <Diff>
          <Side title={t('entry.was')} value={entry.payload.before} tone="was" identifier />
          <Side title={t('entry.now')} value={entry.payload.after} tone="now" identifier />
        </Diff>
      );

    /*
     * Атрибут проекта (TRK-157): значение — то же «было / стало», что у правки поля, но
     * свободным текстом, а не идентификатором; у заведения стороны «было» нет, у снятия
     * нет «стало». Причина — строкой под парой, как у перехода.
     */
    case 'attribute_created':
    case 'attribute_changed':
    case 'attribute_removed':
      return (
        <div className={BLOCK}>
          <Diff>
            {entry.type !== 'attribute_created' && (
              <Side title={t('entry.was')} value={entry.payload.before} tone="was" />
            )}
            {entry.type !== 'attribute_removed' && (
              <Side title={t('entry.now')} value={entry.payload.after} tone="now" />
            )}
          </Diff>
          {entry.payload.reason == null || entry.payload.reason === '' ? null : (
            <p className="wrap-anywhere">
              <TaskText>{entry.payload.reason}</TaskText>
            </p>
          )}
        </div>
      );

    // Архив проекта (TRK-159) и перенос задачи (TRK-172): заголовок называет действие —
    // у переноса и оба ключа, — тело причину.
    case 'archived':
    case 'restored':
    case 'moved':
      return (
        <p className="wrap-anywhere">
          <TaskText>{entry.payload.reason}</TaskText>
        </p>
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
        <div className={BLOCK}>
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
        <div className={BLOCK}>
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
    <div className="grid gap-1">
      <dt className={`${PART_TITLE} text-faint`}>{title}</dt>
      <dd>
        <Markdown>{value}</Markdown>
      </dd>
    </div>
  );
}

/**
 * Пара сторон сравнения. Складывается в одну колонку на точке `compare` (48rem):
 * порог у неё свой, не общий с `fold`, — на `fold` сторона получила бы 195 px ширины,
 * а текст в ней 171 px, то есть ровно то, от чего уходило решение Д8 (UI-48#6).
 */
function Diff({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 compare:grid-cols-2">{children}</div>;
}

/** Пустое тело — не ошибка: у служебных записей содержание лежит в нагрузке. */
function Text({ body }: { body: string }) {
  const { t } = useTranslation('ui');
  if (body.trim() === '') return <p className="text-muted italic">{t('entry.noBody')}</p>;
  return <Markdown>{body}</Markdown>;
}

/** Указатели записи: ключи задач и записей кликабельны, адреса открываются как есть. */
function Refs({ refs }: { refs: string[] }) {
  const { t } = useTranslation('ui');
  if (refs.length === 0) return null;

  return (
    <p className={META}>
      <span>{t('entry.refs')} </span>
      {refs.map((ref) => (
        <span key={ref} className={REF}>
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

/*
 * Стороны сравнения красятся тоном исхода (решение Д14): было — снятое, стало —
 * удачное. Тон берётся из тех же шести, седьмого ради сравнения не заводится.
 * Подпись при этом остаётся: цвет никогда не единственный носитель смысла.
 *
 * `min-w-0` держит сторону в своей колонке: без него элемент сетки не сжимается
 * меньше своего содержимого, и длинная строка `<pre>` внутри markdown растянула бы
 * колонку за край карточки.
 */
const side = cva('flex min-w-0 flex-col gap-1 rounded-mark border px-3 py-2', {
  variants: {
    tone: {
      was: 'border-dashed border-dropped-line bg-transparent',
      now: 'border-positive-line bg-positive-soft',
    },
  },
});

const sideTitle = cva(PART_TITLE, {
  variants: { tone: { was: 'text-dropped', now: 'text-positive' } },
});

/**
 * Сторона сравнения: `checks` приходит списком, остальные разделы — строкой.
 *
 * `identifier` — у правки обвязки (`field_changed`, сегодня только `priority`):
 * её значения не текст агента, а значения контракта (`normal`, `high`), и стоят они
 * тем же моноширинным идентификатором, что приоритет в карточке, а не абзацем
 * прозы — на русском экране абзац `high` читался бы непереведённой подписью (UI-140).
 */
function Side({
  title,
  value,
  tone,
  identifier = false,
}: {
  title: string;
  value?: string | string[] | null;
  tone: 'was' | 'now';
  identifier?: boolean;
}) {
  const { t } = useTranslation('ui');

  return (
    // Исход стороны назван разметкой, а не только цветом: проверка спрашивает, что
    // сторон две и они разного тона, а искать их по имени утилиты значило бы
    // проверять цвет вместо того, что он значит.
    <div data-side={tone} className={side({ tone })}>
      <span className={sideTitle({ tone })}>{title}</span>
      {value === null || value === undefined || value === '' ? (
        <p className="text-muted italic">{t('entry.emptyValue')}</p>
      ) : identifier && !Array.isArray(value) ? (
        <p>
          <code className={REF}>{value}</code>
        </p>
      ) : Array.isArray(value) ? (
        <ol className="pl-6">
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
  throw new Error(`Unknown entry type: ${JSON.stringify(entry)}`);
}
