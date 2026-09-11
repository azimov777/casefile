import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { Input } from './input';

/** Классы поля: состояния Tailwind различаются приставкой, покой идёт без неё. */
function classesOf(): string[] {
  return screen.getByRole('textbox').className.split(/\s+/).filter(Boolean);
}

function inState(classes: string[], state: string): string[] {
  return classes.filter((klass) => klass.startsWith(`${state}:`));
}

describe('поле ввода', () => {
  it('различает покой, наведение, фокус, отказ и запрет', () => {
    render(<Input aria-label={say.login('tokenLabel')} />);

    const classes = classesOf();
    expect(classes.some((klass) => /^(bg|text|border)-/.test(klass))).toBe(true);
    expect(inState(classes, 'enabled:hover')).not.toHaveLength(0);
    expect(inState(classes, 'focus-visible')).not.toHaveLength(0);
    expect(inState(classes, 'aria-invalid')).not.toHaveLength(0);
    expect(inState(classes, 'disabled')).not.toHaveLength(0);
  });

  it('запрет несёт атрибут и свой цвет, а не прозрачность', () => {
    render(<Input aria-label={say.login('tokenLabel')} disabled />);

    expect(screen.getByRole('textbox')).toBeDisabled();

    const classes = classesOf();
    expect(classes.filter((klass) => /(^|:)opacity-/.test(klass))).toHaveLength(0);
    expect(inState(classes, 'disabled').some((klass) => /(bg|text|border)-/.test(klass))).toBe(
      true,
    );
  });

  it('отказ виден и без цвета: он объявлен атрибутом', () => {
    render(<Input aria-label={say.login('tokenLabel')} aria-invalid />);

    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true');
  });

  it('класс места вызова перебивает свой', () => {
    render(<Input aria-label={say.login('tokenLabel')} className="px-1" />);

    const classes = classesOf();
    expect(classes).toContain('px-1');
    expect(classes).not.toContain('px-3');
  });
});
