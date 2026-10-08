import { http } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { API, collection, areaCard } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';
import { EMPTY_FILTERS, type TaskFilters } from '../model/filters';
import { FilterMenu } from './filter-menu';

/*
 * Панель проверяется сама по себе, без всплывающего слоя: `Popover` Radix в jsdom
 * раскрывается десятки секунд, если вообще раскрывается (`TRK/ui-testing#21`,
 * «Выпадающий список Radix в jsdom не открывается вовсе»). Открытие панели, `Esc` и
 * возврат фокуса проверяет сквозной `e2e/filters.spec.ts` в настоящем браузере.
 */
function renderMenu(filters: Partial<TaskFilters> = {}, board = false) {
  const onApply = vi.fn();
  const onAssignee = vi.fn();
  // Области проекта панель читает сама (TRK-557): без проекта запроса нет вовсе, а
  // клиент запросов нужен хуку и тогда.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FilterMenu
        filters={{ ...EMPTY_FILTERS, ...filters }}
        board={board}
        assignee={filters.assignee ?? ''}
        pending={false}
        onAssignee={onAssignee}
        onApply={onApply}
      />
    </QueryClientProvider>,
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
      withDrafts: false,
      withWaiting: false,
    });

    // Предупреждение (TRK-561) — тем же порядком, своим полем.
    await user.click(screen.getByRole('button', { name: say.tasks('filters.withWarnings') }));
    expect(onApply).toHaveBeenLastCalledWith({
      blocked: true,
      withQuestions: false,
      withRemarks: false,
      withWarnings: true,
      withDrafts: false,
      withWaiting: false,
    });
  });

  it('«есть неподнятое знание» (TRK-661) уходит своим полем отбора', async () => {
    const user = userEvent.setup();
    const { onApply } = renderMenu({});

    await user.click(screen.getByRole('button', { name: say.tasks('filters.withDrafts') }));
    expect(onApply).toHaveBeenLastCalledWith({
      blocked: false,
      withQuestions: false,
      withRemarks: false,
      withWarnings: false,
      withDrafts: true,
      withWaiting: false,
    });
  });

  it('«ждёт ответа» (TRK-577) уходит своим полем отбора', async () => {
    const user = userEvent.setup();
    const { onApply } = renderMenu({});

    await user.click(screen.getByRole('button', { name: say.tasks('filters.withWaiting') }));
    expect(onApply).toHaveBeenLastCalledWith({
      blocked: false,
      withQuestions: false,
      withRemarks: false,
      withWarnings: false,
      withDrafts: false,
      withWaiting: true,
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

  it('область (TRK-557): без проекта — «любая» и «без области», выбор уходит как есть', async () => {
    const user = userEvent.setup();
    const { onApply } = renderMenu({});

    const field = screen.getByLabelText(say.tasks('filters.areaLegend'));
    expect(field).toHaveValue('');
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
      say.tasks('filters.areaAny'),
      say.tasks('filters.areaNone'),
    ]);

    await user.selectOptions(field, say.tasks('filters.areaNone'));
    expect(onApply).toHaveBeenLastCalledWith({ area: 'empty()' });
  });

  it('области проекта — с архивными и пометкой; чужой адрес из ссылки стоит своим адресом', async () => {
    setToken('trk_test');
    const seen: string[] = [];
    server.use(
      http.get(`${API}/api/v1/projects/DEMO/areas`, ({ request }) => {
        seen.push(request.url);
        return collection([
          areaCard('DEMO/promotion'),
          areaCard('DEMO/commerce', {
            title: 'Коммерция',
            archived_at: '2026-10-01T10:00:00Z',
          }),
        ]);
      }),
    );
    const user = userEvent.setup();
    const { onApply } = renderMenu({ project: 'DEMO', area: 'OPS/infra' });

    expect(
      await screen.findByRole('option', {
        name: say.tasks('filters.areaOption', {
          title: 'Популяризация',
          address: 'DEMO/promotion',
        }),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', {
        name: say.tasks('filters.areaArchived', {
          title: 'Коммерция',
          address: 'DEMO/commerce',
        }),
      }),
    ).toBeInTheDocument();
    expect(new URL(seen[0] ?? '').searchParams.get('include_archived')).toBe('true');
    expect(screen.getByLabelText(say.tasks('filters.areaLegend'))).toHaveValue('OPS/infra');

    await user.selectOptions(
      screen.getByLabelText(say.tasks('filters.areaLegend')),
      'DEMO/promotion',
    );
    expect(onApply).toHaveBeenLastCalledWith({ area: 'DEMO/promotion' });
  });
});
