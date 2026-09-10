import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/*
 * Заметки в `docs/notes/` обязаны говорить о живом коде.
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
 * Проверяемых мест два, и вопрос к ним разный (UI-71).
 *
 * 1. Поле «Где:» называет **место**: названный файл обязан существовать, а символ
 *    рядом с ним — находиться в этом самом файле. Вопрос строгий: указатель на то
 *    и указатель.
 * 2. Остальной текст записи — заголовок, «Что», «Почему важно», «Как правильно» —
 *    называет **мир**: библиотеку, поле контракта, соседний модуль, отвергнутый
 *    вариант. Требовать, чтобы каждое имя нашлось в названном файле, значит требовать
 *    прозу, которая говорит только о его содержимом; таких заметок не бывает —
 *    замерено на нынешних: 37 падений на 156 имён, и почти все на честном тексте.
 *    Вопрос к тексту слабее и потому честен: имя обязано встречаться где-нибудь
 *    в коде репозитория. Так ловится то, ради чего сторож и заведён, —
 *    переименованный или снесённый компонент, хук, константа, код ошибки: имя
 *    исчезает из репозитория целиком, и прогон падает у того, кто переименовал,
 *    а не через месяц у ревизии. Живое имя, описанное не в том месте, этой сетью
 *    не ловится, и это названная цена, а не недосмотр.
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

/** Токен целиком идентификатор: только такой вообще может оказаться именем из кода. */
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

/**
 * Имена, которых в коде нет намеренно, — с причиной, почему их там нет.
 *
 * Освобождение обязано быть видным: молчаливый пропуск по форме токена превратил бы
 * сторожа в решето, а «поправить текст, чтобы стало зелено» — в норму. Поэтому список
 * лежит здесь одним куском: он читается на ревизии целиком, требует причины словами,
 * и его рост виден в одном месте. Неиспользованная строка роняет прогон — список
 * не копится за спиной.
 *
 * Сюда попадает чужое (API браузера, компонент библиотеки, инструмент) и снесённое
 * своё, которое запись поминает по делу. Живое своё имя, которого «почему-то нет
 * в коде», сюда не попадает никогда: значит, его переименовали, и чинится запись.
 */
const NOT_IN_CODE: Record<string, string> = {
  DropdownMenu: 'Radix: у нас взят только `Select`, родня названа как таковая',
  DropdownMenuCheckboxItem: 'компонент shadcn/ui из эталона, который мы не взяли',
  Popover: 'Radix: у нас взят только `Select`, родня названа как таковая',
  elementFromPoint: 'API браузера',
  maxPages: 'настройка бесконечного запроса TanStack Query, названная как невзятая',
  onlyBuiltDependencies: 'поле pnpm 10, названное как отменённое',
  resize_window: 'инструмент браузерного расширения, не код репозитория',
  '10-listen-on-ipv6-by-default.sh': 'скрипт внутри образа nginx, а не наш файл',
  'markdown.module.css': 'снесённый модуль стилей, названный как снесённый',
};

/**
 * Файлы под гитом: из них собирается корпус кода и по ним разрешаются сокращённые
 * пути. Список берётся у гита, а не обходом дерева, потому что обход принёс бы
 * `node_modules`, сборку и чужие временные файлы — и имя, которого в репозитории нет,
 * подтвердилось бы первым попавшимся артефактом чужой сборки.
 */
function trackedFiles(): string[] {
  const listing = execFileSync('git', ['-C', ROOT, 'ls-files', '-z'], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });

  // Удалённый, но ещё не зафиксированный файл гит перечисляет: читать его нечем.
  return listing.split('\0').filter((path) => path !== '' && existsSync(join(ROOT, path)));
}

const TRACKED = trackedFiles();

/**
 * Код репозитория одной строкой: в нём ищутся имена из текста записей.
 *
 * Документация в корпус не входит. Заметка не должна подтверждать сама себя — иначе
 * имя, выдуманное в одной записи, узаконится второй; карты `AGENTS.md` — тот же
 * пересказ заметок. `pnpm-lock.yaml` не входит потому, что подтвердил бы имя любого
 * пакета мира.
 *
 * А вот этот файл в корпус входит наравне с остальным кодом — и потому примерами
 * здесь служат только живые имена. Выдуманное имя, поставленное примером в комментарии
 * или в проверке ниже, подтвердило бы само себя: заметка, назвавшая его, прошла бы
 * сторожа насквозь. Проверено на первом же прогоне UI-71 — и потому в примерах стоит
 * `ViewSwitch`, а не выдуманное имя, которым проверку заводили.
 */
const CODE = TRACKED.filter(
  (path) => !path.startsWith('docs/') && !path.endsWith('.md') && path !== 'pnpm-lock.yaml',
)
  .map((path) => readFileSync(join(ROOT, path), 'utf8'))
  .join('\n');

/**
 * Файлы под гитом по хвостам пути: `CONCEPT.md` → `docs/CONCEPT.md`,
 * `model/stream-client.ts` → `src/features/live-journal/model/stream-client.ts`.
 *
 * Заметки сокращают путь не только до соседа по папке (это разбирает `locate` вверх
 * по предкам), но и до узнаваемого хвоста откуда угодно. Хвост, подходящий двум файлам
 * (`index.ts`), не разрешается вовсе: догадка между ними была бы враньём.
 */
const BY_TAIL = new Map<string, string | null>();
for (const path of TRACKED) {
  const parts = path.split('/');
  for (let at = parts.length - 1; at >= 0; at -= 1) {
    const tail = parts.slice(at).join('/');
    BY_TAIL.set(tail, BY_TAIL.has(tail) ? null : path);
  }
}

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
  /** Сколько имён и файлов, названных текстом записей, проверено. */
  namedInText: number;
  unknownNames: string[];
  unknownTextFiles: string[];
  /** Освобождения из `NOT_IN_CODE`, которые пригодились хоть одной записи. */
  usedReliefs: Set<string>;
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

  if (base !== undefined) {
    for (let dir = dirname(base); dir.startsWith(ROOT); dir = dirname(dir)) {
      const candidate = join(dir, token);
      if (existsSync(candidate)) return candidate;
    }
  }

  // Последняя попытка — узнаваемый хвост пути: в тексте записи предка искать не от чего.
  const tail = BY_TAIL.get(token);
  return tail === undefined || tail === null ? null : join(ROOT, tail);
}

/**
 * Место в другом дереве: соседний репозиторий или абсолютный путь.
 *
 * `../tracker/...` на чужой машине может быть не выкачан вовсе, и проверка, падающая
 * от этого, хуже отсутствующей: её отключат первым же прогоном. По той же причине
 * запись, чьё «Где:» ведёт в другое дерево, не проверяется и текстом: она говорит
 * о чужом коде, и наш корпус про её имена не знает ничего.
 */
function beyondRepo(token: string): boolean {
  return token.startsWith('../') || token.startsWith('/');
}

/**
 * Указатель уходит за пределы репозитория или назван шаблоном — такое не проверяется.
 *
 * Шаблон (`e2e/*.spec.ts`) называет не файл, а их семейство: разбирать его нечем.
 * Освобождает он только сам кусок указателя — текст записи проверяется по-прежнему,
 * иначе звёздочка в «Где:» тихо снимала бы проверку со всей записи.
 */
function outsideRepo(token: string): boolean {
  return beyondRepo(token) || token.includes('*');
}

/**
 * Куски в обратных кавычках по всему тексту записи.
 *
 * Кавычек в ограде бывает несколько подряд — так markdown пишет кавычку внутри кода, —
 * и закрывает кусок ровно такая же связка. Разбор идёт по абзацам: незакрытая кавычка
 * иначе съела бы полфайла и принесла прозу вместо токена — а заодно унесла бы с собой
 * настоящие имена из следующих абзацев.
 */
export function codeSpans(text: string): string[] {
  const found: string[] = [];

  for (const paragraph of text.split(/\n[ \t]*\n/)) {
    for (const span of paragraph.matchAll(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g)) {
      if (span[2] !== undefined) found.push(span[2].trim());
    }
  }

  return found;
}

/**
 * Токен читается как имя из кода: целиком идентификатор, и в нём есть заглавная буква
 * или подчёркивание — `ViewSwitch`, `useExitHold`, `THEME_SCALES`, `question_no`.
 *
 * Это вся защита от ложных срабатываний, и она намеренно грубая: ложное срабатывание
 * учит править текст под тест, то есть убивает заметку, а пропуск оставляет всё как
 * было. Мимо проходят классы Tailwind и прочее через дефис (`min-w-0`, `aria-current`),
 * переменные CSS (`--motion-fast`), команды и любые токены с пробелом (`pnpm e2e`),
 * числа, цвета, разметка (`<tr>`) и обычные слова в кавычках (`data`, `enabled`):
 * имя это или слово, по одному `enabled` не решается, а цена ошибки несимметрична.
 *
 * Точечные формы (`document.fonts.check`, `details.position`) не проверяются тоже:
 * в этом репозитории это почти всегда вызов чужого API, а не своё имя.
 */
export function looksLikeName(token: string): boolean {
  return IDENTIFIER.test(token) && (/[A-Z]/.test(token) || token.includes('_'));
}

function inspect(): Report {
  const report: Report = {
    entries: 0,
    pointers: 0,
    places: [],
    missingFiles: [],
    missingSymbols: [],
    namedInText: 0,
    unknownNames: [],
    unknownTextFiles: [],
    usedReliefs: new Set(),
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
      /** Файлы, названные указателем: от них же считаются сокращения в тексте записи. */
      const named: string[] = [];
      let elsewhere = false;

      if (field?.[1] !== undefined) {
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
              elsewhere ||= beyondRepo(token);
              continue;
            }

            const target = locate(token, place.files.at(-1));
            if (target === null) {
              report.missingFiles.push(`${name}, «${heading[1]}»: нет файла ${token}`);
            } else if (statSync(target).isFile()) {
              place.files.push(target);
              named.push(target);
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

      if (elsewhere) continue;

      /*
       * Остальной текст записи — заголовок и поля, кроме самого указателя. Поле «Где:»
       * вырезается целиком: право прозы после ведущего списка мест поминать снесённое
       * (`docs/CONVENTIONS.md`) за ней остаётся.
       */
      const prose = field === null ? chunk : chunk.replace(WHERE_FIELD, '');

      for (const token of new Set(codeSpans(prose))) {
        if (outsideRepo(token)) continue;

        if (token in NOT_IN_CODE) {
          report.usedReliefs.add(token);
          continue;
        }

        // Файл, названный текстом, разбирается теми же сокращениями, что и указатель.
        const target = locate(token, named.at(-1));
        if (target !== null) {
          report.namedInText += 1;
          continue;
        }

        if (FILE_LIKE.test(token)) {
          report.namedInText += 1;
          report.unknownTextFiles.push(`${name}, «${heading[1]}»: нет файла ${token}`);
          continue;
        }

        if (!looksLikeName(token)) continue;
        report.namedInText += 1;

        if (!CODE.includes(token)) {
          report.unknownNames.push(`${name}, «${heading[1]}»: имени «${token}» нет в коде`);
        }
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

describe('текст записей', () => {
  /*
   * Та же нижняя граница и по той же причине: она стережёт, что разбор состоялся,
   * а не что имён ровно столько. Обвалить её может и правка отбора токенов — форма
   * имени задана здесь, и «уточнение», после которого проверять стало нечего,
   * иначе прошло бы молча.
   */
  it('разобран, а не потерян разбором', () => {
    expect(report.namedInText).toBeGreaterThanOrEqual(120);
  });

  it('называет существующие файлы', () => {
    expect(
      report.unknownTextFiles,
      'файл, названный текстом записи, обязан существовать: переезд правится в записи, ' +
        'а снесённый файл, помянутый по делу, освобождается строкой в NOT_IN_CODE',
    ).toEqual([]);
  });

  it('называет имена, которые есть в коде', () => {
    expect(
      report.unknownNames,
      'имя из текста записи ищется во всём коде репозитория. Нет его там по двум ' +
        'причинам: либо его переименовали или снесли — тогда чинится запись; либо оно ' +
        'чужое (браузер, библиотека, инструмент) — тогда строка в NOT_IN_CODE с причиной',
    ).toEqual([]);
  });

  /*
   * Освобождение живёт ровно столько, сколько живёт запись, которой оно понадобилось.
   * Иначе список превращается в свалку: имя, снятое с проверки однажды, остаётся снятым
   * навсегда — в том числе для записи, которая появится через год и назовёт его всерьёз.
   */
  it('не освобождается впрок', () => {
    const idle = Object.keys(NOT_IN_CODE).filter((name) => !report.usedReliefs.has(name));
    expect(idle, 'этих имён в заметках больше нет — строки из NOT_IN_CODE пора снести').toEqual([]);
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

describe('разбор текста записи', () => {
  it('берёт код отовсюду, а не ведущим списком', () => {
    expect(codeSpans('**Что:** `ViewSwitch` считает вид по `useSearchParams`.')).toEqual([
      'ViewSwitch',
      'useSearchParams',
    ]);
  });

  it('понимает ограду из двух кавычек', () => {
    expect(codeSpans('кавычка внутри кода: `` `code` ``.')).toEqual(['`code`']);
  });

  /*
   * Незакрытая кавычка — обычная опечатка разметки, и цена ей должна быть в один абзац:
   * разбор всего текста насквозь принял бы за код всю прозу до следующей кавычки.
   */
  it('не тянет кусок через пустую строку', () => {
    expect(codeSpans('незакрытая ` кавычка\n\nследующий абзац про `ViewSwitch`')).toEqual([
      'ViewSwitch',
    ]);
  });
});

describe('отбор имён', () => {
  it('берёт то, что читается именем из кода', () => {
    expect(['ViewSwitch', 'useExitHold', 'THEME_SCALES', 'question_no'].every(looksLikeName)).toBe(
      true,
    );
  });

  /*
   * Обратная сторона проверки, и она важнее прямой: в обратных кавычках заметок стоит
   * куда больше не-кода, чем кода, и сторож, падающий на классе Tailwind, кончится
   * правкой заметок под тест.
   */
  it('проходит мимо всего, что именем из кода не является', () => {
    expect(
      [
        'min-w-0',
        'aria-current',
        '--motion-fast',
        'pnpm e2e',
        '#828795',
        '409',
        '<tr>',
        'data',
        'position: relative',
        'document.fonts.check',
      ].some(looksLikeName),
    ).toBe(false);
  });
});
