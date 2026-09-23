import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { say } from '@testing/say';
import { ENTRY_TYPES, isServiceEntry, type EntryType } from '@/entities/entry';
import { CaseFilterMenu } from './case-filter-menu';

/*
 * Панель проверяется сама по себе, без всплывающего слоя: `Popover` Radix в jsdom
 * раскрывается десятки секунд, если вообще раскрывается (`docs/notes/testing.md`).
 * Открытие панели, `Esc` и возврат фокуса проверяет сквозной `e2e/case-latest.spec.ts`.
 */
function renderMenu(selected: EntryType[] = []) {
  const onChange = vi.fn();
  render(<CaseFilterMenu selected={selected} onChange={onChange} />);
  return { onChange };
}

function typeToggle(type: EntryType) {
  return screen.getByRole('button', { name: type });
}

const AGENT_TYPES = ENTRY_TYPES.filter((type) => !isServiceEntry(type));
const SERVICE_TYPES = ENTRY_TYPES.filter(isServiceEntry);

describe('панель «Фильтр» отбора записей дела', () => {
  it('показывает отбор нажатыми переключателями, каждый тип — своей кнопкой', () => {
    renderMenu(['summary', 'created']);

    expect(typeToggle('summary')).toHaveAttribute('aria-pressed', 'true');
    expect(typeToggle('decision')).toHaveAttribute('aria-pressed', 'false');
    expect(typeToggle('created')).toHaveAttribute('aria-pressed', 'true');
    // Все восемнадцать типов контракта стоят в панели, каждый своей кнопкой.
    for (const type of ENTRY_TYPES) expect(typeToggle(type)).toBeInTheDocument();
  });

  it('нажатие применяет тип сразу, добавляя его к уже выбранным своей группы', async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu(['summary']);

    await user.click(typeToggle('decision'));
    expect(onChange).toHaveBeenLastCalledWith(['summary', 'decision']);
  });

  it('снятый тип уходит из отбора, соседние типы остаются', async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu(['summary', 'decision']);

    await user.click(typeToggle('summary'));
    expect(onChange).toHaveBeenLastCalledWith(['decision']);
  });

  it('подпись группы ставит её целиком, не трогая отбор другой группы', async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu(['created']);

    await user.click(screen.getByRole('button', { name: say.case('filters.agentEntries') }));
    expect(onChange).toHaveBeenLastCalledWith(expect.arrayContaining([...AGENT_TYPES, 'created']));
    const applied = onChange.mock.calls.at(-1)?.[0] as EntryType[];
    expect(applied).toHaveLength(AGENT_TYPES.length + 1);
  });

  it('подпись полностью выбранной группы снимает её целиком, не трогая другую', async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu([...SERVICE_TYPES, 'summary']);

    await user.click(screen.getByRole('button', { name: say.case('filters.serviceEntries') }));
    expect(onChange).toHaveBeenLastCalledWith(['summary']);
  });
});
