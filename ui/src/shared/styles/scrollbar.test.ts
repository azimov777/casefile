import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const STYLES = resolve(__dirname);
const RESET = readFileSync(join(STYLES, 'reset.css'), 'utf8');

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

describe('полосы прокрутки — одно место на весь интерфейс (UI-116)', () => {
  it('`scrollbar-width`/`scrollbar-color` объявлены только в `reset.css`', () => {
    const property = /\bscrollbar-(?:width|color)\s*:/;
    const guilty = sources(resolve(__dirname, '../..')).filter((path) =>
      property.test(readFileSync(path, 'utf8')),
    );

    expect(guilty).toEqual([]);
  });

  it('оба свойства в `reset.css` объявлены и не литералом: цвет — токеном темы', () => {
    const width = /scrollbar-width:\s*([^;]+);/.exec(RESET);
    const color = /scrollbar-color:\s*([^;]+);/.exec(RESET);

    expect(width, '`scrollbar-width` не найден в reset.css').not.toBeNull();
    expect(color, '`scrollbar-color` не найден в reset.css').not.toBeNull();

    expect(width![1]!.trim()).toBe('thin');
    // Первое значение — ползунок — обязано ссылаться на токен темы; дорожка законно
    // прозрачна (`transparent` — ключевое слово CSS, не цвет темы и не литерал вроде
    // `#fff` — тем же словом окрашены рамки и заливки по всему проекту).
    expect(color![1]!.trim()).toMatch(/^var\(--color-[\w-]+\)\s+transparent$/);
  });
});
