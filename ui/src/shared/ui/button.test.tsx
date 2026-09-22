import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { Button } from './button';
import { controlSize } from './control-size';

/**
 * Состояния кнопки различаются классами утилит: в jsdom вёрстки нет, и вычисленный
 * цвет там всё равно был бы пустым — `var()` он не разворачивает. Поэтому проверяется
 * то, что действительно решается здесь: что у каждого состояния есть своё правило и
 * что запрет выражен не прозрачностью. Живые цвета меряет сквозной тест в браузере.
 */
function classesOf(name: string): string[] {
  return screen.getByRole('button', { name }).className.split(/\s+/).filter(Boolean);
}

/** Классы, включающиеся в названном состоянии: у Tailwind состояние — приставка. */
function inState(classes: string[], state: string): string[] {
  return classes.filter((klass) => klass.startsWith(`${state}:`));
}

describe('кнопка', () => {
  /*
   * Подписи взяты из словаря, а не набраны здесь: кнопке всё равно, что на ней
   * написано, но набранная строкой русская подпись — это подпись мимо словаря,
   * и отличить её от настоящей в поиске нечем.
   */
  it.each([
    ['primary', 'answer.submit'],
    ['quiet', 'receipt.close'],
  ] as const)('в тоне %s различает покой, наведение, фокус и запрет', (tone, key) => {
    const label = say.ui(key);
    render(
      <Button tone={tone} disabled>
        {label}
      </Button>,
    );

    const classes = classesOf(label);

    // Покой: заливка или контур названы без приставки состояния.
    expect(classes.some((klass) => /^(bg|text|border)-/.test(klass))).toBe(true);
    expect(inState(classes, 'enabled:hover')).not.toHaveLength(0);
    expect(inState(classes, 'focus-visible')).not.toHaveLength(0);
    expect(inState(classes, 'disabled')).not.toHaveLength(0);
  });

  it('в разных тонах красится по-разному', () => {
    const label = say.ui('answer.submit');
    const { rerender } = render(<Button tone="primary">{label}</Button>);
    const primary = classesOf(label);

    rerender(<Button tone="quiet">{label}</Button>);
    const quiet = classesOf(label);

    expect(primary).not.toEqual(quiet);
  });

  it('запрет несёт атрибут и свой цвет, а не прозрачность', () => {
    const label = say.ui('answer.submit');
    render(<Button disabled>{label}</Button>);

    const button = screen.getByRole('button', { name: label });
    expect(button).toBeDisabled();

    const classes = classesOf(label);
    // Прозрачность смешивает текст с фоном и роняет контраст ниже AA
    // (`docs/notes/ui.md`, «Прозрачность поверх цветной поверхности»).
    expect(classes.filter((klass) => /(^|:)opacity-/.test(klass))).toHaveLength(0);
    expect(inState(classes, 'disabled').some((klass) => /(bg|text|border)-/.test(klass))).toBe(
      true,
    );
  });

  it('класс места вызова перебивает свой, а не встаёт рядом', () => {
    const label = say.ui('answer.submit');
    render(<Button className="px-1">{label}</Button>);

    const classes = classesOf(label);
    expect(classes).toContain('px-1');
    expect(classes).not.toContain('px-4');
  });

  /*
   * Размер — вариант по общей шкале, а не классы места вызова (UI-128): кнопка несёт
   * ровно минимум высоты и кегль своего размера, и тот же минимум у переключателя вида
   * (`segmented-nav.test.tsx`). Классы места вызова вроде `px-2 py-1 text-meta` давали
   * каждому месту свою высоту.
   */
  it.each(['sm', 'md'] as const)('размер %s берёт высоту и кегль из общей шкалы', (size) => {
    const label = say.ui('answer.submit');
    render(<Button size={size}>{label}</Button>);

    const classes = classesOf(label);
    for (const klass of controlSize[size].split(' ')) expect(classes).toContain(klass);
  });

  it('по умолчанию обычного размера', () => {
    const label = say.ui('answer.submit');
    render(<Button>{label}</Button>);

    expect(classesOf(label)).toContain('min-h-(--ui-control)');
  });
});
