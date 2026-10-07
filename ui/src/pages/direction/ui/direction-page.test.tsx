import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  directionDetail,
  entryOfType,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

/*
 * Страница направления (TRK-557): карточка, атрибуты с историей, дело направления описью
 * с телами по клику, запись человека — заметка или решение, правка и архив с причиной;
 * архивное направление и направление архивного проекта только читаются.
 */

type Entry = components['schemas']['EntryRead'];

const ADDRESS = 'DEMO/promotion';
const PATH = '/api/v1/projects/DEMO/directions/promotion';
const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-02T10:00:00Z' };

/** Запись дела направления: ни задачи, ни проекта — назван адрес направления. */
function directionEntry(no: number, type: Entry['type'], overrides: Partial<Entry> = {}): Entry {
  return {
    ...entryOfType(no, 'DEMO', type),
    task_key: null,
    project_key: null,
    direction: ADDRESS,
    ...overrides,
  } as Entry;
}

const CASE: Entry[] = [
  directionEntry(1, 'created', { title: 'Direction created', body: '' }),
  directionEntry(2, 'attribute_created', {
    payload: { name: 'channel', after: 'reddit', reason: null },
  } as Partial<Entry>),
  directionEntry(3, 'decision', {
    title: 'Пишем только в каналы, где есть агенты',
    body: 'Так решили после замера.',
  }),
];

let seen: URL[] = [];
let writes: { method: string; path: string; body: unknown }[] = [];

async function remember(request: Request): Promise<void> {
  writes.push({
    method: request.method,
    path: new URL(request.url).pathname,
    body: await request.clone().json(),
  });
}

/** Кнопка меню «⋯» в шапке страницы направления (TRK-618). */
function menuButton() {
  return screen.findByRole('button', { name: say.direction('menu.label', { address: ADDRESS }) });
}

/** Вкладка страницы направления по началу подписи. */
function tab(name: string) {
  return within(screen.getByRole('navigation', { name: say.direction('tabs.label') })).getByRole(
    'link',
    { name: new RegExp(`^${name}`) },
  );
}

function detail(overrides: Parameters<typeof directionDetail>[1] = {}) {
  return directionDetail(ADDRESS, {
    description: 'Каталоги, публикации и **день запуска**.',
    attributes: [{ name: 'channel', value: 'reddit', ...STAMPS }],
    ...overrides,
  });
}

beforeEach(() => {
  seen = [];
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO'))),
    http.get(`${API}${PATH}`, () => data(detail())),
    http.get(`${API}${PATH}/entries`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      return collection(url.searchParams.has('attribute') ? CASE.slice(1, 2) : CASE);
    }),
    http.get(`${API}${PATH}/entries/:no`, ({ params, request }) => {
      seen.push(new URL(request.url));
      const entry = CASE.find((item) => item.no === Number(params.no));
      return entry === undefined ? failure('entry_not_found', 404) : data(entry);
    }),
    http.post(`${API}${PATH}/entries`, async ({ request }) => {
      await remember(request);
      const body = (await request.clone().json()) as { type: Entry['type'] };
      return data(directionEntry(4, body.type), 201);
    }),
    http.patch(`${API}${PATH}`, async ({ request }) => {
      await remember(request);
      return data(detail());
    }),
    http.post(`${API}${PATH}/archive`, async ({ request }) => {
      await remember(request);
      return data(detail({ archived_at: '2026-10-06T10:00:00Z' }));
    }),
    http.post(`${API}${PATH}/restore`, async ({ request }) => {
      await remember(request);
      return data(detail());
    }),
  );
});

describe('страница направления', () => {
  it('показывает адрес, название, описание и опись; атрибуты — вкладкой; ссылки на проект и задачи', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/directions/promotion', { language: 'ru' });

    const title = await screen.findByRole('heading', { level: 1 });
    expect(title).toHaveTextContent(ADDRESS);
    expect(title).toHaveTextContent('Популяризация');
    expect(screen.getByText('день запуска')).toBeInTheDocument();

    // Без параметра открыто «Дело»: «Обзора» у направления нет.
    expect(tab(say.direction('tabs.case'))).toHaveAttribute('aria-current', 'true');
    const index = await screen.findByRole('table', { name: say.ui('index.count', { count: 3 }) });
    expect(
      within(index).getByRole('button', { name: /Пишем только в каналы, где есть агенты/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: say.project('attributes') })).toBeNull();

    expect(
      screen.getByRole('link', { name: say.direction('page.project', { key: 'DEMO' }) }),
    ).toHaveAttribute('href', '/projects/DEMO');
    // Задачи направления — список с отбором `direction`, тем же условием, что у агента.
    const tasks = screen.getByRole('link', { name: say.direction('page.tasks') });
    const href = new URL(tasks.getAttribute('href') ?? '', 'http://x');
    expect(href.pathname).toBe('/tasks');
    expect(href.searchParams.get('project')).toBe('DEMO');
    expect(href.searchParams.get('direction')).toBe(ADDRESS);

    // Верхняя полоса: проект, его экран ссылкой и само место. Строка имени сравнивается
    // целиком: «Проект DEMO» под карточкой с ней не совпадает.
    expect(screen.getByRole('link', { name: say.ui('app.crumbProject') })).toHaveAttribute(
      'href',
      '/projects/DEMO',
    );

    // Вкладка «Атрибуты» с числом из карточки.
    const attributesTab = tab(say.direction('tabs.attributes'));
    expect(attributesTab).toHaveAccessibleName(`${say.direction('tabs.attributes')} 1`);
    await user.click(attributesTab);
    expect(address.current).toBe('/projects/DEMO/directions/promotion?tab=attributes');
    const attributes = screen.getByRole('region', { name: say.project('attributes') });
    expect(within(attributes).getByRole('button', { name: 'channel' })).toBeInTheDocument();
    expect(within(attributes).getByText('reddit')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('`tab=decisions` у направления — «Дело»: этой вкладки у него нет', async () => {
    renderApp('/projects/DEMO/directions/promotion?tab=decisions', { language: 'ru' });

    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(tab(say.direction('tabs.case'))).toHaveAttribute('aria-current', 'true');
  });

  it('тело записи читается адресом записи направления, номер уходит в адрес страницы', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/directions/promotion');

    const index = await screen.findByRole('table');
    await user.click(
      within(index).getByRole('button', { name: /Пишем только в каналы, где есть агенты/ }),
    );

    expect(await screen.findByText('Так решили после замера.')).toBeInTheDocument();
    expect(seen.some((url) => url.pathname === `${PATH}/entries/3`)).toBe(true);
    expect(address.current).toBe('/projects/DEMO/directions/promotion?entry=3');
  });

  it('история атрибута — отбором `attribute` в деле направления', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/directions/promotion?tab=attributes');

    await user.click(await screen.findByRole('button', { name: 'channel' }));
    await screen.findByRole('region', { name: say.project('history', { name: 'channel' }) });
    expect(
      seen.some(
        (url) =>
          url.pathname === `${PATH}/entries` && url.searchParams.get('attribute') === 'channel',
      ),
    ).toBe(true);
    expect(address.current).toBe(
      '/projects/DEMO/directions/promotion?tab=attributes&attribute=channel',
    );
  });

  it('человек пишет в дело решение: тип выбран, запись `decision` подтверждена ссылкой', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/directions/promotion', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.direction('entry.open') }));
    const types = screen.getByRole('radiogroup', { name: say.direction('entry.typeLegend') });
    expect(
      within(types).getByRole('radio', { name: say.direction('entry.type.note') }),
    ).toBeChecked();
    await user.click(
      within(types).getByRole('radio', { name: say.direction('entry.type.decision') }),
    );

    const form = screen.getByRole('form', {
      name: say.direction('entry.formLabel', { address: ADDRESS }),
    });
    const field = within(form).getByLabelText(say.direction('entry.fieldLabel.decision'));
    await user.type(field, 'Посты только по вторникам{Enter}Так видно больше.');
    await user.click(
      within(form).getByRole('button', { name: say.direction('entry.submit.decision') }),
    );

    const receipt = await screen.findByRole('region', {
      name: say.direction('entry.receiptLabel.decision', { address: ADDRESS }),
    });
    expect(within(receipt).getByRole('link', { name: `${ADDRESS}#4` })).toHaveAttribute(
      'href',
      '/projects/DEMO/directions/promotion?entry=4',
    );
    expect(writes).toEqual([
      {
        method: 'POST',
        path: `${PATH}/entries`,
        body: {
          type: 'decision',
          title: 'Посты только по вторникам',
          body: 'Посты только по вторникам\nТак видно больше.',
        },
      },
    ]);
  });

  it('правка и архив — за «⋯» в шапке, а не в строке ссылок', async () => {
    renderApp('/projects/DEMO/directions/promotion', { language: 'ru' });

    // Окна правки и архива и пункты меню проверяет `features/manage-project/ui/holder-menu.test.tsx`
    // (`directionMenuActions`), путь через меню — сквозной.
    const menu = await menuButton();
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement;
    expect(within(header).getAllByRole('button')).toEqual([menu]);
    expect(screen.queryByRole('button', { name: say.direction('edit.open') })).toBeNull();
    expect(
      screen.queryByRole('button', { name: say.direction('archive.label', { address: ADDRESS }) }),
    ).toBeNull();
  });

  it('архивное направление только читается: правки атрибутов и записи нет, «⋯» на месте', async () => {
    server.use(
      http.get(`${API}${PATH}`, () => data(detail({ archived_at: '2026-10-01T10:00:00Z' }))),
    );
    const user = userEvent.setup();
    renderApp('/projects/DEMO/directions/promotion', { language: 'ru' });

    expect(await screen.findByText(/Направление в архиве с/)).toBeInTheDocument();
    // «Восстановить» — за «⋯»: у архивного направления активного проекта меню есть.
    expect(await menuButton()).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: say.direction('entry.open') })).toBeNull();

    // Атрибуты при этом читаются, но без правки.
    await user.click(tab(say.direction('tabs.attributes')));
    expect(await screen.findByRole('button', { name: 'channel' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: say.project('attribute.add') })).toBeNull();
  });

  it('направление архивного проекта: меню нет вовсе — ни правки, ни архива, ни восстановления, сказано почему', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail('DEMO', { archived_at: '2026-10-01T10:00:00Z' })),
      ),
    );
    renderApp('/projects/DEMO/directions/promotion', { language: 'ru' });

    expect(await screen.findByText(/Сначала восстанавливают проект/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: say.direction('menu.label', { address: ADDRESS }) }),
    ).toBeNull();
    expect(screen.queryByRole('button', { name: say.direction('archive.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.direction('restore.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.direction('entry.open') })).toBeNull();
  });

  it('направления нет — сказано словами, со ссылкой обратно на проект', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO/directions/nope`, () =>
        failure('direction_not_found', 404),
      ),
    );
    renderApp('/projects/DEMO/directions/nope', { language: 'ru' });

    expect(
      await screen.findByRole('heading', {
        name: say.direction('page.missingTitle', { address: 'DEMO/nope' }),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: say.direction('page.backToProject', { key: 'DEMO' }) }),
    ).toHaveAttribute('href', '/projects/DEMO');
  });
});
