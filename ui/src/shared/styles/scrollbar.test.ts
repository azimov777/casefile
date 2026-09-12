import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const STYLES = resolve(__dirname);
const RESET = readFileSync(join(STYLES, 'reset.css'), 'utf8');

/**
 * Текст файла без комментариев: сторож ловит объявления, а не упоминания. Про
 * `::-webkit-scrollbar` рассказывает комментарий у токена `--ui-scrollbar`
 * (`theme.css`), и запрещать это было бы запретом объяснять свой код.
 */
function code(path: string): string {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '');
}

/** Все файлы стилей и разметки репозитория, кроме `reset.css` самого. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    if (path === join(STYLES, 'reset.css')) return [];
    return ['.css', '.ts', '.tsx'].includes(extname(path)) && !path.endsWith('.test.ts')
      ? [path]
      : [];
  });
}

/**
 * Тело блока `{ … }`, начинающегося после `from`, со счётом вложенных скобок:
 * внутри `@supports` лежат свои правила, и первая же `}` закрывает не его.
 */
function block(css: string, from: number): string {
  const open = css.indexOf('{', from);
  let depth = 0;
  for (let at = open; at < css.length; at += 1) {
    if (css[at] === '{') depth += 1;
    if (css[at] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, at);
    }
  }
  throw new Error('незакрытый блок в reset.css');
}

/** Правила вида `::-webkit-scrollbar…{ … }` из `reset.css`, без комментариев. */
function webkitRules(): { selector: string; body: string }[] {
  const css = RESET.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...css.matchAll(/(^|})\s*(::-webkit-scrollbar[^{}]*?)\{([^{}]*)\}/g)].map((found) => ({
    selector: (found[2] as string).trim(),
    body: found[3] as string,
  }));
}

describe('полосы прокрутки — одно место на весь интерфейс (UI-116)', () => {
  it('оформление полос объявлено только в `reset.css`', () => {
    const property = /\bscrollbar-(?:width|color)\s*:|::-webkit-scrollbar/;
    const guilty = sources(resolve(__dirname, '../..')).filter((path) => property.test(code(path)));

    expect(guilty).toEqual([]);
  });

  /*
   * Главное правило этой задачи, и оно неочевидно: стандартные свойства старше
   * псевдоэлементов и гасят их целиком — узел, которому заданы оба, рисует полосу
   * так, будто псевдоэлементов нет вовсе (замер UI-116#28, Chromium 151 и
   * WebKit 26.5). Стандартная пара, выпавшая из-под `@supports`, не сломает ни
   * сборку, ни этот файл сама по себе — она молча вернёт системную полосу.
   */
  it('стандартная пара свойств стоит только под `@supports not selector(::-webkit-scrollbar)`', () => {
    const guard = RESET.indexOf('@supports not selector(::-webkit-scrollbar)');
    expect(guard, 'запасной путь для движков без псевдоэлементов пропал').toBeGreaterThan(-1);

    const fallback = block(RESET, guard);
    const standard = /\bscrollbar-(?:width|color)\s*:/g;

    expect(fallback.match(standard), 'под `@supports` нет обоих стандартных свойств').toHaveLength(
      2,
    );
    expect(
      RESET.match(standard),
      'стандартное свойство объявлено и вне `@supports` — оно погасит наш ползунок',
    ).toHaveLength(2);
  });

  it('запасной путь: ширина ровно `thin`, цвет ползунка — токен темы', () => {
    const fallback = block(RESET, RESET.indexOf('@supports not selector(::-webkit-scrollbar)'));
    const width = /scrollbar-width:\s*([^;]+);/.exec(fallback);
    const color = /scrollbar-color:\s*([^;]+);/.exec(fallback);

    expect(width![1]!.trim()).toBe('thin');
    // Первое значение — ползунок — обязано ссылаться на токен темы; дорожка законно
    // прозрачна (`transparent` — ключевое слово CSS, не цвет темы и не литерал вроде
    // `#fff` — тем же словом окрашены рамки и заливки по всему проекту).
    expect(color![1]!.trim()).toMatch(/^var\(--color-[\w-]+\)\s+transparent$/);
  });

  it('своя полоса: толщина — токен `--ui-scrollbar`, обе оси одинаковы', () => {
    const bar = webkitRules().find((rule) => rule.selector === '::-webkit-scrollbar');

    expect(bar, 'правила `::-webkit-scrollbar` в reset.css нет').toBeDefined();
    expect(/width:\s*var\(--ui-scrollbar\)\s*;/.test(bar!.body), bar!.body).toBe(true);
    expect(/height:\s*var\(--ui-scrollbar\)\s*;/.test(bar!.body), bar!.body).toBe(true);
  });

  it('своя полоса: каждая заливка — токен темы или прозрачность, ни одного литерала', () => {
    const painted = webkitRules().flatMap((rule) =>
      [...rule.body.matchAll(/background:\s*([^;]+);/g)].map((found) => ({
        selector: rule.selector,
        value: (found[1] as string).trim(),
      })),
    );

    expect(painted.length, 'ползунок ничем не покрашен').toBeGreaterThan(0);
    expect(
      painted.filter(
        (paint) => paint.value !== 'transparent' && !/^var\(--color-[\w-]+\)$/.test(paint.value),
      ),
    ).toEqual([]);
  });
});
