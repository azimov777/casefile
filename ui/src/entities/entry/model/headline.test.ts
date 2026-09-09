import { describe, expect, it } from 'vitest';
import { ENTRY_TYPES, type EntryType } from '../api/entries';
import {
  ENTRY_TYPE_NAMES,
  entryHeadline,
  headlineText,
  type EntryFacts,
  type Headline,
} from './headline';

function built(facts: EntryFacts): Headline {
  return entryHeadline(facts, 'DEMO-4');
}

/** Строка целиком: то, что человек прочитает глазами. */
function line(facts: EntryFacts): string {
  return headlineText(built(facts));
}

/** Части, помеченные как идентификаторы контракта: они не переводятся. */
function ids(facts: EntryFacts): string[] {
  const headline = built(facts);
  if (headline.kind !== 'built') return [];
  return headline.parts.filter((part) => part.kind === 'id').map((part) => part.text);
}

/**
 * Образец фактов на каждый тип записи.
 *
 * Перечислено ключами объекта: `satisfies Record<EntryType, EntryFacts>` требует все
 * члены объединения, поэтому полнота списка не сверяется на глаз — тип, добавленный
 * в контракт, роняет сборку теста ровно так же, как роняет её `ENTRY_TYPE_NAMES`.
 * Разметка внутри каждого образца при этом проверяется формой: `{ type: 'verdict',
 * remark_no: 3 }` не соберётся.
 */
const FACTS = {
  created: { type: 'created' },
  summary: { type: 'summary' },
  decision: { type: 'decision' },
  attempt: { type: 'attempt' },
  finding: { type: 'finding' },
  artifact: { type: 'artifact' },
  remark: { type: 'remark' },
  note: { type: 'note' },
  question: { type: 'question', addressees: ['owner'], blocking: true },
  answer: { type: 'answer', question_no: 4 },
  verdict: { type: 'verdict', check_no: 3, outcome: 'failed' },
  resolution: { type: 'resolution', remark_no: 7, outcome: 'accepted', continuation_key: 'DEMO-9' },
  status_changed: { type: 'status_changed', from_status: 'open', to_status: 'done' },
  section_changed: { type: 'section_changed', field: 'goal' },
  field_changed: { type: 'field_changed', field: 'priority' },
  assignee_changed: { type: 'assignee_changed', assignee_to: 'owner' },
  link_added: { type: 'link_added', link_kind: 'blocked_by', other_key: 'DEMO-2' },
  link_removed: { type: 'link_removed', link_kind: 'relates', other_key: 'DEMO-3' },
} satisfies Record<EntryType, EntryFacts>;

describe('заголовок записи по фактам', () => {
  it('у каждого типа контракта есть русское название', () => {
    // Словарь объявлен через `satisfies Record<EntryType, string>`: тип, добавленный
    // в контракт, ломает сборку. Здесь проверяется вторая половина — что ни одно
    // название не пустое и все они на русском.
    for (const type of ENTRY_TYPES) {
      const name = ENTRY_TYPE_NAMES[type];
      expect(name).not.toBe('');
      expect(name).toMatch(/^[а-яё\s]+$/i);
    }
  });

  it('образец фактов есть на каждый тип записи', () => {
    // Сверка со словарём названий, а не с перечислением в голове: оба объекта
    // объявлены ключами по `EntryType`, и разойтись они могут только вместе с ним.
    expect(Object.keys(FACTS).sort()).toEqual(Object.keys(ENTRY_TYPE_NAMES).sort());
  });

  it('заголовок собирается у каждого типа записи, а не падает на незнакомом', () => {
    // Разметка перебрана в `entryHeadline` целиком — это держит `never`-ветка в
    // `switch`. Здесь то же самое проверяется на живых значениях: у каждого типа
    // есть свой исход, и ни один не остался без него.
    for (const type of ENTRY_TYPES) {
      expect(['built', 'author', 'derived']).toContain(built(FACTS[type]).kind);
    }
  });

  it('переход называет оба конца и говорит, искать ли причину', () => {
    expect(line(FACTS.status_changed)).toBe('Статус open → done');
    expect(
      line({ type: 'status_changed', from_status: 'open', to_status: 'backlog', has_reason: true }),
    ).toBe('Статус open → backlog · с причиной');

    // Статусы — идентификаторы контракта: их не переводят (`CONCEPT.md`, 6).
    expect(ids(FACTS.status_changed)).toEqual(['open', 'done']);
  });

  it('правка раздела и поля называет имя поля, а значения оставляет записи', () => {
    expect(line(FACTS.section_changed)).toBe('Правка раздела goal');
    expect(line(FACTS.field_changed)).toBe('Правка поля priority');
    expect(ids(FACTS.section_changed)).toEqual(['goal']);

    // Точечная правка проверки: её номер в фактах есть, но в строке не называется —
    // вид описи задачей UI-64 не менялся.
    expect(line({ type: 'section_changed', field: 'checks', check_no: 3 })).toBe(
      'Правка раздела checks',
    );
  });

  it('смена исполнителя называет обоих, а отсутствие — словом', () => {
    expect(line(FACTS.assignee_changed)).toBe('Исполнитель не назначен → owner');
    expect(line({ type: 'assignee_changed', assignee_from: 'owner' })).toBe(
      'Исполнитель owner → снят',
    );
  });

  it('связь называет вид и вторую сторону ссылкой на неё', () => {
    const added = built(FACTS.link_added);
    expect(headlineText(added)).toBe('Связь blocked_by DEMO-2');
    expect(added.kind === 'built' && added.parts.at(-1)).toEqual({
      kind: 'task',
      key: 'DEMO-2',
    });

    expect(line(FACTS.link_removed)).toBe('Связь снята relates DEMO-3');
  });

  it('ответ и вердикт тоже собираются здесь: их заголовок выводит трекер', () => {
    const answer = built(FACTS.answer);
    expect(headlineText(answer)).toBe('Ответ на DEMO-4#4');
    expect(answer.kind === 'built' && answer.parts.at(-1)).toEqual({
      kind: 'entry',
      key: 'DEMO-4',
      no: 4,
    });

    expect(line(FACTS.verdict)).toBe('Обзорная проверка 3 failed');
    expect(ids(FACTS.verdict)).toEqual(['failed']);
  });

  it('разбор замечания называет исход словами, а продолжение — ссылкой', () => {
    const resolution = built(FACTS.resolution);
    expect(headlineText(resolution)).toBe('Разбор DEMO-4#7 · принято в работу → DEMO-9');
    expect(resolution.kind === 'built' && resolution.parts.at(-1)).toEqual({
      kind: 'task',
      key: 'DEMO-9',
    });

    // Исход — слова, а не идентификатор контракта: его читает человек.
    expect(ids(FACTS.resolution)).toEqual([]);
    expect(line({ type: 'resolution', remark_no: 2, outcome: 'declined' })).toBe(
      'Разбор DEMO-4#2 · менять не будем',
    );
  });

  it('заведение задачи называется словами, без фактов', () => {
    expect(line(FACTS.created)).toBe('Задача заведена');
  });

  it('у записи агента заголовок остаётся авторским, у сводки — выведенным', () => {
    for (const type of [
      'decision',
      'attempt',
      'finding',
      'artifact',
      'note',
      'remark',
      'question',
    ] as const) {
      expect(built(FACTS[type]).kind).toBe('author');
    }
    // Заголовок сводки — первая строка «следующего шага»: в ленте он повторил бы тело.
    expect(built(FACTS.summary).kind).toBe('derived');
  });

  it('строка не разваливается на неполных фактах', () => {
    // Факты приходят от бэкенда, и старая запись может не знать нового поля. Пустое
    // место в строке лучше, чем `undefined` посреди фразы. Разметка при этом есть
    // всегда: без неё факты вообще нечем истолковать.
    expect(line({ type: 'status_changed' })).toBe('Статус не назначен → снят');
    expect(line({ type: 'section_changed' })).toBe('Правка раздела');
    expect(line({ type: 'verdict' })).toBe('Обзорная проверка ?');
  });
});
