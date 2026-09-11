import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { ENTRY_TYPES } from '../api/entries';
import { EntryKind } from './entry-kind';

/** Рисунок знака: по нему и сравниваются рода записей. */
function shapeOf(container: HTMLElement): string {
  const svg = container.querySelector('svg');
  if (svg === null) throw new Error('У знака нет рисунка');
  return svg.innerHTML;
}

describe('знак рода записи', () => {
  it('есть у каждого типа из контракта, и два типа не делят один знак', () => {
    // Список берётся из контракта: тип, добавленный в него, обязан уронить сборку
    // на `satisfies Record<EntryType, …>`, а не тихо получить знак по умолчанию.
    const shapes = ENTRY_TYPES.map((type) => {
      const { container, unmount } = render(<EntryKind type={type} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });

    expect(shapes).toHaveLength(ENTRY_TYPES.length);
    expect(new Set(shapes).size).toBe(ENTRY_TYPES.length);
  });

  it('идентификатор контракта остаётся словом на экране, а род — в доступном имени', () => {
    const { container } = render(<EntryKind type="section_changed" />);

    // Знак дополняет слово, а не заменяет его: `section_changed` — то же, что видит агент.
    expect(container).toHaveTextContent('section_changed');
    // Вслух `section_changed` не читается, поэтому рядом стоит название словами —
    // из словаря тем же ключом, каким его зовёт компонент.
    expect(container).toHaveTextContent(say.ui('entry.type.section_changed'));
  });

  it('без подписи род не пропадает: он уходит в доступное имя', () => {
    const { container } = render(<EntryKind type="verdict" withName={false} />);

    expect(container).toHaveTextContent(say.ui('entry.type.verdict'));
    expect(container.querySelector('svg')).not.toBeNull();
  });
});
