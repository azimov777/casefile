import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  decisionRow,
  decisionsPage,
  entryOfType,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

type DecisionRow = components['schemas']['DecisionListRead'];

/*
 * Вкладка «Решения» проекта (TRK-554, TRK-758): список решений проекта и его областей с
 * отбором, метками «подтверждено» и «не подтверждено» и четырьмя действиями проверки.
 */

let rows: DecisionRow[] = [];
let reviews: { path: string; body: { outcome: string; reason: string } }[] = [];
let filed: { path: string; body: Record<string, unknown> }[] = [];
let refusal: string | null = null;

/** Тело решения в деле проекта: раскрытая строка читает его записью дела. */
function record(no: number) {
  return {
    ...entryOfType(no, 'DEMO', 'decision'),
    task_key: null,
    project_key: 'DEMO',
    title: `Решение ${no}`,
    body: `Тело решения ${no}.`,
  } as components['schemas']['EntryRead'];
}

function serve(archived = false) {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () =>
      data(
        projectDetail('DEMO', {
          archived_at: archived ? '2026-10-06T10:00:00Z' : null,
          unconfirmed_decisions: rows.filter(
            (row) => row.status === 'in_force' && row.review_state === 'unconfirmed',
          ).length,
        }),
      ),
    ),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/areas`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/entries/:no`, ({ params }) =>
      data(record(Number(params.no))),
    ),
    // Счётчики шапки (TRK-619) читают список задач; их числа здесь не проверяются.
    http.get(`${API}/api/v1/tasks`, () => collection([], { total: 0 })),
    http.get(`${API}/api/v1/decisions`, () => decisionsPage(rows)),
    http.post(`${API}/api/v1/projects/DEMO/decisions/:no/review`, async ({ params, request }) => {
      if (refusal !== null) return failure(refusal, 409);
      const body = (await request.json()) as { outcome: string; reason: string };
      reviews.push({ path: new URL(request.url).pathname, body });
      const row = rows.find((item) => item.ref === `DEMO#${String(params.no)}`);
      if (row !== undefined) {
        if (body.outcome === 'confirmed') row.review_state = 'confirmed';
        else row.status = body.outcome === 'rejected' ? 'rejected' : 'removed';
      }
      return data(record(99), 201);
    }),
    http.post(`${API}/api/v1/projects/DEMO/entries`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      filed.push({ path: new URL(request.url).pathname, body });
      return data(record(9), 201);
    }),
  );
}

/** Открывает экран на вкладке «Решения» и раскрывает строку решения. */
async function openRow(ref: string, path = '/projects/DEMO?tab=decisions') {
  const user = userEvent.setup();
  renderApp(path);
  const row = await screen.findByText(
    (_, element) => element?.getAttribute('data-decision') === ref,
  );
  await user.click(row.querySelector('button[aria-expanded]') as HTMLElement);
  return { user, row };
}

beforeEach(() => {
  setToken('trk_test');
  reviews = [];
  filed = [];
  refusal = null;
  rows = [
    decisionRow('DEMO#3', { title: 'Ветки сливаются скриптом', tasks: 2, refs: ['DEMO-4#2'] }),
    decisionRow('DEMO#4', { title: 'Тесты в контейнере', review_state: 'confirmed' }),
    decisionRow('DEMO#5', {
      title: 'Слияние ручное',
      status: 'rejected',
    }),
    decisionRow('DEMO#7', {
      title: 'Решение о переименовании',
      supersedes: ['DEMO#2'],
      tasks: 1,
    }),
    decisionRow('DEMO#2', {
      title: 'Прежнее имя',
      status: 'superseded',
      superseded_by: 'DEMO#7',
    }),
  ];
});

describe('вкладка «Решения» проекта', () => {
  it('неподтверждённое — метка и четыре действия; подтверждённое — три без «Подтвердить»; отклонённое — плашка и ни одного действия', async () => {
    serve();
    const { row: unconfirmed } = await openRow('DEMO#3');
    expect(unconfirmed).toHaveTextContent(say.decisions('mark.unconfirmed'));
    const actions = within(unconfirmed).getByRole('group', {
      name: say.decisions('row.actions', { ref: 'DEMO#3' }),
    });
    expect(
      within(actions)
        .getAllByRole('button')
        .map((button) => button.getAttribute('data-action')),
    ).toEqual(['confirm', 'revise', 'reject', 'remove']);
    expect(await within(unconfirmed).findByText('Тело решения 3.')).toBeInTheDocument();

    const { row: confirmed } = await openRow('DEMO#4');
    expect(confirmed).toHaveTextContent(say.decisions('mark.confirmed'));
    const confirmedActions = within(confirmed).getByRole('group');
    expect(
      within(confirmedActions)
        .getAllByRole('button')
        .map((button) => button.getAttribute('data-action')),
    ).toEqual(['revise', 'reject', 'remove']);
  });

  it('отклонённое в «Показать снятые» — плашка «отклонено» и ни одного действия', async () => {
    serve();
    renderApp('/projects/DEMO?tab=decisions&show=removed');

    const row = await screen.findByText(
      (_, element) => element?.getAttribute('data-decision') === 'DEMO#5',
    );
    expect(row).toHaveTextContent(say.ui('decision.status.rejected'));
    const user = userEvent.setup();
    await user.click(row.querySelector('button[aria-expanded]') as HTMLElement);
    expect(await within(row).findByText('Тело решения 5.')).toBeInTheDocument();
    expect(within(row).queryByRole('group')).toBeNull();
    // Заменённое — в той же выдаче, со ссылкой на преемника без плашки действий.
    const old = screen.getByText(
      (_, element) => element?.getAttribute('data-decision') === 'DEMO#2',
    );
    expect(old).toHaveTextContent(`${say.decisions('row.supersededBy')} DEMO#7`);
  });

  it('отбор живёт в адресе: «Не подтверждены» — только действующие непроверенные', async () => {
    serve();
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=decisions');

    const nav = await screen.findByRole('navigation', { name: say.decisions('filter.label') });
    // Действующих четыре: 3, 4, 7 и… 5 отклонено, 2 заменено — остаются 3, 4, 7.
    expect(
      within(nav).getByRole('link', {
        name: new RegExp(`${say.decisions('filter.inForce')}\\s*3`),
      }),
    ).toHaveAttribute('aria-current', 'true');
    await user.click(
      within(nav).getByRole('link', {
        name: new RegExp(`${say.decisions('filter.unconfirmed')}\\s*2`),
      }),
    );

    expect(address.current).toBe('/projects/DEMO?tab=decisions&show=unconfirmed');
    const list = await screen.findByRole('list', { name: say.decisions('list') });
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.getAttribute('data-decision')),
    ).toEqual(['DEMO#3', 'DEMO#7']);
  });

  it('«Подтвердить» уходит сразу, без окна, и решение пропадает из отбора', async () => {
    serve();
    const { user, row } = await openRow('DEMO#3', '/projects/DEMO?tab=decisions&show=unconfirmed');

    await user.click(
      within(row).getByRole('button', {
        name: say.decisions('action.confirmLabel', { ref: 'DEMO#3' }),
      }),
    );

    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]).toEqual({
      path: '/api/v1/projects/DEMO/decisions/3/review',
      body: { outcome: 'confirmed', reason: '' },
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() =>
      expect(
        screen.queryByText((_, element) => element?.getAttribute('data-decision') === 'DEMO#3'),
      ).toBeNull(),
    );
    expect(screen.getByText(say.decisions('row.reviewed'))).toBeInTheDocument();
  });

  it('«Отклонить» у решения, что заменило другое, говорит: прежнее не вернётся, и называет задачи', async () => {
    serve();
    const { user, row } = await openRow('DEMO#7');

    await user.click(
      within(row).getByRole('button', {
        name: say.decisions('action.rejectLabel', { ref: 'DEMO#7' }),
      }),
    );

    const dialog = await screen.findByRole('alertdialog', {
      name: say.decisions('take.reject.title', { ref: 'DEMO#7' }),
    });
    expect(dialog).toHaveTextContent(say.decisions('take.replacedOne', { refs: 'DEMO#2' }));
    expect(dialog).toHaveTextContent(say.decisions('take.tasks', { count: 1 }));

    await user.type(
      within(dialog).getByLabelText(say.decisions('take.reasonLabel')),
      'Не согласен',
    );
    await user.click(
      within(dialog).getByRole('button', { name: say.decisions('take.reject.submit') }),
    );

    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]?.body).toEqual({ outcome: 'rejected', reason: 'Не согласен' });
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });

  it('«Удалить» без замены предка не предупреждает, причина необязательна', async () => {
    serve();
    const { user, row } = await openRow('DEMO#4');

    await user.click(
      within(row).getByRole('button', {
        name: say.decisions('action.removeLabel', { ref: 'DEMO#4' }),
      }),
    );
    const dialog = await screen.findByRole('alertdialog', {
      name: say.decisions('take.remove.title', { ref: 'DEMO#4' }),
    });
    expect(dialog).not.toHaveTextContent(say.decisions('take.replacedOne', { refs: 'DEMO#2' }));
    await user.click(
      within(dialog).getByRole('button', { name: say.decisions('take.remove.submit') }),
    );

    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]?.body).toEqual({ outcome: 'removed', reason: '' });
  });

  it('«Исправить» — форма с текущим текстом; отправка создаёт решение с `supersedes` прежнего', async () => {
    serve();
    const { user, row } = await openRow('DEMO#3');

    await user.click(
      within(row).getByRole('button', {
        name: say.decisions('action.reviseLabel', { ref: 'DEMO#3' }),
      }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: say.decisions('revise.title', { ref: 'DEMO#3' }),
    });
    const title = await within(dialog).findByLabelText(say.decisions('revise.titleLabel'));
    expect(title).toHaveValue('Ветки сливаются скриптом');
    expect(within(dialog).getByLabelText(say.decisions('revise.bodyLabel'))).toHaveValue(
      'Тело решения 3.',
    );

    await user.clear(title);
    await user.type(title, 'Ветки сливает координатор');
    await user.click(within(dialog).getByRole('button', { name: say.decisions('revise.submit') }));

    await waitFor(() => expect(filed).toHaveLength(1));
    expect(filed[0]).toEqual({
      path: '/api/v1/projects/DEMO/entries',
      body: {
        type: 'decision',
        title: 'Ветки сливает координатор',
        body: 'Тело решения 3.',
        supersedes: [3],
      },
    });
  });

  it('отказ бэкенда виден рядом с действием, а не теряется', async () => {
    serve();
    refusal = 'decision_not_in_force';
    const { user, row } = await openRow('DEMO#3');

    await user.click(
      within(row).getByRole('button', {
        name: say.decisions('action.confirmLabel', { ref: 'DEMO#3' }),
      }),
    );

    expect(await within(row).findByRole('alert')).toBeInTheDocument();
    expect(reviews).toHaveLength(0);
  });

  it('у архивного проекта действий проверки нет вовсе', async () => {
    serve(true);
    const { row } = await openRow('DEMO#3');
    expect(await within(row).findByText('Тело решения 3.')).toBeInTheDocument();
    expect(within(row).queryByRole('group')).toBeNull();
  });

  it('пустое состояние сказано словами', async () => {
    rows = [];
    serve();
    renderApp('/projects/DEMO?tab=decisions');
    expect(await screen.findByText(say.decisions('empty.inForce'))).toBeInTheDocument();
  });

  it('ссылка решения открывает «Дело» с раскрытой записью', async () => {
    serve();
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=decisions');
    const link = await screen.findByRole('link', { name: 'DEMO#3' });
    await user.click(link);
    expect(address.current).toBe('/projects/DEMO?entry=3');
  });
});
