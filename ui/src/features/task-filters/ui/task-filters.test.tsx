import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { say } from '@testing/say';
import { EMPTY_FILTERS, type TaskFilters } from '../model/filters';
import { TaskFiltersForm } from './task-filters';

function form(filters: TaskFilters) {
  return <TaskFiltersForm filters={filters} onApply={vi.fn()} onReset={vi.fn()} problem={null} />;
}

describe('форма отбора', () => {
  it('напечатанное не стирается новым объектом отбора с теми же значениями (TRK-423)', async () => {
    const user = userEvent.setup();
    const { rerender } = render(form({ ...EMPTY_FILTERS }));

    const field = screen.getByLabelText(say.tasks('filters.text'));
    await user.type(field, 'токен');

    // Адрес фиксируется позже нажатия соседнего условия: приходит новый объект
    // отбора, в котором текст прежний, а изменилось другое поле.
    rerender(form({ ...EMPTY_FILTERS, withQuestions: true }));
    expect(field).toHaveValue('токен');
  });

  it('значение, изменившееся мимо формы, поле перечитывает', () => {
    const { rerender } = render(form({ ...EMPTY_FILTERS, text: 'старое' }));
    rerender(form({ ...EMPTY_FILTERS, text: 'новое' }));

    expect(screen.getByLabelText(say.tasks('filters.text'))).toHaveValue('новое');
  });
});
