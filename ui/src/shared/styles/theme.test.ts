import { readFileSync } from 'node:fs';
import { readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const STYLES = resolve(__dirname);
const tokens = readFileSync(join(STYLES, 'tokens.css'), 'utf8');
const theme = readFileSync(join(STYLES, 'theme.css'), 'utf8');

/** Блок `@media (prefers-color-scheme: dark)` целиком: в нём живёт ночная половина. */
function darkBlock(css: string): string {
  const start = css.indexOf('@media (prefers-color-scheme: dark)');
  return start === -1 ? '' : css.slice(start);
}

function declarations(css: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of css.matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    found.set(match[1] as string, (match[2] as string).trim());
  }
  return found;
}

const light = declarations(tokens.slice(0, tokens.indexOf('@media (prefers-color-scheme: dark)')));
const dark = new Map([...light, ...declarations(darkBlock(tokens))]);
const semantic = declarations(theme);

/** Разворачивает `var(--x)` до значения: цепочка «примитив → семантика» может быть любой длины. */
function resolveValue(name: string, scope: Map<string, string>): string {
  const seen = new Set<string>();
  let value = scope.get(name) ?? semantic.get(name) ?? '';
  while (value.startsWith('var(')) {
    const inner = value.slice(4, value.indexOf(')'));
    if (seen.has(inner)) throw new Error(`Кольцо ссылок на ${inner}`);
    seen.add(inner);
    value = scope.get(inner) ?? semantic.get(inner) ?? '';
  }
  return value;
}

function channel(part: string): number {
  const value = Number.parseInt(part, 16) / 255;
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const clean = hex.replace('#', '');
  const [r, g, b] = [clean.slice(0, 2), clean.slice(2, 4), clean.slice(4, 6)].map(channel) as [
    number,
    number,
    number,
  ];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Отношение контраста по WCAG: то же число, которое считает `axe`. */
function contrast(front: string, back: string): number {
  const a = luminance(front);
  const b = luminance(back);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function ratio(text: string, surface: string, scope: Map<string, string>): number {
  return contrast(resolveValue(text, scope), resolveValue(surface, scope));
}

const THEMES: [string, Map<string, string>][] = [
  ['светлая', light],
  ['тёмная', dark],
];

describe.each(THEMES)('контраст: %s тема', (_name, scope) => {
  // Содержание и то, что его объясняет, читают, а не сканируют: им нужен полный AA.
  it.each(['--t-ground', '--t-surface', '--t-sunken'])(
    'основной и приглушённый текст на %s не ниже 4.5',
    (surface) => {
      expect(ratio('--t-text', surface, scope)).toBeGreaterThanOrEqual(4.5);
      expect(ratio('--t-muted', surface, scope)).toBeGreaterThanOrEqual(4.5);
    },
  );

  // Служебное сканируют взглядом: ключ, время, счётчик. Порог крупного текста и
  // нетекстовых элементов — 3.0; ниже него им нельзя красить содержание.
  it.each(['--t-ground', '--t-surface', '--t-sunken'])(
    'служебный текст на %s не ниже 3.0',
    (surface) => {
      expect(ratio('--t-faint', surface, scope)).toBeGreaterThanOrEqual(3);
    },
  );

  it.each(['neutral', 'progress', 'positive', 'attention', 'danger'])(
    'текст тона %s на своей заливке не ниже 4.5',
    (tone) => {
      expect(ratio(`--t-${tone}`, `--t-${tone}-soft`, scope)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it('снятое читается на поверхности: заливки у него нет вовсе', () => {
    // Плашка `cancelled` — содержание строки, а не служебная подпись: ей нужен
    // полный AA. Служебный уровень давал на белом 3.59 и был пойман `axe`.
    expect(ratio('--t-dropped', '--t-surface', scope)).toBeGreaterThanOrEqual(4.5);
  });

  it('акцент читается на поверхности, а его текст — на нём самом', () => {
    expect(ratio('--t-accent', '--t-surface', scope)).toBeGreaterThanOrEqual(4.5);
    expect(ratio('--t-accent-text', '--t-accent', scope)).toBeGreaterThanOrEqual(4.5);
  });
});

describe('слои темы', () => {
  const component = [...semantic].filter(([name]) => name.startsWith('--ui-'));

  it('компонентных токенов больше одного и каждый ссылается на семантику', () => {
    expect(component.length).toBeGreaterThan(1);

    for (const [name, value] of component) {
      // Литерал в этом слое не переключился бы вместе с темой и пережил бы её молча.
      expect(value, `${name} обязан ссылаться на var(), а не нести литерал`).toContain('var(');
    }
  });

  it('тёмная тема не переопределяет ни одного компонентного токена', () => {
    const night = declarations(darkBlock(tokens));
    const overridden = [...night.keys()].filter((name) => name.startsWith('--ui-'));

    expect(overridden).toEqual([]);
  });

  it('в @theme попала только семантика: примитивов там нет', () => {
    const scales = /^--(n|d|blue|green|amber|red)-/;
    const leaked = [...semantic.keys()].filter((name) => scales.test(name));

    expect(leaked).toEqual([]);
  });

  it('семантический цвет объявлен ссылкой, а не значением: иначе тема его не переключит', () => {
    const colors = [...semantic].filter(
      ([name, value]) => name.startsWith('--color-') && value !== 'initial',
    );

    expect(colors.length).toBeGreaterThan(10);
    for (const [name, value] of colors) {
      expect(value, `${name} обязан ссылаться на значение темы`).toMatch(/^var\(--t-/);
    }
  });
});

/** Все файлы разметки: по ним проверяется, что чужая шкала не течёт в классы. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return path.endsWith('.tsx') && !path.endsWith('.test.tsx') ? [path] : [];
  });
}

describe('шкала Tailwind по умолчанию не течёт в разметку', () => {
  const files = sources(resolve(__dirname, '../..'));

  it.each([
    [
      'чужая палитра',
      /\b(?:bg|text|border|outline|ring|fill|stroke)-(?:gray|slate|zinc|neutral|stone|red|blue|green|amber|yellow|indigo|violet)-\d{2,3}\b/,
    ],
    ['чужая шкала кегля', /\btext-(?:xs|sm|base|lg|xl|[2-9]xl)\b/],
    ['чужая шкала радиусов', /\brounded-(?:xs|sm|md|lg|xl|[23]xl|full)\b/],
    ['примитив в произвольном значении', /\[var\(--(?:n|d|blue|green|amber|red)-/],
  ])('%s: ни одного вхождения', (_what, pattern) => {
    const guilty = files.filter((path) => pattern.test(readFileSync(path, 'utf8')));

    expect(guilty).toEqual([]);
  });
});
