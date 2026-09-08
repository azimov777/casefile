import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { cn, THEME_SCALES } from './cn';

const THEME_CSS = resolve(__dirname, '../styles/theme.css');

/**
 * Пространства имён `@theme`, которых в `THEME_SCALES` нет намеренно, и причина.
 *
 * Список закрыт: пространство, появившееся в `@theme` и не попавшее ни сюда, ни в
 * настройку, красит прогон. Иначе сторож стерёг бы только те шкалы, о которых знал
 * автор, — а ловушка бьёт по любой.
 */
const NOT_CONFIGURED: Record<string, string> = {
  color:
    'умолчание библиотеки — `color: [isAny]`: любое имя после `text-`, `bg-`, `border-` ' +
    'она и так относит к цвету, и тридцать имён палитры пришлось бы держать в согласии ' +
    'руками без единого изменения в поведении',
  font: 'умолчание — `font: [isAnyNonArbitrary]`: `font-mono` и `font-sans` уже разбираются гарнитурой',
  breakpoint:
    'рождает не утилиту, а вариант (`fold:`): спорить за свойство нечему, и склейка его не касается',
};

/** Тело `@theme { … }` целиком: внутри есть вложенный блок (`@keyframes`), поэтому по скобкам. */
function themeBlock(css: string): string {
  const open = css.indexOf('{', css.indexOf('@theme'));
  let depth = 0;
  for (let index = open; index < css.length; index++) {
    if (css[index] === '{') depth++;
    else if (css[index] === '}' && --depth === 0) return css.slice(open + 1, index);
  }
  throw new Error('Блок @theme не закрыт: сторож шкал не может прочитать theme.css');
}

/**
 * Объявленные шкалы: `--<пространство>-<имя>: …` из `@theme`, сгруппированные по
 * пространству. Начало строки в образце обязательно — иначе `var(--t-ground)` внутри
 * значения сошёл бы за объявление. Гашение чужой шкалы (`--text-*: initial`) под
 * образец не подходит: `*` не имя.
 */
function declaredScales(): Map<string, string[]> {
  const scales = new Map<string, string[]>();
  for (const [, space, name] of themeBlock(readFileSync(THEME_CSS, 'utf8')).matchAll(
    /^\s*--([a-z]+)-([a-z][a-z0-9-]*)\s*:/gm,
  )) {
    const names = scales.get(space as string) ?? [];
    names.push(name as string);
    scales.set(space as string, names);
  }
  return scales;
}

describe('настройка `cn` знает шкалы `@theme`', () => {
  const declared = declaredScales();

  it('сторож прочитал theme.css: пространства нашлись', () => {
    // Опечатка в пути или образце дала бы пустую карту, а пустая карта сошлась бы
    // с любой настройкой — и сторож молчал бы, ничего не стерегая.
    expect([...declared.keys()]).toContain('text');
    expect(declared.get('text')).toHaveLength(THEME_SCALES.text.length);
  });

  it('каждое пространство `@theme` либо в настройке, либо в названном исключении', () => {
    expect([...declared.keys()].sort()).toEqual(
      [...Object.keys(THEME_SCALES), ...Object.keys(NOT_CONFIGURED)].sort(),
    );
  });

  it.each(Object.keys(THEME_SCALES))(
    'имена шкалы `%s` в настройке совпадают со шкалой в theme.css',
    (space) => {
      const inConfig = THEME_SCALES[space as keyof typeof THEME_SCALES];

      expect([...inConfig].sort()).toEqual([...(declared.get(space) ?? [])].sort());
    },
  );
});

describe('кегль рядом с цветом', () => {
  const sizes = THEME_SCALES.text.map((name) => `text-${name}`);

  it.each(sizes)('%s остаётся при цвете, а не проигрывает ему', (size) => {
    for (const color of ['text-muted', 'text-faint', 'text-danger']) {
      expect(cn(size, color)).toBe(`${size} ${color}`);
      // И наоборот: цвет, названный раньше, кегль тоже не отменяет.
      expect(cn(color, size)).toBe(`${color} ${size}`);
    }
  });

  it('два кегля по-прежнему спорят: остаётся названный позже', () => {
    expect(cn('text-body', 'text-title')).toBe('text-title');
  });

  it('кегль не отменяет высоту строки: он её и не задаёт', () => {
    expect(cn('leading-[1.6]', 'text-label')).toBe('leading-[1.6] text-label');
  });

  it('а приставочная форма задаёт и потому отменяет', () => {
    // `text-body/6` печатает и `font-size`, и `line-height` — правило библиотеки здесь верно.
    expect(cn('leading-[1.6]', 'text-body/6')).toBe('text-body/6');
  });
});

describe('прочие шкалы проекта: класс от места вызова перебивает свой', () => {
  it.each([
    ['rounded-mark', 'rounded-block'],
    ['rounded-control', 'rounded-pill'],
    ['shadow-raised', 'shadow-sticky'],
    ['tracking-caps', 'tracking-normal'],
    ['ease-fast', 'ease-linear'],
    ['animate-appear', 'animate-none'],
  ])('%s уступает %s', (own, outer) => {
    expect(cn(own, outer)).toBe(outer);
  });

  it('радиус и тень не путаются с цветом', () => {
    expect(cn('rounded-mark border-line', 'rounded-block')).toBe('border-line rounded-block');
    expect(cn('shadow-raised', 'shadow-danger-line')).toBe('shadow-raised shadow-danger-line');
  });
});
