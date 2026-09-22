import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { controlSize } from './control-size';
import { SegmentedNav, SegmentedNavLink } from './segmented-nav';

/**
 * Переключатель вида остаётся навигацией (UI-128): виды — ссылки с адресом, текущий
 * назван `aria-current`, а не `aria-checked` радиогруппы. Высота — из той же шкалы,
 * что у кнопки (`button.test.tsx`).
 */
function renderSwitch(size?: 'sm' | 'md') {
  return render(
    <MemoryRouter>
      <SegmentedNav label={say.ui('task.nav.view')} size={size}>
        <SegmentedNavLink to="/tasks/DEMO-1" current="page">
          {say.ui('task.nav.card')}
        </SegmentedNavLink>
        <SegmentedNavLink to="/tasks/DEMO-1/case" current={false}>
          {say.ui('task.nav.case')}
        </SegmentedNavLink>
      </SegmentedNav>
    </MemoryRouter>,
  );
}

describe('переключатель вида', () => {
  it('это ориентир навигации со ссылками, а не радиогруппа', () => {
    renderSwitch();

    const nav = screen.getByRole('navigation', { name: say.ui('task.nav.view') });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/tasks/DEMO-1',
      '/tasks/DEMO-1/case',
    ]);
    expect(within(nav).queryByRole('radio')).toBeNull();
  });

  it('текущий вид назван `aria-current` тем словом, которое дали, остальные — никак', () => {
    renderSwitch();

    expect(screen.getByRole('link', { name: say.ui('task.nav.card') })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: say.ui('task.nav.case') })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it.each(['sm', 'md'] as const)('размер %s берёт высоту и кегль из шкалы кнопки', (size) => {
    renderSwitch(size);

    const classes = screen
      .getByRole('navigation', { name: say.ui('task.nav.view') })
      .className.split(/\s+/);
    for (const klass of controlSize[size].split(' ')) expect(classes).toContain(klass);
  });
});
