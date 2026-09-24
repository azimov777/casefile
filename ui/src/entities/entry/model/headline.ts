import type { TFunction } from 'i18next';
import type { components } from '@/shared/api';
import type { Entry, EntryHeading } from '../api/entries';

/**
 * Факты записи из описи дела: то, чем её называют, не читая тела.
 *
 * Размеченное по `type` объединение десяти форм, а не объект из шестнадцати полей с
 * `null` в пятнадцати (`docs/FRONTEND.md`, «Строку описи не надо
 * разбирать»). Состав полей сужается сам — `switch (facts.type)`, — и внешний тип
 * записи для этого не нужен.
 */
export type EntryFacts = components['schemas']['EntryFactsRead'];

/**
 * Отдельные формы объединения: ими индексируются типы значений там, где нагрузку
 * записи приходится приводить к факту. Само объединение индексировать нечем — общих
 * ключей у форм нет, кроме разметки.
 */
type StatusChangedFacts = components['schemas']['StatusChangedFactsRead'];
type SectionChangedFacts = components['schemas']['SectionChangedFactsRead'];
type FieldChangedFacts = components['schemas']['FieldChangedFactsRead'];
type LinkFacts = components['schemas']['LinkFactsRead'];

/** Чем разобрано замечание: значение из контракта, показывается словами. */
export type RemarkOutcome = components['schemas']['RemarkOutcome'];

/**
 * Часть собранной строки: либо слова, либо идентификатор контракта, либо ссылка.
 *
 * Идентификаторы (`open`, `relates`, `goal`, ключи задач) не переводятся и стоят
 * моноширинными — так их видит и агент, и они же лежат в адресах (`CONCEPT.md`, 6).
 * Переводится только фраза вокруг них.
 */
export type HeadlinePart =
  | { kind: 'words'; text: string }
  | { kind: 'id'; text: string }
  | { kind: 'task'; key: string }
  | { kind: 'entry'; key: string; no: number };

/**
 * Чей заголовок у записи.
 *
 * `built` — собран здесь из типа и фактов: у служебных записей, у `answer` и `verdict`
 * бэкенд строит `title` сам и по-английски («Status changed: backlog -> open»), и
 * показывать эту строку в русском интерфейсе незачем. Разбирать её регуляркой — тем
 * более: формат никто не обещал.
 *
 * `author` — написан автором и осмыслен: его и показываем.
 *
 * `derived` — выведен трекером из тела записи: у `summary` это первая строка
 * «следующего шага», и в ленте она стояла бы жирным над тем же текстом.
 */
export type Headline =
  { kind: 'built'; parts: HeadlinePart[] } | { kind: 'author' } | { kind: 'derived' };

/**
 * Подписи типа записи и исхода разбора живут в словаре языков
 * (`shared/i18n`, `ui.entry.type` и `ui.entry.remarkOutcome`), а полноту их наборов
 * держит там же `satisfies Record<EntryType, string>`: тип, добавленный в контракт,
 * роняет сборку словаря, а не остаётся без подписи на экране.
 */

const words = (text: string): HeadlinePart => ({ kind: 'words', text });
const id = (text: string): HeadlinePart => ({ kind: 'id', text });

/**
 * Заголовок записи по её фактам.
 *
 * Строится из структурных полей, а не из готового `title`: тот приходит по-английски
 * и его формат — служебный слой бэкенда, а не контракт для клиента.
 *
 * Тип записи отдельным доводом не нужен: он лежит в самих фактах и разметкой их
 * сужает. Внешний `type` этого не умел — TypeScript про его связь с плоским объектом
 * не знал, и каждое поле приходилось проверять на `null` заново.
 *
 * `taskKey` — ключ владельца дела: задачи или проекта. Он нужен ответу и разбору
 * замечания (они ссылаются на запись в той же задаче, а в фактах описи лежит только её
 * номер) и заведению — «задача заведена» или «проект заведён».
 *
 * Подписи приходят функцией перевода, а не берутся из экземпляра `i18next`: заголовок
 * собирают компоненты, и они же обязаны быть подписаны на смену языка. Пространство
 * одно — `ui`: заголовок записи одинаков в описи карточки и в ленте дела.
 */
export function entryHeadline(facts: EntryFacts, taskKey: string, t: TFunction<'ui'>): Headline {
  switch (facts.type) {
    // `created` подшивается и в дело проекта (TRK-156). Чьё это дело, видно по ключу
    // владельца: дефис есть только в ключе задачи (`../docs/CONCEPT.md`, 3.4).
    case 'created':
      return {
        kind: 'built',
        parts: [
          words(
            taskKey.includes('-')
              ? t('entry.headline.created')
              : t('entry.headline.projectCreated'),
          ),
        ],
      };

    case 'status_changed':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.status')),
          ...pair(facts.from_status, facts.to_status, t),
          // Причина — свободный текст, и её место в теле записи. Здесь только то,
          // искать её там или нет.
          ...(facts.has_reason === true ? [words(t('entry.headline.withReason'))] : []),
        ],
      };

    /*
     * Номер проверки (`check_no`) в фактах правки раздела есть, но в строке не
     * называется: это перевод на другую форму данных, а не редизайн строки описи
     * (UI-64#6).
     */
    case 'section_changed':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.sectionEdited')),
          ...(facts.field == null ? [] : [id(facts.field)]),
        ],
      };

    case 'field_changed':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.fieldEdited')),
          ...(facts.field == null ? [] : [id(facts.field)]),
        ],
      };

    case 'assignee_changed':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.assignee')),
          ...pair(facts.assignee_from, facts.assignee_to, t),
        ],
      };

    case 'link_added':
    case 'link_removed':
      return {
        kind: 'built',
        parts: [
          words(
            facts.type === 'link_added'
              ? t('entry.headline.linkAdded')
              : t('entry.headline.linkRemoved'),
          ),
          ...(facts.link_kind == null ? [] : [id(facts.link_kind)]),
          /*
           * Вид назван от лица этой задачи: `parent DEMO-9` в деле программы значит
           * «эта задача — родитель DEMO-9». Фразой идентификатор читается наоборот
           * («родитель — DEMO-9»), поэтому у иерархии роль второй задачи сказана
           * словами перед её ключом (UI-166). Идентификатор остаётся как есть.
           */
          ...(facts.link_kind === 'parent' || facts.link_kind === 'child'
            ? [words(t(`entry.headline.linkRole.${facts.link_kind}`))]
            : []),
          ...(facts.other_key == null ? [] : [{ kind: 'task' as const, key: facts.other_key }]),
        ],
      };

    // Атрибут проекта (TRK-157): что случилось и имя. Значения и причина — в теле
    // записи: это свободный текст, а в описи от записи остаётся одна строка.
    case 'attribute_created':
    case 'attribute_changed':
    case 'attribute_removed':
      return {
        kind: 'built',
        parts: [
          words(
            facts.type === 'attribute_created'
              ? t('entry.headline.attributeCreated')
              : facts.type === 'attribute_changed'
                ? t('entry.headline.attributeChanged')
                : t('entry.headline.attributeRemoved'),
          ),
          ...(facts.name == null ? [] : [id(facts.name)]),
        ],
      };

    case 'answer':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.answerTo')),
          ...(facts.question_no == null
            ? []
            : [{ kind: 'entry' as const, key: taskKey, no: facts.question_no }]),
        ],
      };

    case 'verdict':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.check', { no: facts.check_no ?? '?' })),
          ...(facts.outcome == null ? [] : [id(facts.outcome)]),
        ],
      };

    /*
     * Разбор замечания: на что отвечено, чем и куда ушла работа. Исход — словами, в
     * отличие от вердикта: вердикт читает агент, а резолюцию — человек, оставивший
     * замечание. Ключ задачи-продолжения остаётся ссылкой: по нему переходят.
     */
    case 'resolution':
      return {
        kind: 'built',
        parts: [
          words(t('entry.headline.resolution')),
          ...(facts.remark_no == null
            ? []
            : [{ kind: 'entry' as const, key: taskKey, no: facts.remark_no }]),
          ...(facts.outcome == null
            ? []
            : [
                words(
                  t('entry.headline.resolutionOutcome', {
                    outcome: t(`entry.remarkOutcome.${facts.outcome}`),
                  }),
                ),
              ]),
          ...(facts.continuation_key == null
            ? []
            : [words('→'), { kind: 'task' as const, key: facts.continuation_key }]),
        ],
      };

    // Заголовок сводки — первая строка «следующего шага»: в ленте он стоял бы жирным
    // над тем же текстом, а в описи это единственное, чем сводку назвать.
    case 'summary':
      return { kind: 'derived' };

    // Вопрос, решение, попытка, находка, артефакт, замечание, заметка: заголовок
    // пишет автор. У вопроса факты есть (`addressees`, `blocking`), но они уже
    // показаны бейджами карточки, а не заголовком.
    case 'question':
    case 'decision':
    case 'attempt':
    case 'finding':
    case 'artifact':
    case 'remark':
    case 'note':
      return { kind: 'author' };

    /*
     * Ветка недостижима, и это проверяет компилятор: разметка перебрана целиком, так
     * что здесь `facts` сузился до `never`. Форма, добавленная в контракт, уронит
     * сборку тут — а не покажется на экране «неизвестным типом».
     */
    default: {
      const unreachable: never = facts;
      return unreachable;
    }
  }
}

/** Пара «было → стало». Отсутствие значения называется словом, а не пустотой. */
function pair(
  before: string | null | undefined,
  after: string | null | undefined,
  t: TFunction<'ui'>,
) {
  return [
    before == null ? words(t('entry.headline.none')) : id(before),
    words('→'),
    after == null ? words(t('entry.headline.cleared')) : id(after),
  ];
}

/**
 * Факты записи ленты: там приходит `payload` целиком, а описи бэкенд отдаёт уже
 * вырезанное. Приведение здесь, чтобы строку собирало одно место для обоих.
 *
 * Каждая ветка называет разметку: без неё это не факты, а объект, который нечем
 * истолковать. Ветка по умолчанию отдаёт одну разметку — у записей агента и человека
 * фактов нет вовсе, и форма контракта говорит ровно это.
 *
 * Значения перечислений приходится приводить: в нагрузке записи контракт объявляет
 * статус, имя поля и вид связи строками, а в фактах описи — перечислениями. Значение
 * то же самое и приходит из одной строки базы; расхождение — в ширине типа на стороне
 * бэкенда, и выдумывать здесь свой список значений (вместо сгенерированного) было бы
 * хуже: он разошёлся бы с контрактом молча.
 */
export function factsOfEntry(entry: Entry): EntryFacts {
  switch (entry.type) {
    case 'status_changed':
      return {
        type: 'status_changed',
        from_status: entry.payload.from as StatusChangedFacts['from_status'],
        to_status: entry.payload.to as StatusChangedFacts['to_status'],
        has_reason: entry.payload.reason != null && entry.payload.reason !== '',
      };
    case 'section_changed':
      return {
        type: 'section_changed',
        field: entry.payload.field as SectionChangedFacts['field'],
        check_no: entry.payload.check_no,
      };
    case 'field_changed':
      return {
        type: 'field_changed',
        field: entry.payload.field as FieldChangedFacts['field'],
      };
    case 'assignee_changed':
      return {
        type: 'assignee_changed',
        assignee_from: entry.payload.before,
        assignee_to: entry.payload.after,
      };
    case 'link_added':
    case 'link_removed':
      return {
        type: entry.type,
        link_kind: entry.payload.kind as LinkFacts['link_kind'],
        other_key: entry.payload.other,
      };
    case 'question':
      return {
        type: 'question',
        addressees: entry.payload.addressees,
        blocking: entry.payload.blocking,
      };
    case 'answer':
      return { type: 'answer', question_no: entry.payload.question_no };
    case 'verdict':
      /*
       * `outdated` в нагрузке записи нет: он не хранится, а вычисляется при чтении
       * дела — в ленте его просто неоткуда взять, и поле остаётся незаполненным.
       */
      return { type: 'verdict', check_no: entry.payload.check_no, outcome: entry.payload.outcome };
    case 'resolution':
      return {
        type: 'resolution',
        remark_no: entry.payload.remark_no,
        outcome: entry.payload.outcome,
        continuation_key: entry.payload.task,
      };
    case 'attribute_created':
    case 'attribute_changed':
    case 'attribute_removed':
      return { type: entry.type, name: entry.payload.name };
    default:
      return { type: entry.type };
  }
}

/**
 * Строка описи из записи целиком: то же, что бэкенд отдаёт описью в пакете задачи.
 *
 * У дела проекта описи в ответе нет — `GET /projects/{key}/entries` отдаёт записи с
 * телами, — и строка собирается из полученного: поля записи как есть, факты — тем же
 * `factsOfEntry`, что у ленты. Это проекция ответа, а не вычисление признака: ничего,
 * чего нет в записи, строка не несёт (UI-174).
 */
export function headingOfEntry(entry: Entry): EntryHeading {
  return {
    no: entry.no,
    type: entry.type,
    author: entry.author,
    created_at: entry.created_at,
    title: entry.title,
    action_id: entry.action_id ?? null,
    facts: factsOfEntry(entry),
  };
}

/** Строка заголовка словами: для подсказок, подписей и тестов. */
export function headlineText(headline: Headline): string {
  if (headline.kind !== 'built') return '';
  return headline.parts
    .map((part) => {
      switch (part.kind) {
        case 'words':
        case 'id':
          return part.text;
        case 'task':
          return part.key;
        case 'entry':
          return `${part.key}#${part.no}`;
      }
    })
    .join(' ');
}
