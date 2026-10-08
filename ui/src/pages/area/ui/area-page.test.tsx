import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  areaDetail,
  entryOfType,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

/*
 * Страница области (TRK-557): карточка, атрибуты с историей, дело области описью
 * с телами по клику, запись человека — заметка или решение, правка и архив с причиной;
 * архивная область и область архивного проекта только читаются.
 */

type Entry = components['schemas']['EntryRead'];

const ADDRESS = 'DEMO/promotion';
const PATH = '/api/v1/projects/DEMO/areas/promotion';
const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-02T10:00:00Z' };

/** Запись дела области: ни задачи, ни проекта — назван адрес области. */
function areaEntry(no: number, type: Entry['type'], overrides: Partial<Entry> = {}): Entry {
  return {
    ...entryOfType(no, 'DEMO', type),
    task_key: null,
    project_key: null,
    area: ADDRESS,
    ...overrides,
  } as Entry;
}

const CASE: Entry[] = [
  areaEntry(1, 'created', { title: 'Area created', body: '' }),
  areaEntry(2, 'attribute_created', {
    payload: { name: 'channel', after: 'reddit', reason: null },
  } as Partial<Entry>),
  areaEntry(3, 'decision', {
    title: 'Пишем только в каналы, где есть агенты',
    body: 'Так решили после замера.',
    status: 'in_force',
    superseded_by: null,
  } as Partial<Entry>),
  areaEntry(4, 'decision', {
    title: 'Пишем в любые каналы',
    body: 'Прежнее правило.',
    status: 'superseded',
    superseded_by: 3,
  } as Partial<Entry>),
  areaEntry(5, 'finding', {
    title: 'Reddit режет ссылки на новые домены',
    body: 'Замер: из десяти постов с ссылкой живы два.',
    status: 'in_force',
    superseded_by: null,
  } as Partial<Entry>),
  areaEntry(6, 'finding', {
    title: 'Reddit принимает любые ссылки',
    body: 'Устарело.',
    status: 'superseded',
    superseded_by: 5,
  } as Partial<Entry>),
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

/** Кнопка меню «⋯» в шапке страницы области (TRK-618). */
function menuButton() {
  return screen.findByRole('button', { name: say.area('menu.label', { address: ADDRESS }) });
}

/** Вкладка страницы области по началу подписи. */
function tab(name: string) {
  return within(screen.getByRole('navigation', { name: say.area('tabs.label') })).getByRole(
    'link',
    { name: new RegExp(`^${name}`) },
  );
}

function detail(overrides: Parameters<typeof areaDetail>[1] = {}) {
  return areaDetail(ADDRESS, {
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
    // Счётчики шапки (TRK-619) читают список задач; их числа здесь не проверяются.
    http.get(`${API}/api/v1/tasks`, () => collection([], { total: 0 })),
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
      return data(areaEntry(7, body.type), 201);
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

describe('страница области', () => {
  it('показывает адрес, название, описание и опись; атрибуты — вкладкой; ссылки на проект и задачи', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    const title = await screen.findByRole('heading', { level: 1 });
    expect(title).toHaveTextContent(ADDRESS);
    expect(title).toHaveTextContent('Популяризация');
    expect(screen.getByText('день запуска')).toBeInTheDocument();

    // Без параметра открыты «Решения»: «Обзора» у области нет.
    expect(tab(say.area('tabs.decisions'))).toHaveAttribute('aria-current', 'true');
    expect(await screen.findByText('Пишем только в каналы, где есть агенты')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    await user.click(tab(say.area('tabs.case')));
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=case');
    const index = await screen.findByRole('table', { name: say.ui('index.count', { count: 6 }) });
    expect(
      within(index).getByRole('button', { name: /Пишем только в каналы, где есть агенты/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: say.project('attributes') })).toBeNull();

    expect(
      screen.getByRole('link', { name: say.area('page.project', { key: 'DEMO' }) }),
    ).toHaveAttribute('href', '/projects/DEMO');
    // Задачи области — список с отбором `area`, тем же условием, что у агента.
    const tasks = screen.getByRole('link', { name: say.area('page.tasks') });
    const href = new URL(tasks.getAttribute('href') ?? '', 'http://x');
    expect(href.pathname).toBe('/tasks');
    expect(href.searchParams.get('project')).toBe('DEMO');
    expect(href.searchParams.get('area')).toBe(ADDRESS);

    // Верхняя полоса: проект, его экран ссылкой и само место. Строка имени сравнивается
    // целиком: «Проект DEMO» под карточкой с ней не совпадает.
    expect(screen.getByRole('link', { name: say.ui('app.crumbProject') })).toHaveAttribute(
      'href',
      '/projects/DEMO',
    );

    // Вкладка «Атрибуты» с числом из карточки.
    const attributesTab = tab(say.area('tabs.attributes'));
    expect(attributesTab).toHaveAccessibleName(`${say.area('tabs.attributes')} 1`);
    await user.click(attributesTab);
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=attributes');
    const attributes = screen.getByRole('region', { name: say.project('attributes') });
    expect(within(attributes).getByRole('button', { name: 'channel' })).toBeInTheDocument();
    expect(within(attributes).getByText('reddit')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('`tab=areas` у области — «Решения»: этой вкладки у неё нет', async () => {
    renderApp('/projects/DEMO/areas/promotion?tab=areas', { language: 'ru' });

    expect(
      await screen.findByRole('list', { name: say.area('knowledge.decisions.list') }),
    ).toBeInTheDocument();
    expect(tab(say.area('tabs.decisions'))).toHaveAttribute('aria-current', 'true');
  });

  it('тело записи читается адресом записи области, номер уходит в адрес страницы', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=case');

    const index = await screen.findByRole('table');
    await user.click(
      within(index).getByRole('button', { name: /Пишем только в каналы, где есть агенты/ }),
    );

    expect(await screen.findByText('Так решили после замера.')).toBeInTheDocument();
    expect(seen.some((url) => url.pathname === `${PATH}/entries/3`)).toBe(true);
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=case&entry=3');
  });

  it('история атрибута — отбором `attribute` в деле области', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=attributes');

    await user.click(await screen.findByRole('button', { name: 'channel' }));
    await screen.findByRole('region', { name: say.project('history', { name: 'channel' }) });
    expect(
      seen.some(
        (url) =>
          url.pathname === `${PATH}/entries` && url.searchParams.get('attribute') === 'channel',
      ),
    ).toBe(true);
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=attributes&attribute=channel');
  });

  it('человек пишет в дело решение: тип выбран, запись `decision` подтверждена ссылкой', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=case', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.area('entry.open') }));
    const types = screen.getByRole('radiogroup', { name: say.area('entry.typeLegend') });
    // Заметка области — запись `finding` (TRK#59): её можно будет заменить.
    expect(
      within(types).getByRole('radio', { name: say.area('entry.type.finding') }),
    ).toBeChecked();
    await user.click(within(types).getByRole('radio', { name: say.area('entry.type.decision') }));

    const form = screen.getByRole('form', {
      name: say.area('entry.formLabel', { address: ADDRESS }),
    });
    const field = within(form).getByLabelText(say.area('entry.fieldLabel.decision'));
    await user.type(field, 'Посты только по вторникам{Enter}Так видно больше.');
    await user.click(within(form).getByRole('button', { name: say.area('entry.submit.decision') }));

    const receipt = await screen.findByRole('region', {
      name: say.area('entry.receiptLabel.decision', { address: ADDRESS }),
    });
    expect(within(receipt).getByRole('link', { name: `${ADDRESS}#7` })).toHaveAttribute(
      'href',
      '/projects/DEMO/areas/promotion?entry=7',
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
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    // Окна правки и архива и пункты меню проверяет `features/manage-project/ui/holder-menu.test.tsx`
    // (`areaMenuActions`), путь через меню — сквозной.
    const menu = await menuButton();
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement;
    expect(within(header).getAllByRole('button')).toEqual([menu]);
    expect(screen.queryByRole('button', { name: say.area('edit.open') })).toBeNull();
    expect(
      screen.queryByRole('button', { name: say.area('archive.label', { address: ADDRESS }) }),
    ).toBeNull();
  });

  it('архивная область только читается: правки атрибутов и записи нет, «⋯» на месте', async () => {
    server.use(
      http.get(`${API}${PATH}`, () => data(detail({ archived_at: '2026-10-01T10:00:00Z' }))),
    );
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    expect(await screen.findByText(/Область в архиве с/)).toBeInTheDocument();
    // «Восстановить» — за «⋯»: у архивной области активного проекта меню есть.
    expect(await menuButton()).toBeInTheDocument();
    await screen.findByRole('list', { name: say.area('knowledge.decisions.list') });
    expect(screen.queryByRole('button', { name: say.area('knowledge.openDecision') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.area('knowledge.openNote') })).toBeNull();
    // Атрибуты при этом читаются, но без правки.
    await user.click(tab(say.area('tabs.attributes')));
    const channel = await screen.findByRole('button', { name: /^channel$/ });
    expect(screen.queryByRole('button', { name: say.project('attribute.add') })).toBeNull();
    // …и в открытой истории архивной области кнопок правки нет.
    await user.click(channel);
    await screen.findByRole('region', { name: say.project('history', { name: 'channel' }) });
    expect(
      screen.queryByRole('button', {
        name: say.project('attribute.changeLabel', { name: 'channel' }),
      }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', {
        name: say.project('attribute.removeLabel', { name: 'channel' }),
      }),
    ).toBeNull();
  });

  it('«Изменить» и «Снять» атрибута — в открытой истории, а не под строкой', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=attributes', { language: 'ru' });

    const channel = await screen.findByRole('button', { name: /^channel$/ });
    const change = say.project('attribute.changeLabel', { name: 'channel' });
    const remove = say.project('attribute.removeLabel', { name: 'channel' });
    expect(screen.queryByRole('button', { name: change })).toBeNull();
    expect(screen.queryByRole('button', { name: remove })).toBeNull();

    await user.click(channel);
    const history = await screen.findByRole('region', {
      name: say.project('history', { name: 'channel' }),
    });
    expect(within(history).getByRole('button', { name: change })).toBeInTheDocument();
    expect(within(history).getByRole('button', { name: remove })).toBeInTheDocument();
  });

  it('область архивного проекта: меню нет вовсе — ни правки, ни архива, ни восстановления, сказано почему', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail('DEMO', { archived_at: '2026-10-01T10:00:00Z' })),
      ),
    );
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    expect(await screen.findByText(/Сначала восстанавливают проект/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: say.area('menu.label', { address: ADDRESS }) }),
    ).toBeNull();
    expect(screen.queryByRole('button', { name: say.area('archive.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.area('restore.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.area('entry.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.area('knowledge.openDecision') })).toBeNull();
  });

  it('области нет — сказано словами, со ссылкой обратно на проект', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO/areas/nope`, () => failure('area_not_found', 404)),
    );
    renderApp('/projects/DEMO/areas/nope', { language: 'ru' });

    expect(
      await screen.findByRole('heading', {
        name: say.area('page.missingTitle', { address: 'DEMO/nope' }),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: say.area('page.backToProject', { key: 'DEMO' }) }),
    ).toHaveAttribute('href', '/projects/DEMO');
  });
});

/** Запросы дела областью, кроме чтения знания (его типы — решения и заметки сразу). */
function caseReads(): URL[] {
  return seen.filter(
    (url) =>
      url.pathname === `${PATH}/entries` &&
      !(url.searchParams.getAll('types').includes('finding') && url.searchParams.has('types')),
  );
}

describe('фильтр по типу в деле области (TRK-621)', () => {
  /** Дело области с отбором по `types`, как у бэкенда. */
  function filtered() {
    return http.get(`${API}${PATH}/entries`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      const types = url.searchParams.getAll('types');
      return collection(types.length === 0 ? CASE : CASE.filter((e) => types.includes(e.type)));
    });
  }

  it('без выбора запрос дела уходит без types', async () => {
    server.use(filtered());
    renderApp('/projects/DEMO/areas/promotion?tab=case', { language: 'ru' });
    await screen.findByRole('table', { name: say.ui('index.count', { count: 6 }) });

    const reads = caseReads();
    expect(reads.length).toBeGreaterThan(0);
    for (const url of reads) expect(url.searchParams.has('types')).toBe(false);
  });

  it('с выбором запрос дела уходит с types', async () => {
    server.use(filtered());
    renderApp('/projects/DEMO/areas/promotion?tab=case&type=decision', { language: 'ru' });
    await screen.findByRole('table', { name: say.ui('index.count', { count: 2 }) });

    const reads = caseReads();
    expect(reads.at(-1)?.searchParams.getAll('types')).toEqual(['decision']);
  });

  it('пустая выдача по отбору — честное пустое состояние со сбросом', async () => {
    const user = userEvent.setup();
    server.use(filtered());
    renderApp('/projects/DEMO/areas/promotion?tab=case&type=note', { language: 'ru' });

    expect(await screen.findByText(say.case('emptyByTypes'))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: say.case('filters.reset') }));

    await screen.findByRole('table', { name: say.ui('index.count', { count: 6 }) });
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=case');
  });
});

describe('знание области: решения и заметки (TRK-660, TRK#59)', () => {
  /** Список знания вкладки по имени. */
  const list = (name: string) => screen.findByRole('list', { name });

  it('«Решения»: действующие в списке, заменённых нет; число на вкладке — действующих', async () => {
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    const decisions = await list(say.area('knowledge.decisions.list'));
    expect(within(decisions).getAllByRole('listitem')).toHaveLength(1);
    expect(
      within(decisions).getByText('Пишем только в каналы, где есть агенты'),
    ).toBeInTheDocument();
    expect(within(decisions).queryByText('Пишем в любые каналы')).toBeNull();
    expect(tab(say.area('tabs.decisions'))).toHaveAccessibleName(`${say.area('tabs.decisions')} 1`);
    expect(tab(say.area('tabs.notes'))).toHaveAccessibleName(`${say.area('tabs.notes')} 1`);
    // Ссылка записи ведёт в «Дело» с раскрытым телом.
    expect(within(decisions).getByRole('link', { name: `${ADDRESS}#3` })).toHaveAttribute(
      'href',
      '/projects/DEMO/areas/promotion?entry=3',
    );
  });

  it('«Показать заменённые» добавляет заменённую заметку с пометкой и ссылкой на преемника', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=notes', { language: 'ru' });

    const notes = await list(say.area('knowledge.notes.list'));
    expect(within(notes).getByText('Reddit режет ссылки на новые домены')).toBeInTheDocument();
    expect(screen.queryByText('Reddit принимает любые ссылки')).toBeNull();

    await user.click(
      screen.getByRole('checkbox', { name: new RegExp(say.area('knowledge.showSuperseded')) }),
    );

    const old = screen.getByText('Reddit принимает любые ссылки').closest('li') as HTMLElement;
    expect(old).toHaveAttribute('data-status', 'superseded');
    expect(within(old).getByText(say.ui('decision.status.superseded'))).toBeInTheDocument();
    expect(within(old).getByRole('link', { name: `${ADDRESS}#5` })).toHaveAttribute(
      'href',
      '/projects/DEMO/areas/promotion?entry=5',
    );
    // Число на вкладке по-прежнему считает действующие.
    expect(tab(say.area('tabs.notes'))).toHaveAccessibleName(`${say.area('tabs.notes')} 1`);
  });

  it('поиск уходит параметром text и живёт в адресе', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=notes', { language: 'ru' });

    await list(say.area('knowledge.notes.list'));
    const field = screen.getByRole('searchbox', { name: say.area('knowledge.searchLabel') });
    await user.type(field, 'десяти{Enter}');

    await vi.waitFor(() =>
      expect(address.current).toContain('q=%D0%B4%D0%B5%D1%81%D1%8F%D1%82%D0%B8'),
    );
    await vi.waitFor(() =>
      expect(seen.some((url) => url.searchParams.get('text') === 'десяти')).toBe(true),
    );
    // Между «Заметками» и «Решениями» поиск переезжает, с «Дела» снимается.
    await user.click(tab(say.area('tabs.decisions')));
    expect(address.current).toContain('q=');
    await user.click(tab(say.area('tabs.case')));
    expect(address.current).toBe('/projects/DEMO/areas/promotion?tab=case');
  });

  it('«Решение» на вкладке пишет запись `decision` без выбора типа', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', { name: say.area('knowledge.openDecision') }),
    );
    expect(screen.queryByRole('radiogroup')).toBeNull();
    const form = screen.getByRole('form', {
      name: say.area('entry.formLabel', { address: ADDRESS }),
    });
    await user.type(
      within(form).getByLabelText(say.area('entry.fieldLabel.decision')),
      'Новое правило',
    );
    await user.click(within(form).getByRole('button', { name: say.area('entry.submit.decision') }));

    await screen.findByRole('region', {
      name: say.area('entry.receiptLabel.decision', { address: ADDRESS }),
    });
    expect(writes).toHaveLength(1);
    expect(writes[0]?.body).toMatchObject({ type: 'decision', title: 'Новое правило' });
  });

  it('«Заметка» на вкладке пишет запись `finding`', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO/areas/promotion?tab=notes', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.area('knowledge.openNote') }));
    const form = screen.getByRole('form', {
      name: say.area('entry.formLabel', { address: ADDRESS }),
    });
    await user.type(within(form).getByLabelText(say.area('entry.fieldLabel.finding')), 'Факт');
    await user.click(within(form).getByRole('button', { name: say.area('entry.submit.finding') }));

    await screen.findByRole('region', {
      name: say.area('entry.receiptLabel.finding', { address: ADDRESS }),
    });
    expect(writes[0]?.body).toMatchObject({ type: 'finding', title: 'Факт' });
  });
});
