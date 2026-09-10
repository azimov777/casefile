import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * `docs/FRONTEND.md` — карта контракта: что где искать и почему устроено именно так.
 * Документ читают до того, как поднимут бэкенд, и путь из него уезжает прямо в код
 * интерфейса, а код ошибки — в текст, который увидит человек.
 *
 * Пока документ жил в репозитории бэкенда, его сверял питоновский тест рядом с кодом.
 * Переехав сюда, он остался бы обещанием: карта, отставшая от контракта, хуже
 * отсутствующей — по ней пишут запрос, получают `404` и полчаса подозревают свою
 * авторизацию. Поэтому проверка переехала вместе с документом и сверяет его с теми же
 * двумя артефактами бэкенда, которые тот выгружает командой.
 */
const DOC = resolve(process.cwd(), 'docs/FRONTEND.md');
const SCHEMA = resolve(process.cwd(), '../openapi.json');
const ERRORS = resolve(process.cwd(), '../docs/ERRORS.md');

/**
 * Путь API в тексте документа. Строка обрывается на первом символе, которого в пути
 * быть не может: `?` начинает параметры запроса, а обратная кавычка и пробел —
 * окружающий текст.
 */
const API_PATH = /\/api\/v1[A-Za-z0-9_/{}-]*/g;

/**
 * Заголовок таблицы частых ошибок. Проверка отталкивается от него, а не от всех
 * обратных кавычек документа: в тексте есть и имена полей, и значения перечислений,
 * и «код», найденный среди них, был бы ложным срабатыванием.
 */
const ERROR_TABLE_HEADER = '| Код | Когда |';

/** Код в первой колонке строки таблицы. */
const CODE = /`([a-z][a-z0-9_]*)`/g;

const doc = () => readFileSync(DOC, 'utf8');

function codesNamedInTheDoc(): string[] {
  const lines = doc().split('\n');
  const start = lines.indexOf(ERROR_TABLE_HEADER) + 2; // заголовок и строка-разделитель
  const codes = new Set<string>();
  for (const line of lines.slice(start)) {
    if (!line.startsWith('|')) break;
    const cell = line.split('|')[1] ?? '';
    for (const [, code] of cell.matchAll(CODE)) if (code) codes.add(code);
  }
  return [...codes];
}

describe('карта контракта для интерфейса', () => {
  it('называет только те пути, которые есть в схеме', () => {
    expect(
      existsSync(SCHEMA),
      `Не найден контракт ${SCHEMA}. Бэкенд — корень этого репозитория, на уровень выше ui/`,
    ).toBe(true);

    const named = [...new Set(doc().match(API_PATH) ?? [])];
    const declared = new Set(Object.keys(JSON.parse(readFileSync(SCHEMA, 'utf8')).paths));

    expect(
      named.length,
      'документ не называет ни одного пути — шаблон промахнулся',
    ).toBeGreaterThan(0);
    expect(named.filter((path) => !declared.has(path))).toEqual([]);
  });

  it('называет только те коды ошибок, которые бэкенд может вернуть', () => {
    expect(
      existsSync(ERRORS),
      `Не найден справочник ${ERRORS}. Бэкенд — корень этого репозитория, на уровень выше ui/`,
    ).toBe(true);

    const named = codesNamedInTheDoc();
    const known = new Set(
      [...readFileSync(ERRORS, 'utf8').matchAll(/^\| `([a-z][a-z0-9_]*)`/gm)].map(
        ([, code]) => code,
      ),
    );

    expect(
      named.length,
      'таблица кодов не разобрана — проверка ничего не стережёт',
    ).toBeGreaterThan(0);
    expect(named.filter((code) => !known.has(code))).toEqual([]);
  });
});
