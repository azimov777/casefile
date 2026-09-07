import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from './button';

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
  it.each([
    ['primary', 'Ответить'],
    ['quiet', 'Отмена'],
  ] as const)('в тоне %s различает покой, наведение, фокус и запрет', (tone, label) => {
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
    const { rerender } = render(<Button tone="primary">Ответить</Button>);
    const primary = classesOf('Ответить');

    rerender(<Button tone="quiet">Ответить</Button>);
    const quiet = classesOf('Ответить');

    expect(primary).not.toEqual(quiet);
  });

  it('запрет несёт атрибут и свой цвет, а не прозрачность', () => {
    render(<Button disabled>Ответить</Button>);

    const button = screen.getByRole('button', { name: 'Ответить' });
    expect(button).toBeDisabled();

    const classes = classesOf('Ответить');
    // Прозрачность смешивает текст с фоном и роняет контраст ниже AA
    // (`docs/notes/ui.md`, «Прозрачность поверх цветной поверхности»).
    expect(classes.filter((klass) => /(^|:)opacity-/.test(klass))).toHaveLength(0);
    expect(inState(classes, 'disabled').some((klass) => /(bg|text|border)-/.test(klass))).toBe(
      true,
    );
  });

  it('класс места вызова перебивает свой, а не встаёт рядом', () => {
    render(<Button className="px-1">Ответить</Button>);

    const classes = classesOf('Ответить');
    expect(classes).toContain('px-1');
    expect(classes).not.toContain('px-4');
  });
});
