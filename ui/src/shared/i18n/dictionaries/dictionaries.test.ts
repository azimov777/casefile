import { afterAll, describe, expect, it } from 'vitest';
import { i18n } from '../i18n';
import { LANGUAGES, type Language } from '../languages';
import { dictionaries } from './index';

/*
 * Наборы ключей всех словарей обязаны совпадать.
 *
 * Компилятор видит только английский: типы ключей построены на нём (`i18next.d.ts`),
 * поэтому пропажу ключа из английского он ловит сам, а пропажу из русского — нет.
 * Ловит её этот тест, и потому подпись, забытая в одном языке, роняет `pnpm check`,
 * а не доезжает до человека английской фразой посреди русского экрана.
 */

/**
 * Множественное число даёт языку разное число ключей на одну фразу: в английском две
 * формы (`_one`, `_other`), в русском четыре (`_one`, `_few`, `_many`, `_other`).
 * Сравнивать их в лоб нельзя — иначе честная плюрализация выглядела бы расхождением.
 * Сравнивается фраза, а не форма: суффикс формы отбрасывается.
 *
 * Формы перечислены по `Intl.PluralRules`, а своей таблицы у нас нет и не будет.
 */
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/** Плоский список ключей словаря: `login.submit`, `errors.unauthorized`. */
function keysOf(node: unknown, prefix = '', stripForm = true): string[] {
  if (typeof node !== 'object' || node === null) {
    return [stripForm ? prefix.replace(PLURAL_SUFFIX, '') : prefix];
  }

  return Object.entries(node).flatMap(([key, value]) =>
    keysOf(value, prefix === '' ? key : `${prefix}.${key}`, stripForm),
  );
}

function sortedKeys(language: keyof typeof dictionaries): string[] {
  return [...new Set(keysOf(dictionaries[language]))].sort();
}

describe('словари языков', () => {
  it('перечислены все поддержанные языки и ничего сверх', () => {
    expect(Object.keys(dictionaries).sort()).toEqual([...LANGUAGES].sort());
  });

  it('набор ключей одинаков во всех языках', () => {
    const reference = sortedKeys('en');

    expect(reference.length).toBeGreaterThan(10);
    for (const language of LANGUAGES) {
      expect(sortedKeys(language), `словарь ${language}`).toEqual(reference);
    }
  });

  it('ни одна подпись не осталась непереведённой копией английской', () => {
    // Совпадение текста законно там, где переводить нечего: подсказка формата токена,
    // пример на языке запросов бэкенда, подстановка кода ошибки, приписка к заголовку
    // разбора и знак вопроса вместо неизвестного числа — знаки и подстановки,
    // без единого слова. И имя продукта: Casefile — название, а не слово, и буква
    // значка идёт за ним. Так же и чужие продукты с форматами у фрагментов подключения
    // (UI-105): Claude Code и Codex — названия клиентов, `JSON mcpServers` — имя формата
    // конфигурации, URL и JSON — имена форматов, и подпись поля «URL» в приложении Codex
    // на русском та же. И пример имени участника (UI-106, и у человека — UI-122): имена — латиница
    // `snake_case` на любом языке интерфейса, и переведённый пример показывал бы то,
    // чего бэкенд не примет. И подпись родителя (UI-119): ключ, разделитель, название
    // и число остальных — подстановки и знаки, слов в них нет. И номера крайних записей
    // группы правок (UI-133): два числа через тире.
    const sameOnPurpose = new Set([
      'access.agent.namePlaceholder',
      'people.create.namePlaceholder',
      'ui.app.name',
      'ui.app.mark',
      'login.title',
      'login.tokenPlaceholder',
      'tasks.filters.query.placeholder',
      'tasks.board.unknown',
      'ui.error.withCode',
      'ui.entry.headline.resolutionOutcome',
      'ui.entry.group.range',
      'ui.snippets.clients.claudeCode',
      'ui.snippets.clients.codex',
      'ui.snippets.clients.json',
      'ui.snippets.addressCaption',
      'ui.snippets.codexField.url',
      'ui.snippets.jsonCaption',
      'ui.task.parents.caption',
      'ui.task.parents.item',
      'ui.task.parents.more',
    ]);

    /*
     * Сравниваются полные ключи, вместе с формой множественного числа: у стёртой формы
     * (`tasks.found`) значения нет ни в одном языке, и два `undefined` прошли бы за
     * непереведённую копию. Формы, которых в английском нет вовсе (`_few`, `_many`),
     * сравнивать не с чем — они пропускаются.
     */
    const copied = fullKeys('en').filter((key) => {
      if (sameOnPurpose.has(key.replace(PLURAL_SUFFIX, ''))) return false;
      const russian = phrase('ru', key);
      return russian !== undefined && phrase('en', key) === russian;
    });

    expect(copied).toEqual([]);
  });
});

/** Плоский список ключей вместе с формой множественного числа. */
function fullKeys(language: keyof typeof dictionaries): string[] {
  return keysOf(dictionaries[language], '', false).sort();
}

function phrase(language: keyof typeof dictionaries, key: string): unknown {
  return key
    .split('.')
    .reduce<unknown>(
      (node, step) =>
        typeof node === 'object' && node !== null
          ? (node as Record<string, unknown>)[step]
          : undefined,
      dictionaries[language],
    );
}

/*
 * Множественное число проверяется на границах, а не на глаз.
 *
 * Границы взяты не наугад: у русского форма меняется на 1, 2 и 5, повторяется на 11
 * (это `many`, а не `one`, — самая частая ошибка ручной таблицы) и снова становится
 * `one` на 21. Ноль стоит здесь потому, что он не форма языка, а наше решение: `_zero`
 * `i18next` берёт раньше остальных на обоих языках, и им пишется «вопросов нет» —
 * вместо ветки `count > 0 ? … : …` в разметке.
 */
const COUNTS = [0, 1, 2, 5, 11, 21];

/**
 * Пространства, чьи ключи — коды бэкенда (`error.code`, `details.fields[].reason`), а
 * не авторские фразы: те же, что `i18next.d.ts` объявляет `Record<string, string>`.
 * Код случайно кончается на суффикс формы числа — `too_many` («элементов слишком
 * много», `app/domain/fields.py`) читается как форма `_many` ключа `too` — и без
 * исключения эвристика множественного числа приняла бы контрактный код за
 * недописанную форму множественного числа.
 */
const CODE_NAMESPACES = new Set(['errors', 'fieldReasons']);

/** Ключи, у которых в английском словаре есть формы: их и спрашиваем со счётчиком. */
function pluralKeys(): { ns: string; key: string }[] {
  const seen = new Set<string>();

  for (const full of keysOf(dictionaries.en, '', false)) {
    if (CODE_NAMESPACES.has(full.split('.', 1)[0] ?? '')) continue;
    if (!PLURAL_SUFFIX.test(full)) continue;
    seen.add(full.replace(PLURAL_SUFFIX, ''));
  }

  return [...seen].sort().map((path) => {
    const [ns, ...rest] = path.split('.');
    return { ns: ns as string, key: rest.join('.') };
  });
}

/**
 * Фраза со счётчиком на названном языке.
 *
 * Ключ считается из самого словаря и потому типам не известен: `strictKeyChecks`
 * требует литерала, а обойти это иначе нечем — перечислить ключи руками значило бы
 * завести второй список, который разойдётся с первым. Приведение стоит здесь одно
 * на весь файл и ровно ради этого.
 */
function said(language: Language, ns: string, key: string, count: number): string {
  void i18n.changeLanguage(language);
  const t = i18n.getFixedT(null, ns as 'ui') as (key: string, options: object) => string;
  return t(key, { count });
}

describe('множественное число', () => {
  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it.each(LANGUAGES)('в словаре %s счётная фраза говорит на каждой границе', (language) => {
    const keys = pluralKeys();
    expect(keys.length).toBeGreaterThan(5);

    for (const { ns, key } of keys) {
      for (const count of COUNTS) {
        const text = said(language, ns, key, count);
        const where = `${language}:${ns}.${key} @ ${count}`;

        // Ключ, у которого не хватило формы, `i18next` возвращает самим собой.
        expect(text, where).not.toBe(key);
        expect(text, where).not.toBe('');
        // Число стоит во фразе везде, кроме нулевой формы: там сказано «нет», а не «0».
        if (count > 0) expect(text, where).toContain(String(count));
      }
    }
  });

  it.each(LANGUAGES)('в словаре %s форма выбирается по числу, а не одна на все', (language) => {
    for (const { ns, key } of pluralKeys()) {
      const where = `${language}:${ns}.${key}`;
      // Один и много различаются в обоих языках: у английского это `_one` и `_other`,
      // у русского — `_one` и `_many`. Совпадение означает, что форма не выбирается.
      expect(said(language, ns, key, 1), where).not.toBe(said(language, ns, key, 5));
      // Ноль сказан своей фразой, а не формой числа 1.
      expect(said(language, ns, key, 0), where).not.toBe(said(language, ns, key, 1));
    }
  });

  it('одиннадцать не читается как один: у русского это отдельная форма', () => {
    // Ровно то, на чём ломается таблица окончаний, написанная руками: 11, 12, 13 и 14
    // идут по `many`, хотя кончаются на 1, 2, 3 и 4.
    expect(said('ru', 'ui', 'app.openQuestions', 11)).toBe('11 открытых вопросов');
    expect(said('ru', 'ui', 'app.openQuestions', 21)).toBe('21 открытый вопрос');
    expect(said('ru', 'tasks', 'found', 11)).toBe('Нашлось 11 задач');
    expect(said('ru', 'tasks', 'found', 21)).toBe('Нашлась 21 задача');
  });

  it('счётчик вопросов и счётчик задач называются словами на обеих границах', () => {
    // Обход двоеточием («Открытых вопросов: 3») снят по-настоящему: слово склоняется.
    expect(COUNTS.map((count) => said('ru', 'ui', 'app.openQuestions', count))).toEqual([
      'Открытых вопросов нет',
      '1 открытый вопрос',
      '2 открытых вопроса',
      '5 открытых вопросов',
      '11 открытых вопросов',
      '21 открытый вопрос',
    ]);
    expect(COUNTS.map((count) => said('en', 'ui', 'app.openQuestions', count))).toEqual([
      'No open questions',
      '1 open question',
      '2 open questions',
      '5 open questions',
      '11 open questions',
      '21 open questions',
    ]);
    expect(COUNTS.map((count) => said('ru', 'tasks', 'found', count))).toEqual([
      'Ничего не нашлось',
      'Нашлась 1 задача',
      'Нашлось 2 задачи',
      'Нашлось 5 задач',
      'Нашлось 11 задач',
      'Нашлась 21 задача',
    ]);
    expect(COUNTS.map((count) => said('en', 'tasks', 'found', count))).toEqual([
      'Nothing found',
      '1 task found',
      '2 tasks found',
      '5 tasks found',
      '11 tasks found',
      '21 tasks found',
    ]);
  });
});

describe('разряды числа', () => {
  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  /*
   * Разделитель разрядов — свойство языка, как и форма слова: у английского запятая,
   * у русского пробел. Считает его `Intl` внутри `i18next` (`{{count, number}}`
   * в словаре), поэтому своей таблицы разделителей здесь нет — как нет и таблицы
   * окончаний. Четырёхзначное число — первое, на котором это видно.
   */
  const BIG = 1234;

  it.each(LANGUAGES)('в словаре %s счётная фраза разделяет разряды по-своему', (language) => {
    const expected = new Intl.NumberFormat(language).format(BIG);
    expect(expected).not.toBe(String(BIG));

    for (const { ns, key } of pluralKeys()) {
      const where = `${language}:${ns}.${key}`;
      const text = said(language, ns, key, BIG);

      expect(text, where).toContain(expected);
      // Голое `1234` во фразе означало бы подстановку мимо `Intl`.
      expect(text, where).not.toContain(String(BIG));
    }
  });

  it('у языков разделитель разный, и фразы поэтому не совпадают', () => {
    expect(said('en', 'tasks', 'found', BIG)).not.toContain(
      new Intl.NumberFormat('ru').format(BIG),
    );
    expect(said('ru', 'tasks', 'found', BIG)).not.toContain(
      new Intl.NumberFormat('en').format(BIG),
    );
  });
});
