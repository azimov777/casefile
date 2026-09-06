import type { components } from '@/shared/api';
import type { Entry, EntryType } from '../api/entries';

/** Факты записи из описи дела: то, чем её называют, не читая тела. */
export type EntryFacts = components['schemas']['EntryFactsRead'];

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
 * Русское название типа записи. Перечислено ключами объекта: тип, добавленный в
 * контракт, роняет сборку, а не остаётся без подписи на экране.
 */
export const ENTRY_TYPE_NAMES = {
  summary: 'сводка',
  decision: 'решение',
  attempt: 'попытка',
  finding: 'находка',
  artifact: 'артефакт',
  question: 'вопрос',
  answer: 'ответ',
  verdict: 'вердикт',
  note: 'заметка',
  created: 'заведение',
  status_changed: 'смена статуса',
  section_changed: 'правка раздела',
  field_changed: 'правка поля',
  assignee_changed: 'смена исполнителя',
  link_added: 'связь добавлена',
  link_removed: 'связь снята',
} satisfies Record<EntryType, string>;

const words = (text: string): HeadlinePart => ({ kind: 'words', text });
const id = (text: string): HeadlinePart => ({ kind: 'id', text });

/**
 * Заголовок записи по её типу и фактам.
 *
 * Строится из структурных полей, а не из готового `title`: тот приходит по-английски
 * и его формат — служебный слой бэкенда, а не контракт для клиента.
 *
 * `taskKey` нужен ответу: он ссылается на вопрос в той же задаче, а в фактах описи
 * лежит только номер записи.
 */
export function entryHeadline(type: EntryType, facts: EntryFacts, taskKey: string): Headline {
  switch (type) {
    case 'created':
      return { kind: 'built', parts: [words('Задача заведена')] };

    case 'status_changed':
      return {
        kind: 'built',
        parts: [
          words('Статус'),
          ...pair(facts.from_status, facts.to_status),
          // Причина — свободный текст, и её место в теле записи. Здесь только то,
          // искать её там или нет.
          ...(facts.has_reason === true ? [words('· с причиной')] : []),
        ],
      };

    case 'section_changed':
      return {
        kind: 'built',
        parts: [words('Правка раздела'), ...(facts.field == null ? [] : [id(facts.field)])],
      };

    case 'field_changed':
      return {
        kind: 'built',
        parts: [words('Правка поля'), ...(facts.field == null ? [] : [id(facts.field)])],
      };

    case 'assignee_changed':
      return {
        kind: 'built',
        parts: [words('Исполнитель'), ...pair(facts.assignee_from, facts.assignee_to)],
      };

    case 'link_added':
    case 'link_removed':
      return {
        kind: 'built',
        parts: [
          words(type === 'link_added' ? 'Связь' : 'Связь снята'),
          ...(facts.link_kind == null ? [] : [id(facts.link_kind)]),
          ...(facts.other_key == null ? [] : [{ kind: 'task' as const, key: facts.other_key }]),
        ],
      };

    case 'answer':
      return {
        kind: 'built',
        parts: [
          words('Ответ на'),
          ...(facts.question_no == null
            ? []
            : [{ kind: 'entry' as const, key: taskKey, no: facts.question_no }]),
        ],
      };

    case 'verdict':
      return {
        kind: 'built',
        parts: [
          words(`Обзорная проверка ${facts.check_no ?? '?'}`),
          ...(facts.outcome == null ? [] : [id(facts.outcome)]),
        ],
      };

    // Заголовок сводки — первая строка «следующего шага»: в ленте он стоял бы жирным
    // над тем же текстом, а в описи это единственное, чем сводку назвать.
    case 'summary':
      return { kind: 'derived' };

    // Вопрос, решение, попытка, находка, артефакт, заметка: заголовок пишет автор.
    default:
      return { kind: 'author' };
  }
}

/** Пара «было → стало». Отсутствие значения называется словом, а не пустотой. */
function pair(before: string | null | undefined, after: string | null | undefined) {
  return [
    before == null ? words('не назначен') : id(before),
    words('→'),
    after == null ? words('снят') : id(after),
  ];
}

/**
 * Факты записи ленты: там приходит `payload` целиком, а описи бэкенд отдаёт уже
 * вырезанное. Приведение здесь, чтобы строку собирало одно место для обоих.
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
        from_status: entry.payload.from as EntryFacts['from_status'],
        to_status: entry.payload.to as EntryFacts['to_status'],
        has_reason: entry.payload.reason != null && entry.payload.reason !== '',
      };
    case 'section_changed':
    case 'field_changed':
      return { field: entry.payload.field as EntryFacts['field'] };
    case 'assignee_changed':
      return { assignee_from: entry.payload.before, assignee_to: entry.payload.after };
    case 'link_added':
    case 'link_removed':
      return {
        link_kind: entry.payload.kind as EntryFacts['link_kind'],
        other_key: entry.payload.other,
      };
    case 'question':
      return { addressees: entry.payload.addressees, blocking: entry.payload.blocking };
    case 'answer':
      return { question_no: entry.payload.question_no };
    case 'verdict':
      return { check_no: entry.payload.check_no, outcome: entry.payload.outcome };
    default:
      return {};
  }
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
