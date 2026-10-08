import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { LANGUAGES, dictionaries, i18n } from '@/shared/i18n';
import { ENTRY_TYPES, type EntryType } from '../api/entries';
import { entryHeadline, headlineText, type EntryFacts, type Headline } from './headline';

function built(facts: EntryFacts): Headline {
  return entryHeadline(facts, 'DEMO-4', say.ui);
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
 * в контракт, роняет сборку теста ровно так же, как роняет её словарь.
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
  acceptance: { type: 'acceptance' },
  warning: { type: 'warning', partial: [2], unverifiable: [3] },
  status_changed: { type: 'status_changed', from_status: 'open', to_status: 'done' },
  section_changed: { type: 'section_changed', field: 'goal' },
  field_changed: { type: 'field_changed', field: 'priority' },
  assignee_changed: { type: 'assignee_changed', assignee_to: 'owner' },
  link_added: { type: 'link_added', link_kind: 'blocked_by', other_key: 'DEMO-2' },
  link_removed: { type: 'link_removed', link_kind: 'relates', other_key: 'DEMO-3' },
  moved: { type: 'moved', from_key: 'UI-5', to_key: 'DEMO-9' },
  attribute_created: { type: 'attribute_created', name: 'repo' },
  attribute_changed: { type: 'attribute_changed', name: 'repo' },
  attribute_removed: { type: 'attribute_removed', name: 'repo' },
  archived: { type: 'archived' },
  restored: { type: 'restored' },
  conclusion: { type: 'conclusion' },
  attached: { type: 'attached', task_key: 'DEMO-1', discussion: 'DEMO~1' },
  detached: { type: 'detached', task_key: 'DEMO-1', discussion: 'DEMO~1' },
  closed: { type: 'closed' },
} satisfies Record<EntryType, EntryFacts>;

describe('названия типов записи в словарях', () => {
  it.each(LANGUAGES)('в словаре %s назван каждый тип контракта', (language) => {
    // Набор объявлен через `satisfies Record<EntryType, string>` в самом словаре: тип,
    // добавленный в контракт, ломает сборку. Здесь проверяется вторая половина — что
    // ни одно название не пустое.
    for (const type of ENTRY_TYPES) {
      expect(dictionaries[language].ui.entry.type[type], type).not.toBe('');
    }
  });

  it('образец фактов есть на каждый тип записи', () => {
    // Сверка со словарём названий, а не с перечислением в голове: оба объекта
    // объявлены ключами по `EntryType`, и разойтись они могут только вместе с ним.
    expect(Object.keys(FACTS).sort()).toEqual(Object.keys(dictionaries.en.ui.entry.type).sort());
  });
});

/*
 * Заголовок собирается на языке интерфейса, и проверяется это на каждом: ожидаемая
 * строка берётся из словаря тем же ключом, что и в коде, а вокруг неё стоят
 * идентификаторы контракта — они одинаковы на любом языке, и в этом половина смысла
 * проверки.
 */
describe.each(LANGUAGES)('заголовок записи по фактам на языке %s', (language) => {
  beforeAll(() => {
    void i18n.changeLanguage(language);
  });

  afterAll(() => {
    void i18n.changeLanguage('en');
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
    expect(line(FACTS.status_changed)).toBe(`${say.ui('entry.headline.status')} open → done`);
    expect(
      line({ type: 'status_changed', from_status: 'open', to_status: 'backlog', has_reason: true }),
    ).toBe(
      `${say.ui('entry.headline.status')} open → backlog ${say.ui('entry.headline.withReason')}`,
    );

    // Статусы — идентификаторы контракта: их не переводят (TRK#239).
    expect(ids(FACTS.status_changed)).toEqual(['open', 'done']);
  });

  it('правка раздела и поля называет имя поля, а значения оставляет записи', () => {
    expect(line(FACTS.section_changed)).toBe(`${say.ui('entry.headline.sectionEdited')} goal`);
    expect(line(FACTS.field_changed)).toBe(`${say.ui('entry.headline.fieldEdited')} priority`);
    expect(ids(FACTS.section_changed)).toEqual(['goal']);

    // Точечная правка проверки: её номер в фактах есть, но в строке не называется —
    // вид описи задачей UI-64 не менялся.
    expect(line({ type: 'section_changed', field: 'checks', check_no: 3 })).toBe(
      `${say.ui('entry.headline.sectionEdited')} checks`,
    );
  });

  it('смена исполнителя называет обоих, а отсутствие — словом', () => {
    expect(line(FACTS.assignee_changed)).toBe(
      `${say.ui('entry.headline.assignee')} ${say.ui('entry.headline.none')} → owner`,
    );
    expect(line({ type: 'assignee_changed', assignee_from: 'owner' })).toBe(
      `${say.ui('entry.headline.assignee')} owner → ${say.ui('entry.headline.cleared')}`,
    );
  });

  it('связь называет вид и вторую сторону ссылкой на неё', () => {
    const added = built(FACTS.link_added);
    expect(headlineText(added)).toBe(`${say.ui('entry.headline.linkAdded')} blocked_by DEMO-2`);
    expect(added.kind === 'built' && added.parts.at(-1)).toEqual({
      kind: 'task',
      key: 'DEMO-2',
    });

    expect(line(FACTS.link_removed)).toBe(`${say.ui('entry.headline.linkRemoved')} relates DEMO-3`);
  });

  it('у связи родителя и ребёнка роль второй задачи сказана словами перед её ключом', () => {
    // Вид назван от лица этой задачи: у программы `parent DEMO-9` — «DEMO-9 её дочерняя».
    expect(line({ type: 'link_added', link_kind: 'parent', other_key: 'DEMO-9' })).toBe(
      `${say.ui('entry.headline.linkAdded')} parent ${say.ui('entry.headline.linkRole.parent')} DEMO-9`,
    );
    // У ребёнка `child DEMO-8` — «DEMO-8 её родитель», и при снятии связи так же.
    expect(line({ type: 'link_removed', link_kind: 'child', other_key: 'DEMO-8' })).toBe(
      `${say.ui('entry.headline.linkRemoved')} child ${say.ui('entry.headline.linkRole.child')} DEMO-8`,
    );
    // Фраза самого идентификатора у остальных видов читается верно — слов не прибавляется.
    expect(line({ type: 'link_added', link_kind: 'blocks', other_key: 'DEMO-3' })).toBe(
      `${say.ui('entry.headline.linkAdded')} blocks DEMO-3`,
    );
  });

  it('перенос называет прежний и новый ключ, и оба — ссылки на задачу (TRK-172)', () => {
    expect(line(FACTS.moved)).toBe(`${say.ui('entry.headline.moved')} UI-5 → DEMO-9`);
    const moved = built(FACTS.moved);
    expect(moved.kind === 'built' && moved.parts.filter((part) => part.kind === 'task')).toEqual([
      { kind: 'task', key: 'UI-5' },
      { kind: 'task', key: 'DEMO-9' },
    ]);
  });

  it('ответ и вердикт тоже собираются здесь: их заголовок выводит трекер', () => {
    const answer = built(FACTS.answer);
    expect(headlineText(answer)).toBe(`${say.ui('entry.headline.answerTo')} DEMO-4#4`);
    expect(answer.kind === 'built' && answer.parts.at(-1)).toEqual({
      kind: 'entry',
      key: 'DEMO-4',
      no: 4,
    });

    expect(line(FACTS.verdict)).toBe(`${say.ui('entry.headline.check', { no: 3 })} failed`);
    expect(ids(FACTS.verdict)).toEqual(['failed']);
  });

  it('снятый вопрос назван словами, а не «ответом» (TRK-552)', () => {
    const withdrawn = built({ type: 'answer', question_no: 5, outcome: 'withdrawn' });
    expect(headlineText(withdrawn)).toBe(
      `${say.ui('entry.headline.question')} DEMO-4#5 ${say.ui('entry.headline.withdrawn')}`,
    );
    expect(withdrawn.kind === 'built' && withdrawn.parts[1]).toEqual({
      kind: 'entry',
      key: 'DEMO-4',
      no: 5,
    });
  });

  it('заменённый вопрос называет заменивший ссылкой на его запись (TRK-552)', () => {
    const replaced = built({ type: 'answer', question_no: 5, outcome: 'replaced', replaced_by: 8 });
    expect(headlineText(replaced)).toBe(
      `${say.ui('entry.headline.question')} DEMO-4#5 ${say.ui('entry.headline.replacedBy')} DEMO-4#8`,
    );
    expect(replaced.kind === 'built' && replaced.parts.at(-1)).toEqual({
      kind: 'entry',
      key: 'DEMO-4',
      no: 8,
    });
  });

  it('ответ по существу и ответ без исхода называются как раньше (TRK-552)', () => {
    // Ответ, подшитый до появления исхода, поля не несёт — это `answered`.
    expect(line({ type: 'answer', question_no: 4, outcome: 'answered', replaced_by: null })).toBe(
      line(FACTS.answer),
    );
    expect(line(FACTS.answer)).toBe(`${say.ui('entry.headline.answerTo')} DEMO-4#4`);
  });

  it('разбор замечания называет исход словами, а продолжение — ссылкой', () => {
    const resolution = built(FACTS.resolution);
    const accepted = say.ui('entry.headline.resolutionOutcome', {
      outcome: say.ui('entry.remarkOutcome.accepted'),
    });
    expect(headlineText(resolution)).toBe(
      `${say.ui('entry.headline.resolution')} DEMO-4#7 ${accepted} → DEMO-9`,
    );
    expect(resolution.kind === 'built' && resolution.parts.at(-1)).toEqual({
      kind: 'task',
      key: 'DEMO-9',
    });

    // Исход — слова, а не идентификатор контракта: его читает человек.
    expect(ids(FACTS.resolution)).toEqual([]);
    const declined = say.ui('entry.headline.resolutionOutcome', {
      outcome: say.ui('entry.remarkOutcome.declined'),
    });
    expect(line({ type: 'resolution', remark_no: 2, outcome: 'declined' })).toBe(
      `${say.ui('entry.headline.resolution')} DEMO-4#2 ${declined}`,
    );
  });

  it('заведение задачи называется словами, без фактов', () => {
    expect(line(FACTS.created)).toBe(say.ui('entry.headline.created'));
  });

  it('заведение в деле проекта — «проект заведён», а не «задача заведена»', () => {
    expect(headlineText(entryHeadline(FACTS.created, 'TRK', say.ui))).toBe(
      say.ui('entry.headline.projectCreated'),
    );
  });

  it('в деле области (TRK-557) — «область заведена», архив и восстановление — её', () => {
    const area = (facts: EntryFacts) => headlineText(entryHeadline(facts, 'TRK/promotion', say.ui));
    expect(area(FACTS.created)).toBe(say.ui('entry.headline.areaCreated'));
    expect(area({ type: 'archived' })).toBe(say.ui('entry.headline.areaArchived'));
    expect(area({ type: 'restored' })).toBe(say.ui('entry.headline.areaRestored'));
    // У проекта — по-прежнему проектные.
    expect(headlineText(entryHeadline({ type: 'archived' }, 'TRK', say.ui))).toBe(
      say.ui('entry.headline.projectArchived'),
    );
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
    expect(line({ type: 'status_changed' })).toBe(
      `${say.ui('entry.headline.status')} ${say.ui('entry.headline.none')} → ${say.ui('entry.headline.cleared')}`,
    );
    expect(line({ type: 'section_changed' })).toBe(say.ui('entry.headline.sectionEdited'));
    expect(line({ type: 'verdict' })).toBe(say.ui('entry.headline.check', { no: '?' }));
  });
});

/*
 * Слова исхода ответа на каждом языке — вписаны руками, а не взяты из словаря: здесь
 * проверяется сам текст, который прочтёт человек (TRK-552), а не связь ключа с местом.
 */
describe('исход ответа словами на русском и на английском', () => {
  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it.each([
    [
      'ru',
      'Вопрос DEMO-4#5 снят',
      'Вопрос DEMO-4#5 заменён вопросом DEMO-4#8',
      'Ответ на DEMO-4#5',
    ],
    [
      'en',
      'Question DEMO-4#5 withdrawn',
      'Question DEMO-4#5 replaced by DEMO-4#8',
      'Answer to DEMO-4#5',
    ],
  ] as const)('%s', async (language, withdrawn, replaced, answered) => {
    await i18n.changeLanguage(language);
    expect(line({ type: 'answer', question_no: 5, outcome: 'withdrawn' })).toBe(withdrawn);
    expect(line({ type: 'answer', question_no: 5, outcome: 'replaced', replaced_by: 8 })).toBe(
      replaced,
    );
    expect(line({ type: 'answer', question_no: 5 })).toBe(answered);
  });
});

/*
 * Исходы проверки не целиком, предупреждение и принятие (TRK-561) — вписаны руками на
 * каждом языке: проверяется текст, который прочтёт человек, а не связь ключа с местом.
 */
describe('исходы не целиком, предупреждение и принятие словами на русском и на английском', () => {
  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it.each([
    [
      'ru',
      'Обзорная проверка 2 частично',
      'Обзорная проверка 3 невозможно проверить',
      'Закрыта не целиком: проверка 2 частично проверка 3 невозможно проверить',
      'принятие',
      'предупреждение',
    ],
    [
      'en',
      'Review check 2 partial',
      'Review check 3 cannot be verified',
      'Closed not in full: check 2 partial check 3 cannot be verified',
      'acceptance',
      'warning',
    ],
  ] as const)('%s', async (language, partial, unverifiable, warning, acceptance, warningType) => {
    await i18n.changeLanguage(language);
    expect(line({ type: 'verdict', check_no: 2, outcome: 'partial' })).toBe(partial);
    expect(line({ type: 'verdict', check_no: 3, outcome: 'unverifiable' })).toBe(unverifiable);
    expect(line({ type: 'warning', partial: [2], unverifiable: [3] })).toBe(warning);
    // Принятие подписывает автор: заголовок его, а род записи назван словарём.
    expect(built({ type: 'acceptance' }).kind).toBe('author');
    expect(dictionaries[language].ui.entry.type.acceptance).toBe(acceptance);
    expect(dictionaries[language].ui.entry.type.warning).toBe(warningType);
  });

  it('исходы не целиком — плашкой, `passed` и `failed` — идентификатором, как были', () => {
    const partial = built({ type: 'verdict', check_no: 2, outcome: 'partial' });
    expect(partial.kind === 'built' && partial.parts.at(-1)?.kind).toBe('flag');
    expect(ids({ type: 'verdict', check_no: 1, outcome: 'passed' })).toEqual(['passed']);
    expect(ids({ type: 'verdict', check_no: 1, outcome: 'failed' })).toEqual(['failed']);
  });
});
