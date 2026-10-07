import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Archive, Pencil } from 'lucide-react';
import { ActionMenu, ActionMenuItems } from './action-menu';

/*
 * Меню «⋯» (TRK-618). Пункты проверяются без всплывающего слоя: `Popover` Radix в jsdom
 * раскрывается секундами (замер TRK-618 — около 9 с на открытие голой панели). Открытие,
 * `Esc` и возврат фокуса проверяют сквозные тесты экрана проекта в настоящем браузере.
 */

describe('меню действий', () => {
  it('кнопка «⋯» названа для диктора и закрыта, пункты не стоят на странице', () => {
    render(
      <ActionMenu
        label="Действия с проектом DEMO"
        items={[{ id: 'edit', label: 'Изменить', icon: Pencil, onSelect: () => {} }]}
      />,
    );

    const button = screen.getByRole('button', { name: 'Действия с проектом DEMO' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Изменить' })).toBeNull();
  });

  it('пункты — кнопки с подписями по порядку; выбор сперва закрывает меню, потом делает своё', async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    render(
      <ActionMenuItems
        items={[
          { id: 'edit', label: 'Изменить', icon: Pencil, onSelect: () => calls.push('edit') },
          { id: 'archive', label: 'В архив', icon: Archive, onSelect: () => calls.push('archive') },
        ]}
        onChoose={() => calls.push('close')}
      />,
    );

    const list = screen.getByRole('list');
    expect(
      within(list)
        .getAllByRole('button')
        .map((item) => item.textContent),
    ).toEqual(['Изменить', 'В архив']);
    // Роли меню нет: стрелочной навигации у пунктов нет, и роль обещала бы её.
    expect(screen.queryByRole('menu')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'В архив' }));
    expect(calls).toEqual(['close', 'archive']);
  });
});
