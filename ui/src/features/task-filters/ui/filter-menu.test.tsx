import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { say } from '@testing/say';
import { EMPTY_FILTERS, type TaskFilters } from '../model/filters';
import { FilterMenu } from './filter-menu';

/*
 * Панель проверяется сама по себе, без всплывающего слоя: `Popover` Radix в jsdom
 * раскрывается десятки секунд, если вообще раскрывается (`docs/notes/testing.md`,
 * «Выпадающий список Radix в jsdom не открывается вовсе»). Открытие панели, `Esc` и
 * возврат фокуса проверяет сквозной `e2e/filters.spec.ts` в настоящем браузере.
 */
function renderMenu(filters: Partial<TaskFilters> = {}, board = false) {
  const onApply = vi.fn();
  const onAssignee = vi.fn();
  render(
    <FilterMenu
      filters={{ ...EMPTY_FILTERS, ...filters }}
      board={board}
      assignee={filters.assignee ?? ''}
      pending={false}
      onAssignee={onAssignee}
      onApply={onApply}
    />,
  );
  return { onApply, onAssignee };
}

/** Переключатель назван так же, как знак в строке списка: родом и значением. */
function toggle(kind: 'statusLabel' | 'priorityLabel', value: string) {
  return screen.getByRole('button', { name: `${say.ui(`task.${kind}`)} ${value}` });
}

describe('панель «Фильтр»', () => {
  it('показывает отбор из адреса нажатыми переключателями и полем исполнителя', () => {
    renderMenu({ status: ['open'], priority: ['high'], withQuestions: true, assignee: 'owner' });

    expect(toggle('statusLabel', 'open')).toHaveAttribute('aria-pressed', 'true');
    expect(toggle('statusLabel', 'in_progress')).toHaveAttribute('aria-pressed', 'false');
    expect(toggle('priorityLabel', 'high')).toHaveAttribute('aria-pressed', 'true');
    expect(
      screen.getByRole('button', { name: say.tasks('filters.withQuestions') }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText(say.tasks('filters.assignee'))).toHaveValue('owner');
  });

  it('нажатие применяет условие сразу, добавляя значение к уже выбранным', async () => {
    const user = userEvent.setup();
    const { onApply } = renderMenu({ priority: ['high'] });

    await user.click(toggle('priorityLabel', 'critical'));
    expect(onApply).toHaveBeenLastCalledWith({ priority: ['high', 'critical'] });

    await user.click(toggle('statusLabel', 'in_progress'));
    expect(onApply).toHaveBeenLastCalledWith({ status: ['in_progress'] });
  });

  it('статуса ожидания среди статусов нет: «Ждёт ответа» — столбец доски, а не статус', () => {
    renderMenu({});

    // Хранимый статус снят бэкендом (TRK-573): отбор `status: waiting` он бы отклонил.
    expect(
      screen.queryByRole('button', { name: `${say.ui('task.statusLabel')} waiting` }),
    ).not.toBeInTheDocument();
    expect(toggle('statusLabel', 'open')).toBeInTheDocument();
  });

  it('признаки уходят каждый своим полем отбора', async () => {
    const user = userEvent.setup();
    const { onApply } = renderMenu({ blocked: true });

    await user.click(screen.getByRole('button', { name: say.tasks('filters.withRemarks') }));
    expect(onApply).toHaveBeenLastCalledWith({
      blocked: true,
      withQuestions: false,
      withRemarks: true,
      withWarnings: false,
    });

    // Предупреждение (TRK-561) — тем же порядком, своим полем.
    await user.click(screen.getByRole('button', { name: say.tasks('filters.withWarnings') }));
    expect(onApply).toHaveBeenLastCalledWith({
      blocked: true,
      withQuestions: false,
      withRemarks: false,
      withWarnings: true,
    });
  });

  it('исполнитель — черновик до Enter', async () => {
    const user = userEvent.setup();
    const { onApply, onAssignee } = renderMenu();

    await user.type(screen.getByLabelText(say.tasks('filters.assignee')), 'o');
    expect(onAssignee).toHaveBeenLastCalledWith('o');
    expect(onApply).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(onApply).toHaveBeenCalledWith({});
  });

  it('на доске статуса в панели нет: статус там — столбец', () => {
    renderMenu({}, true);

    expect(screen.queryByText(say.tasks('filters.statusLegend'))).toBeNull();
    expect(toggle('priorityLabel', 'high')).toBeInTheDocument();
  });
});
