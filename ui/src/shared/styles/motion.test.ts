import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Сторож правила «длительность только токеном, гашение переменной».
 *
 * Правило держится на том, что `prefers-reduced-motion` переопределяет `--motion-*`
 * (`index.css`), и заводящему новый переход не надо ничего вспоминать. Число,
 * написанное в разметке, выводит движение из-под этого правила молча.
 *
 * Почему нарушение ловится здесь, а не в браузере. Рядом с переопределением стоит
 * страховка `*` с `transition-duration: 0.01ms !important`, и она накрывает
 * **и нарушителя тоже**: при `prefers-reduced-motion` вычисленная длительность
 * у `duration-300` окажется той же `0.01ms`, что у токена. Браузер по устройству
 * не отличает движение на токене от движения на числе — значит источник длительности
 * читают текстом, а браузер проверяет другое: что гашение работает
 * (`e2e/motion.spec.ts`). Решение — `UI-63#10`.
 *
 * Ни одного места движения здесь не выписано. Словарь берётся из самих файлов темы,
 * места — обходом дерева `src`: новое движение попадает под сторожа в тот же день,
 * когда написано, и вспоминать про сторожа никому не надо.
 */

const STYLES = resolve(__dirname);
const SRC = resolve(__dirname, '../..');
const ROOT = resolve(SRC, '..');

/** Словарь и его гашение — единственные два файла, где времени числом место. */
const VOCABULARY = join('src', 'shared', 'styles', 'tokens.css');
const EXTINGUISHING = join('src', 'shared', 'styles', 'index.css');

/**
 * Текст без комментариев: в них словарь объясняют словами и числами, и сторож ловил бы
 * собственное объяснение. Строчный комментарий срезается только там, где перед `//`
 * не двоеточие, — иначе вместе с ним уехал бы `https://`.
 */
function code(text: string): string {
  return text.replaceAll(/\/\*[\s\S]*?\*\//g, ' ').replaceAll(/(^|[^:])\/\/[^\n]*/gm, '$1');
}

/** Пары «переменная → значение» из куска CSS. */
function declarations(css: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of code(css).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    found.set(match[1] as string, (match[2] as string).trim());
  }
  return found;
}

/** Имена переменных с этой приставкой. Групповой сброс `--x-*: initial` именем не считается. */
function declared(css: string, prefix: string): string[] {
  return [...declarations(css)]
    .filter(([token, value]) => token.startsWith(prefix) && value !== 'initial')
    .map(([token]) => token);
}

/** Блок `@media (prefers-reduced-motion: reduce)` целиком: в нём живёт гашение. */
function reduceBlock(css: string): string {
  const start = css.indexOf('@media (prefers-reduced-motion: reduce)');
  if (start === -1) return '';

  let depth = 0;
  for (let at = css.indexOf('{', start); at < css.length; at += 1) {
    if (css[at] === '{') depth += 1;
    if (css[at] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(start, at + 1);
    }
  }
  return css.slice(start);
}

/** Время в миллисекундах: `120ms` и `0.12s` — одно число, записанное по-разному. */
function ms(value: string): number {
  const number = Number.parseFloat(value);
  return value.trim().endsWith('ms') ? number : number * 1000;
}

/** Все исходники интерфейса. Порождённый клиент контракта не наш текст и не правится. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    if (/\.test\.tsx?$/.test(path) || path.endsWith(join('shared', 'api', 'openapi.ts'))) return [];
    return /\.(tsx?|css)$/.test(path) ? [path] : [];
  });
}

const tokens = readFileSync(join(STYLES, 'tokens.css'), 'utf8');
const theme = readFileSync(join(STYLES, 'theme.css'), 'utf8');
const index = readFileSync(join(STYLES, 'index.css'), 'utf8');

const durations = declared(tokens, '--motion-');
const curves = declared(theme, '--ease-');
const motions = declared(theme, '--animate-');

const files = sources(SRC).map((path) => ({
  path: relative(ROOT, path),
  text: code(readFileSync(path, 'utf8')),
}));
const markup = files.filter((file) => !file.path.endsWith('.css'));

/**
 * Утилиты вида `duration-…`, `ease-…`, `animate-…`, `delay-…` из всего кода.
 *
 * Не только из `*.tsx`: строку классов собирают и в `*.ts` — вариантами `cva`, общей
 * основой кирпича, — и сторож, читающий одну разметку, чужой кривой и чужого имени
 * движения там не увидел бы.
 *
 * Имена чужой шкалы здесь нарочно не названы ни одним примером. Tailwind 4 ищет
 * кандидатов в **тексте** файлов, комментарии включая: имя, написанное в этой самой
 * строке, приезжает в собранный CSS настоящим токеном. Замерено — `UI-63#13`.
 */
function utilities(kind: string): { where: string; value: string }[] {
  const pattern = new RegExp(String.raw`(?<![\w-])${kind}-([^\s'"\`]+)`, 'g');
  return markup.flatMap((file) =>
    [...file.text.matchAll(pattern)].map((match) => ({
      where: file.path,
      value: match[1] as string,
    })),
  );
}

describe('словарь движения объявлен там, где его гасят', () => {
  it('в словаре есть что стеречь: длительности, кривые и имена движений', () => {
    // Без этого все проверки ниже перебирали бы пустые списки и молчали бы обо всём.
    expect(durations.length).toBeGreaterThan(0);
    expect(curves.length).toBeGreaterThan(0);
    expect(motions.length).toBeGreaterThan(0);
  });

  it('каждая длительность словаря погашена при `prefers-reduced-motion`', () => {
    const extinguished = declarations(reduceBlock(index));

    // Заведут третью длительность и забудут погасить — покраснеет здесь, а не через
    // полгода на чужом ноутбуке. Ровно этого перечисление переходов и не умеет.
    for (const token of durations) {
      const value = extinguished.get(token);
      expect(value, `${token} объявлен в tokens.css, но не погашен в index.css`).toBeDefined();
      // Ноль здесь нельзя: переход обязан остаться переходом и слать `transitionend`.
      expect(ms(value ?? '')).toBeGreaterThan(0);
      expect(ms(value ?? '')).toBeLessThan(1);
    }
  });

  it('страховка накрывает оба рода движения, а не один', () => {
    const extinguishing = reduceBlock(index);

    // Переопределения переменной мало: движение приходит и из чужого CSS (Radix),
    // где наших токенов нет вовсе.
    expect(extinguishing).toMatch(/transition-duration:\s*[^;]+!important/);
    expect(extinguishing).toMatch(/animation-duration:\s*[^;]+!important/);
  });

  it('каждое имя движения собрано из токенов, а не из своих чисел', () => {
    for (const [animation, value] of declarations(theme)) {
      if (!animation.startsWith('--animate-')) continue;
      expect(value, `${animation} обязан брать длительность токеном`).toContain('var(--motion-');
      expect(value, `${animation} обязан брать кривую токеном`).toContain('var(--ease-');
    }
  });
});

describe('длительность числом: её нет нигде, кроме словаря и его гашения', () => {
  it('во всём `src` время написано числом только в словаре и в блоке гашения', () => {
    const guilty = files
      .filter((file) => file.path !== VOCABULARY)
      .map((file) =>
        file.path === EXTINGUISHING
          ? { ...file, text: file.text.replace(reduceBlock(file.text), ' ') }
          : file,
      )
      .filter((file) => /(?<![\w.])\d+(\.\d+)?m?s(?![\w-])/.test(file.text))
      .map((file) => file.path);

    // Правило нарочно шире, чем «утилита названа верно»: оно ловит любую форму записи —
    // утилиту, свойство в CSS, стиль объектом в JSX — включая те, которых ещё не
    // придумали. Сторож, знающий только знакомые формы, устаревает на первой незнакомой.
    expect(guilty, 'длительность берут токеном: `--motion-fast` или `--motion-slow`').toEqual([]);
  });

  it('в самом словаре время стоит только у длительностей', () => {
    const light = code(tokens).slice(0, code(tokens).indexOf('@media'));
    const timed = [...declarations(light)]
      .filter(([, value]) => /^\d+(\.\d+)?m?s$/.test(value))
      .map(([token]) => token);

    // Иначе исключение, данное словарю, стало бы исключением, данным файлу: в него
    // можно было бы положить любую длительность мимо `--motion-*`.
    expect([...timed].sort()).toEqual([...durations].sort());
  });
});

describe('утилиты движения в разметке — только словарные', () => {
  it('движение в разметке вообще есть', () => {
    // Нижняя граница, а не точное число: счёт мест — тот же перечень, только в одной
    // цифре, и законная правка разметки красила бы прогон, ничего не сказав о правиле.
    expect(utilities('duration').length).toBeGreaterThan(10);
    expect(utilities('animate').length).toBeGreaterThan(0);
  });

  it('длительность берётся переменной словаря', () => {
    const allowed = durations.map((token) => `(${token})`);

    expect(utilities('duration').filter(({ value }) => !allowed.includes(value))).toEqual([]);
  });

  it('кривая берётся из словаря', () => {
    const allowed = curves.map((token) => token.replace('--ease-', ''));

    expect(utilities('ease').filter(({ value }) => !allowed.includes(value))).toEqual([]);
  });

  it('имя движения объявлено в `@theme`', () => {
    const allowed = motions.map((token) => token.replace('--animate-', ''));

    expect(utilities('animate').filter(({ value }) => !allowed.includes(value))).toEqual([]);
  });

  it('задержки нет ни одной: словарь её не содержит, а страховка её не гасит', () => {
    // `transition-delay` и `animation-delay` правило `*` не трогает, и задержка,
    // написанная числом, пережила бы просьбу не двигать интерфейс целиком.
    expect(utilities('delay')).toEqual([]);
  });
});
