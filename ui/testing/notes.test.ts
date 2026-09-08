import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/*
 * Указатели «Где:» в `docs/notes/` обязаны вести в живой код.
 *
 * Заметка — единственное знание, переживающее сессию агента: задания удаляются,
 * отчёты исчезают вместе с контекстом. Её читают **до** кода и ей верят, поэтому
 * указатель на переехавший модуль стоит следующему агенту получаса поисков поведения,
 * которого нет на названном месте, и кончается выводом «документация врёт» — после
 * которого не верят уже и живым записям.
 *
 * Своими глазами это не ловится: к UI-42 протухли четыре указателя, и заметили двух.
 * Ловит только прогон, поэтому проверка живёт в `pnpm check` (`vitest` собирает
 * `testing/**` наравне с `src/**`), а не отдельной командой, которую надо вспомнить.
 *
 * Формат самой записи проверять здесь нечего: он описан в `docs/CONVENTIONS.md`
 * и под тест не меняется. Тест читает заметки такими, какие они есть.
 */

const ROOT = resolve(__dirname, '..');
const NOTES = join(ROOT, 'docs', 'notes');

/** Карта папки — не заметка: её `##` перечисляют файлы, а не находки. */
const FOLDER_MAP = 'AGENTS.md';

/**
 * Баннер файла-истории: механика снесена, файл оставлен целиком как материал.
 * Его «Где:» ведут в код, которого нет, и это честно — но честно ровно потому,
 * что пометка стоит на всём файле, а не потеряна среди живых записей. Стоять она
 * обязана в шапке, до первой записи: освобождает себя файл, а не отдельная находка.
 */
const HISTORY_BANNER = /^> \*\*Файл-история:\*\*/m;

/** Заголовок записи: `##` внутри файла области. */
const ENTRY_HEADING = /^## (.+)$/;

/**
 * Поле «Где:» записи: от подписи до следующего поля или конца записи. Многострочное —
 * указатель на два-три места переносится по ширине строки, как и любой другой текст.
 */
const WHERE_FIELD = /^\*\*Где:\*\*([\s\S]*?)(?=^\*\*|(?![\s\S]))/m;

/** Токен в обратных кавычках: путь, имя символа или кусок команды. */
const QUOTED = /`([^`]+)`/y;

/**
 * Разделители между местами одного указателя: знаки препинания и два союза. Всё
 * остальное — слово, то есть проза (см. `leadingPlaces`).
 */
const SEPARATORS = /[\s,:().«»"'—–-]*(?:(?:или|и)[\s,:().«»"'—–-]+)?/y;

/** Расширения, которые в этом репозитории встречаются. Токен с таким концом — путь. */
const FILE_LIKE =
  /^[\w@./-]+\.(ts|tsx|js|jsx|mjs|cjs|css|md|json|yml|yaml|html|conf|template|sh|txt|example)$/;

/** Токен без пробелов и скобок: только такой вообще может оказаться путём. */
const PLAIN = /^[\w@./-]+$/;

interface Place {
  note: string;
  heading: string;
  /** Файлы куска, разобранные до настоящих путей: в них ищутся символы того же куска. */
  files: string[];
  symbols: string[];
}

interface Report {
  entries: number;
  pointers: number;
  places: Place[];
  missingFiles: string[];
  missingSymbols: string[];
}

/** Файл-история освобождён от проверки указателей — по баннеру в шапке, а не по имени. */
export function isHistoryFile(text: string): boolean {
  const firstEntry = text.search(/^## /m);
  const header = firstEntry === -1 ? text : text.slice(0, firstEntry);
  return HISTORY_BANNER.test(header);
}

/**
 * Ведущий список мест куска: токены от начала и до первого слова прозы.
 *
 * Поле «Где:» — не всегда список путей: за ним нередко идёт объяснение, и в нём
 * **законно** поминают снесённый код («модуля `tasks-table.module.css` больше нет»).
 * Разбирать поле целиком значило бы требовать вернуть удалённые файлы, то есть чистить
 * честный текст ради зелёного прогона. Поэтому проза заканчивает разбор куска: всё,
 * что после первого слова, — комментарий, и он не проверяется.
 */
export function leadingPlaces(segment: string): string[] {
  const found: string[] = [];
  let at = 0;

  for (;;) {
    SEPARATORS.lastIndex = at;
    SEPARATORS.exec(segment);
    QUOTED.lastIndex = SEPARATORS.lastIndex;

    const token = QUOTED.exec(segment);
    if (token?.[1] === undefined) return found;

    found.push(token[1]);
    at = QUOTED.lastIndex;
  }
}

/** Куски указателя: места разделяются `;`, внутри куска файл и его символы. */
function segmentsOf(field: string): string[] {
  const cuts: string[] = [];
  let start = 0;

  // Кавычки пропускаются целиком: `;` внутри токена — часть токена, а не разделитель.
  for (const match of field.matchAll(/`[^`]*`|;/g)) {
    if (match[0] === ';' && match.index !== undefined) {
      cuts.push(field.slice(start, match.index));
      start = match.index + 1;
    }
  }

  cuts.push(field.slice(start));
  return cuts;
}

function looksLikePath(token: string): boolean {
  if (FILE_LIKE.test(token)) return true;
  // `.nvmrc` и подобные точечные файлы не подходят ни под расширение, ни под косую
  // черту — их выдаёт только само существование в репозитории.
  return PLAIN.test(token) && (token.includes('/') || existsSync(join(ROOT, token)));
}

/**
 * Путь до места, названного токеном, или `null`.
 *
 * Кроме пути от корня заметки пользуются сокращением: назвав полный путь, соседа рядом
 * с ним пишут одним именем (`tokens.css` после `src/shared/styles/theme.css`), а место
 * в том же срезе — хвостом пути (`ui/answer-form.tsx` после `.../model/draft.ts`).
 * Сокращение ищется вверх по предкам последнего разобранного файла: требовать вместо
 * него полный путь значило бы менять формат заметок под тест.
 */
function locate(token: string, base: string | undefined): string | null {
  const direct = join(ROOT, token);
  if (existsSync(direct)) return direct;
  if (base === undefined) return null;

  for (let dir = dirname(base); dir.startsWith(ROOT); dir = dirname(dir)) {
    const candidate = join(dir, token);
    if (existsSync(candidate)) return candidate;
  }

  return null;
}

/**
 * Указатель уходит за пределы репозитория или назван шаблоном — такое не проверяется.
 *
 * Соседний репозиторий (`../tracker/...`) на чужой машине может быть не выкачан вовсе,
 * и проверка, падающая от этого, хуже отсутствующей: её отключат первым же прогоном.
 */
function outsideRepo(token: string): boolean {
  return token.startsWith('../') || token.startsWith('/') || token.includes('*');
}

function inspect(): Report {
  const report: Report = {
    entries: 0,
    pointers: 0,
    places: [],
    missingFiles: [],
    missingSymbols: [],
  };

  const files = readdirSync(NOTES)
    .filter((name) => name.endsWith('.md') && name !== FOLDER_MAP)
    .sort();

  for (const name of files) {
    const text = readFileSync(join(NOTES, name), 'utf8');
    if (isHistoryFile(text)) continue;

    for (const chunk of text.split(/^(?=## )/m)) {
      const heading = ENTRY_HEADING.exec(chunk.split('\n')[0] ?? '');
      if (heading?.[1] === undefined) continue;
      report.entries += 1;

      const field = WHERE_FIELD.exec(chunk);
      if (field?.[1] === undefined) continue;
      report.pointers += 1;

      for (const segment of segmentsOf(field[1])) {
        const place: Place = { note: name, heading: heading[1], files: [], symbols: [] };
        let skip = false;

        for (const token of leadingPlaces(segment)) {
          if (!looksLikePath(token)) {
            place.symbols.push(token);
            continue;
          }

          if (outsideRepo(token)) {
            // Кусок пропускается целиком, а не один токен: символ чужого файла
            // (`journal_page` в `entries.py`) иначе искался бы в соседнем нашем.
            skip = true;
            continue;
          }

          const target = locate(token, place.files.at(-1));
          if (target === null) {
            report.missingFiles.push(`${name}, «${heading[1]}»: нет файла ${token}`);
          } else if (statSync(target).isFile()) {
            place.files.push(target);
          }
        }

        if (skip || place.files.length === 0) continue;

        const bodies = place.files.map((path) => readFileSync(path, 'utf8'));
        const where = place.files.map((path) => relative(ROOT, path)).join(', ');
        report.missingSymbols.push(
          ...place.symbols
            .filter((symbol) => !bodies.some((body) => body.includes(symbol)))
            .map((symbol) => `${name}, «${heading[1]}»: символа «${symbol}» нет в ${where}`),
        );

        report.places.push(place);
      }
    }
  }

  return report;
}

const report = inspect();
const checkedFiles = report.places.reduce((sum, place) => sum + place.files.length, 0);
const checkedSymbols = report.places.reduce((sum, place) => sum + place.symbols.length, 0);

describe('указатели «Где:» в заметках', () => {
  /*
   * Нижние границы, а не точные числа: заметки только копятся, и точное число пришлось
   * бы править каждой находкой. Границы стерегут другое — что разбор вообще состоялся
   * и что заметки не вывели из-под проверки оптом. Баннер файла-истории освобождает
   * файл целиком, и, приписанный `ui.md`, он обрушил бы счёт до трети — то есть
   * тихо погасил бы проверку. Здесь это падение, а не тишина.
   */
  it('разобраны, а не потеряны разбором', () => {
    expect(report.entries).toBeGreaterThanOrEqual(80);
    expect(report.pointers).toBeGreaterThanOrEqual(80);
    expect(checkedFiles + checkedSymbols).toBeGreaterThanOrEqual(120);
  });

  it('ведут в существующие файлы', () => {
    expect(report.missingFiles).toEqual([]);
  });

  it('называют символы, которые в этих файлах есть', () => {
    expect(report.missingSymbols).toEqual([]);
  });
});

describe('файл-история', () => {
  const banner = '> **Файл-история:** механика снесена задачей UI-20, в коде её больше нет.';

  it('узнаётся по баннеру в шапке', () => {
    expect(isHistoryFile(`# Вебхуки\n\n${banner}\n\n## Находка\n\n**Где:** \`нет.ts\`\n`)).toBe(
      true,
    );
  });

  it('без баннера остаётся обычной заметкой', () => {
    expect(isHistoryFile('# Вебхуки\n\n## Находка\n\n**Где:** `нет.ts`\n')).toBe(false);
  });

  /*
   * Освобождает себя файл, а не запись: баннер ниже первой `##` не считается. Иначе
   * протухший указатель прятали бы строкой рядом с собой, и проверка стала бы
   * необязательной для того, кто о ней знает.
   */
  it('не освобождает себя баннером, приписанным к записи', () => {
    expect(isHistoryFile(`# Вебхуки\n\n## Находка\n\n${banner}\n\n**Где:** \`нет.ts\`\n`)).toBe(
      false,
    );
  });
});

describe('разбор указателя', () => {
  it('кончается на первом слове прозы', () => {
    expect(
      leadingPlaces(' `e2e/hit-target.spec.ts`. Приём переехал: `task-row.module.css`'),
    ).toEqual(['e2e/hit-target.spec.ts']);
  });

  it('берёт все места, пока идут разделители и союзы', () => {
    expect(leadingPlaces(' `a.ts`, `b.ts` и `SYMBOL` (`--n-500`)')).toEqual([
      'a.ts',
      'b.ts',
      'SYMBOL',
      '--n-500',
    ]);
  });
});
