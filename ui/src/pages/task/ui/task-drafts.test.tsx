import { http } from 'msw';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  entryOfType,
  heading,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

type Entry = components['schemas']['EntryRead'];

/** Адреса чтений дела: по ним видно, что решения и находки читаются одним запросом. */
let reads: string[] = [];

beforeEach(() => {
  reads = [];
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
  setToken('trk_test');
});

/** Решение или находка дела задачи; `draftFor` задаёт адрес подъёма, `null` — обычная запись. */
function draft(
  no: number,
  type: 'decision' | 'finding',
  draftFor: string | null,
  liftedBy: string[] | null,
): Entry {
  return {
    ...entryOfType(no, 'DEMO-1', type),
    type,
    payload: { supersedes: [], draft_for: draftFor },
    lifted_by: liftedBy,
  } as unknown as Entry;
}

function serve(drafts: Entry[], openDrafts: number) {
  server.use(
    http.get(`${API}/api/v1/tasks/DEMO-1`, () =>
      data(
        taskPackage('DEMO-1', {
          features: {
            blocked: false,
            deferred: false,
            open_questions: 0,
            open_blocking_questions: 0,
            open_remarks: 0,
            open_warnings: 0,
            open_drafts: openDrafts,
            last_summary_at: null,
            last_entry_at: null,
          },
          index: [
            heading(1, { type: 'decision' }, 'Решение для ядра'),
            heading(2, { type: 'finding' }, 'Находка для интерфейса'),
            heading(3, { type: 'decision' }, 'Обычное решение'),
          ],
        }),
      ),
    ),
    http.get(`${API}/api/v1/tasks/DEMO-1/entries`, ({ request }) => {
      reads.push(request.url);
      return collection(drafts);
    }),
  );
}

describe('черновики знания на карточке задачи (TRK-661)', () => {
  it('неподнятый черновик назван адресом и словами «не поднят», поднятый — ссылкой на запись адресата', async () => {
    serve(
      [
        draft(1, 'decision', 'DEMO/core', ['DEMO/core#4']),
        draft(2, 'finding', 'DEMO/ui', []),
        // Не черновик: решение без адреса подъёма пометки не получает.
        draft(3, 'decision', null, null),
      ],
      1,
    );

    renderApp('/tasks/DEMO-1');
    const table = await screen.findByRole('table');

    const open = await within(table).findByText(say.ui('draft.open', { address: 'DEMO/ui' }));
    expect(open.closest('[data-draft]')).toHaveAttribute('data-draft', 'open');

    const lifted = within(table).getByText(say.ui('draft.lifted'));
    const mark = lifted.closest('[data-draft]') as HTMLElement;
    expect(mark).toHaveAttribute('data-draft', 'lifted');
    // Ссылка ведёт на запись адресата: решение области открывается на странице области.
    expect(within(mark).getByRole('link', { name: 'DEMO/core#4' })).toHaveAttribute(
      'href',
      '/projects/DEMO/areas/core?entry=4',
    );

    expect(table.querySelectorAll('[data-draft]')).toHaveLength(2);

    // Решения и находки читаются одним запросом с двумя типами, а не телом за телом.
    expect(reads).toHaveLength(1);
    expect(new URL(reads[0] as string).searchParams.getAll('types')).toEqual([
      'decision',
      'finding',
    ]);
  });

  it('признак с числом неподнятых стоит в шапке задачи', async () => {
    serve([draft(2, 'finding', 'DEMO/ui', [])], 1);

    renderApp('/tasks/DEMO-1');
    const title = await screen.findByRole('heading', { name: /DEMO-1/ });
    const header = title.closest('header') as HTMLElement;

    expect(
      within(header).getByRole('button', { name: say.ui('task.features.drafts', { count: 1 }) }),
    ).toBeInTheDocument();
  });

  it('когда всё поднято, признака в шапке нет', async () => {
    serve([draft(1, 'decision', 'DEMO/core', ['DEMO/core#4'])], 0);

    renderApp('/tasks/DEMO-1');
    const title = await screen.findByRole('heading', { name: /DEMO-1/ });
    const header = title.closest('header') as HTMLElement;

    expect(within(header).queryByText(say.ui('task.features.drafts', { count: 0 }))).toBeNull();
    expect(
      within(header).queryByRole('button', { name: /knowledge|знани/i }),
    ).not.toBeInTheDocument();
  });
});
