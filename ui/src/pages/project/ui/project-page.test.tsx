import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, entryOfType, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';
import type { ProjectDecision } from '@/entities/project';

type Entry = components['schemas']['EntryRead'];
type ProjectDetail = components['schemas']['ProjectDetailRead'];

const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-02T10:00:00Z' };

function projectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    key: 'DEMO',
    title: 'Демонстрация',
    description: 'Учебный проект: код в `app/`.',
    last_task_number: 7,
    created_by: { kind: 'tracker', signature: null },
    ...STAMPS,
    attributes: [
      { name: 'branch', value: 'main', ...STAMPS },
      { name: 'repo', value: 'github.com/demo', ...STAMPS },
    ],
    decisions: [],
    directions: [],
    ...overrides,
  };
}

/** Запись дела проекта: владелец — проект, ключа задачи нет (TRK-156). */
function projectEntry(no: number, type: Entry['type'], overrides: Partial<Entry> = {}): Entry {
  return {
    ...entryOfType(no, 'DEMO', type),
    task_key: null,
    project_key: 'DEMO',
    ...overrides,
  } as Entry;
}

/** Дело проекта: заведение и правка `repo`, заведение `branch`, решение. */
const CASE: Entry[] = [
  projectEntry(1, 'created', { title: 'Project created', body: '' }),
  projectEntry(2, 'attribute_created'),
  projectEntry(3, 'attribute_created', {
    payload: { name: 'branch', after: 'main', reason: null },
  } as Partial<Entry>),
  projectEntry(4, 'attribute_changed'),
  projectEntry(5, 'decision', {
    title: 'Держим ветку main единственной',
    body: 'Так решили в DEMO-2.',
  }),
];

/** Полоса вкладок экрана проекта: ориентир `nav` с именем из словаря. */
function tabStrip() {
  return screen.getByRole('navigation', { name: say.project('tabs.label') });
}

/** Ссылка вкладки на полосе: подпись и число, если оно у вкладки есть. */
function tabLink(name: string, count?: number) {
  return within(tabStrip()).getByRole('link', {
    name: count === undefined ? name : `${name} ${count}`,
  });
}

/** Действующее решение проекта DEMO в чтении проекта. */
function decision(no: number, overrides: Partial<ProjectDecision> = {}): ProjectDecision {
  return {
    no,
    ref: `DEMO#${no}`,
    title: `Решение ${no}`,
    author: { kind: 'agent', signature: 'demo_agent' },
    created_at: '2026-09-01T10:00:00Z',
    status: 'in_force',
    supersedes: [],
    superseded_by: null,
    tasks: 0,
    ...overrides,
  };
}

/** Адреса запросов прогона: по ним видно, чем читалась история и тело. */
let seen: URL[] = [];

beforeEach(() => {
  seen = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail())),
    http.get(`${API}/api/v1/projects/DEMO/directions`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/entries`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      const types = url.searchParams.getAll('types');
      let items = types.length === 0 ? CASE : CASE.filter((entry) => types.includes(entry.type));
      // `attribute` — тот же отбор, что делает бэкенд (TRK-166): сужает до трёх типов
      // записи об атрибутах и до имени, без учёта регистра, складывается с `types` по «и».
      const attribute = url.searchParams.get('attribute');
      if (attribute !== null) {
        const wanted = attribute.toLowerCase();
        items = items.filter(
          (entry) =>
            (entry.type === 'attribute_created' ||
              entry.type === 'attribute_changed' ||
              entry.type === 'attribute_removed') &&
            entry.payload.name.toLowerCase() === wanted,
        );
      }
      return collection(items);
    }),
    http.get(`${API}/api/v1/projects/DEMO/entries/:no`, ({ params, request }) => {
      seen.push(new URL(request.url));
      const entry = CASE.find((item) => item.no === Number(params.no));
      return entry === undefined ? failure('entry_not_found', 404) : data(entry);
    }),
  );
});

describe('экран проекта', () => {
  it('шапка — ключ, название, описание; вкладки с числами из карточки, открыт «Обзор»', async () => {
    renderApp('/projects/DEMO');

    const title = await screen.findByRole('heading', { level: 1 });
    expect(title).toHaveTextContent('DEMO');
    expect(title).toHaveTextContent('Демонстрация');
    expect(screen.getByText('app/')).toBeInTheDocument();

    // Числа — из карточки: действующих решений нет, атрибутов два, направлений нет;
    // у «Дела» числа нет вовсе. Открыт «Обзор», остальные вкладки — ссылки на `?tab=`.
    expect(tabLink(say.project('tabs.overview'))).toHaveAttribute('aria-current', 'true');
    expect(tabLink(say.project('tabs.decisions'), 0)).toHaveAttribute(
      'href',
      '/projects/DEMO?tab=decisions',
    );
    expect(tabLink(say.project('tabs.attributes'), 2)).toHaveAttribute(
      'href',
      '/projects/DEMO?tab=attributes',
    );
    expect(tabLink(say.project('tabs.directions'), 0)).toHaveAttribute(
      'href',
      '/projects/DEMO?tab=directions',
    );
    expect(tabLink(say.project('tabs.case'))).toHaveAttribute('href', '/projects/DEMO?tab=case');
    expect(tabLink(say.project('tabs.case'))).not.toHaveAttribute('aria-current');

    // На «Обзоре» разделов вкладок нет: атрибуты и опись — по нажатию на вкладку.
    expect(screen.queryByRole('region', { name: say.project('attributes') })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(
      await screen.findByRole('region', { name: say.project('overview.case') }),
    ).toBeInTheDocument();
  });

  it('вкладка «Атрибуты» показывает атрибуты, «Дело» — опись дела', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO');

    await user.click(
      await screen.findByRole('link', { name: `${say.project('tabs.attributes')} 2` }),
    );
    expect(address.current).toBe('/projects/DEMO?tab=attributes');
    expect(tabLink(say.project('tabs.attributes'), 2)).toHaveAttribute('aria-current', 'true');
    const attributes = screen.getByRole('region', { name: say.project('attributes') });
    expect(within(attributes).getByRole('button', { name: 'repo' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(within(attributes).getByText('github.com/demo')).toBeInTheDocument();

    await user.click(tabLink(say.project('tabs.case')));
    expect(address.current).toBe('/projects/DEMO?tab=case');
    expect(screen.queryByRole('region', { name: say.project('attributes') })).toBeNull();
    const index = await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });
    expect(
      within(index).getByRole('button', { name: /Держим ветку main единственной/ }),
    ).toBeInTheDocument();
  });

  it('клик по записи описи читает её тело адресом записи проекта и пишет номер в адрес', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=case');

    await user.click(await screen.findByRole('button', { name: /Держим ветку main единственной/ }));

    expect(await screen.findByText(/Так решили в/)).toBeInTheDocument();
    // Ссылка на задачу в теле записи проекта — та же ссылка приложения.
    // В теле и в указателях записи — обе ссылками приложения.
    for (const link of screen.getAllByRole('link', { name: 'DEMO-2' })) {
      expect(link).toHaveAttribute('href', '/tasks/DEMO-2');
    }
    expect(seen.some((url) => url.pathname === '/api/v1/projects/DEMO/entries/5')).toBe(true);
    expect(address.current).toBe('/projects/DEMO?tab=case&entry=5');
  });

  it('свёрнутая запись, пришедшая ссылкой `?entry=N`, оставляет «Дело» открытым', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?entry=5');

    const row = await screen.findByRole('button', { name: /Держим ветку main единственной/ });
    expect(row).toHaveAttribute('aria-expanded', 'true');
    await user.click(row);

    expect(address.current).toBe('/projects/DEMO?tab=case');
    expect(tabLink(say.project('tabs.case'))).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('клик по атрибуту показывает его историю: только его записи, было, стало и причина', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=attributes');

    await user.click(await screen.findByRole('button', { name: 'repo' }));

    const history = await screen.findByRole('region', {
      name: say.project('history', { name: 'repo' }),
    });
    // Заведение и правка `repo`, а заведение `branch` сюда не попало: сеть мокается
    // отбором по `attribute`, а не по `types` — клиентского фильтра по имени больше нет.
    expect(await within(history).findAllByRole('article')).toHaveLength(2);
    expect(within(history).getByText('github.com/old')).toBeInTheDocument();
    expect(within(history).getByText('Репозиторий переехал')).toBeInTheDocument();
    expect(within(history).queryByText('main')).not.toBeInTheDocument();
    // Отбор по имени уходит на сервер параметром `attribute` (TRK-166, UI-179), не по `types`.
    const historyCall = seen.find((url) => url.searchParams.has('attribute'));
    expect(historyCall?.searchParams.get('attribute')).toBe('repo');
    expect(historyCall?.searchParams.has('types')).toBe(false);
    expect(address.current).toBe('/projects/DEMO?tab=attributes&attribute=repo');

    // Второй клик сворачивает историю и убирает имя из адреса; вкладка остаётся.
    await user.click(screen.getByRole('button', { name: 'repo' }));
    expect(
      screen.queryByRole('region', { name: say.project('history', { name: 'repo' }) }),
    ).not.toBeInTheDocument();
    expect(address.current).toBe('/projects/DEMO?tab=attributes');
  });

  it('адрес восстанавливает то же состояние после перезагрузки; проект помечен в панели', async () => {
    const { unmount } = renderApp('/projects/DEMO?attribute=repo');

    // Атрибут из адреса без `tab` открывает «Атрибуты» с открытой историей…
    expect(
      await screen.findByRole('region', { name: say.project('history', { name: 'repo' }) }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'repo' })).toHaveAttribute('aria-expanded', 'true');
    expect(tabLink(say.project('tabs.attributes'), 2)).toHaveAttribute('aria-current', 'true');
    unmount();

    renderApp('/projects/DEMO?entry=5');
    // …а запись из адреса — «Дело» с раскрытой записью и её телом.
    expect(await screen.findByText(/Так решили в/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Держим ветку main единственной/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(tabLink(say.project('tabs.case'))).toHaveAttribute('aria-current', 'true');

    // Место — проект DEMO: строка проекта и знак его экрана помечены `aria-current`.
    const sections = screen.getByRole('navigation', { name: say.ui('app.sections') });
    expect(within(sections).getByRole('link', { name: /^DEMO/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    const about = within(sections).getByRole('link', {
      name: say.ui('app.aboutProject', { key: 'DEMO' }),
    });
    expect(about).toHaveAttribute('href', '/projects/DEMO');
    expect(about).toHaveAttribute('aria-current', 'page');
  });

  it('неизвестный `tab` открывает «Обзор», а не пустой экран', async () => {
    renderApp('/projects/DEMO?tab=history');

    expect(
      await screen.findByRole('region', { name: say.project('overview.case') }),
    ).toBeInTheDocument();
    expect(tabLink(say.project('tabs.overview'))).toHaveAttribute('aria-current', 'true');
  });

  it('без описания и атрибутов говорит об этом словами', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail({ description: '', attributes: [] })),
      ),
    );
    renderApp('/projects/DEMO?tab=attributes');

    expect(await screen.findByText(say.project('noDescription'))).toBeInTheDocument();
    expect(screen.getByText(say.project('noAttributes'))).toBeInTheDocument();
    expect(tabLink(say.project('tabs.attributes'), 0)).toHaveAttribute('aria-current', 'true');
  });

  it('несуществующий проект — словами по коду, а не пустым экраном', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/NOPE`, () => failure('project_not_found', 404)),
      http.get(`${API}/api/v1/projects/NOPE/entries`, () => failure('project_not_found', 404)),
    );
    renderApp('/projects/NOPE');

    expect(
      await screen.findByRole('heading', { name: say.project('missingTitle', { key: 'NOPE' }) }),
    ).toBeInTheDocument();
  });

  it('из панели на экран проекта — одним движением, строка проекта ведёт в список', async () => {
    const user = userEvent.setup();
    server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
    renderApp('/tasks?project=DEMO');

    const sections = await screen.findByRole('navigation', { name: say.ui('app.sections') });
    const row = await within(sections).findByRole('link', { name: /^DEMO/ });
    expect(row.getAttribute('href')).toMatch(/^\/tasks\?.*project=DEMO/);

    await user.click(
      within(sections).getByRole('link', { name: say.ui('app.aboutProject', { key: 'DEMO' }) }),
    );
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Демонстрация');
    expect(address.current).toBe('/projects/DEMO');
  });
});

describe('вкладка «Обзор»', () => {
  it('направления списком: название ссылкой на страницу направления и адрес', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(
          projectDetail({
            directions: [
              { address: 'DEMO/promotion', title: 'Популяризация' },
              { address: 'DEMO/sales', title: 'Продажи' },
            ],
          }),
        ),
      ),
    );
    renderApp('/projects/DEMO', { language: 'ru' });

    const block = await screen.findByRole('region', { name: say.project('overview.directions') });
    const rows = within(block).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0] as HTMLElement).getByRole('link', { name: /Популяризация/ }),
    ).toHaveAttribute('href', '/projects/DEMO/directions/promotion');
    expect(rows[0]).toHaveTextContent('DEMO/promotion');
    expect(tabLink(say.project('tabs.directions'), 2)).toBeInTheDocument();
  });

  it('три последних действующих решения по номеру, сверху новое; «Все N решений» — на вкладку', async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(
          projectDetail({
            decisions: [
              decision(2, { title: 'Первое' }),
              decision(3, { title: 'Заменённое', status: 'superseded', superseded_by: 9 }),
              decision(5, { title: 'Второе' }),
              decision(7, { title: 'Третье' }),
              decision(9, { title: 'Четвёртое', supersedes: [3] }),
            ],
          }),
        ),
      ),
    );
    renderApp('/projects/DEMO', { language: 'ru' });

    const block = await screen.findByRole('region', { name: say.project('overview.decisions') });
    const rows = within(block).getAllByRole('listitem');
    expect(rows.map((row) => row.getAttribute('data-overview-decision'))).toEqual([
      'DEMO#9',
      'DEMO#7',
      'DEMO#5',
    ]);
    expect(rows[0]).toHaveTextContent('Четвёртое');
    // Ключ решения ведёт в «Дело» с раскрытой записью — тем же адресом, что `TRK#9`.
    expect(within(rows[0] as HTMLElement).getByRole('link', { name: 'DEMO#9' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=9',
    );
    // Число — действующих: заменённое не в счёт ни здесь, ни на вкладке.
    expect(tabLink(say.project('tabs.decisions'), 4)).toBeInTheDocument();

    await user.click(
      within(block).getByRole('link', { name: say.project('overview.allDecisions', { count: 4 }) }),
    );
    expect(address.current).toBe('/projects/DEMO?tab=decisions');
    expect(
      await screen.findByRole('region', { name: say.project('decisions.title') }),
    ).toBeInTheDocument();
  });

  it('пять последних записей дела, сверху новое; нажатие открывает «Дело» с раскрытой записью', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    const block = await screen.findByRole('region', { name: say.project('overview.case') });
    await waitFor(() => expect(within(block).getAllByRole('listitem')).toHaveLength(5));
    const rows = within(block).getAllByRole('listitem');
    expect(rows.map((row) => row.getAttribute('data-overview-entry'))).toEqual([
      '5',
      '4',
      '3',
      '2',
      '1',
    ]);
    expect(
      within(block).getByRole('link', { name: say.project('overview.allCase') }),
    ).toHaveAttribute('href', '/projects/DEMO?tab=case');

    await user.click(within(block).getByRole('link', { name: /Держим ветку main единственной/ }));
    expect(address.current).toBe('/projects/DEMO?entry=5');
    expect(tabLink(say.project('tabs.case'))).toHaveAttribute('aria-current', 'true');
    expect(await screen.findByText(/Так решили в/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Держим ветку main единственной/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('из длинного дела берутся последние записи, а не последние из первой страницы', async () => {
    const first = Array.from({ length: 4 }, (_, index) =>
      projectEntry(index + 1, 'note', { title: `Ранняя ${index + 1}` }),
    );
    const second = Array.from({ length: 6 }, (_, index) =>
      projectEntry(index + 5, 'note', { title: `Поздняя ${index + 5}` }),
    );
    server.use(
      http.get(`${API}/api/v1/projects/DEMO/entries`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        return cursor === 'page-2'
          ? collection(second)
          : collection(first, { has_more: true, next_cursor: 'page-2' });
      }),
    );
    renderApp('/projects/DEMO', { language: 'ru' });

    const block = await screen.findByRole('region', { name: say.project('overview.case') });
    await waitFor(() =>
      expect(
        within(block)
          .getAllByRole('listitem')
          .map((row) => row.getAttribute('data-overview-entry')),
      ).toEqual(['10', '9', '8', '7', '6']),
    );
  });

  it('пустые состояния сказаны словами', async () => {
    server.use(http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])));
    renderApp('/projects/DEMO', { language: 'ru' });

    expect(await screen.findByText(say.project('overview.directionsNone'))).toBeInTheDocument();
    expect(screen.getByText(say.project('decisions.none'))).toBeInTheDocument();
    expect(await screen.findByText(say.project('overview.caseNone'))).toBeInTheDocument();
    // Ссылок «Все решения» и «Всё дело» у пустого нет: вести некуда.
    expect(screen.queryByRole('link', { name: say.project('overview.allCase') })).toBeNull();
  });
});

describe('фильтр по типу в деле проекта (TRK-621)', () => {
  it('без выбора запрос дела уходит без types, чипов нет', async () => {
    renderApp('/projects/DEMO?tab=case');
    await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });

    const caseReads = seen.filter((url) => url.pathname === '/api/v1/projects/DEMO/entries');
    expect(caseReads.length).toBeGreaterThan(0);
    for (const url of caseReads) expect(url.searchParams.has('types')).toBe(false);
    expect(screen.getByText(say.case('filters.allShown'))).toBeInTheDocument();
  });

  it('?type= из адреса уходит бэкенду параметром types, остальные параметры целы', async () => {
    renderApp('/projects/DEMO?type=decision&entry=5');

    const index = await screen.findByRole('table', { name: say.ui('index.count', { count: 1 }) });
    expect(
      within(index).getByRole('button', { name: /Держим ветку main единственной/ }),
    ).toHaveAttribute('aria-expanded', 'true');
    const filtered = seen.filter(
      (url) => url.pathname === '/api/v1/projects/DEMO/entries' && url.searchParams.has('types'),
    );
    expect(filtered.at(-1)?.searchParams.getAll('types')).toEqual(['decision']);
  });

  it('снятие чипа убирает type из адреса и возвращает все записи; entry остаётся', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?type=decision&entry=5');
    await screen.findByRole('table', { name: say.ui('index.count', { count: 1 }) });

    await user.click(
      screen.getByRole('button', { name: say.case('filters.remove', { type: 'decision' }) }),
    );

    await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });
    expect(address.current).toBe('/projects/DEMO?entry=5');
  });

  it('пустая выдача по отбору — честное пустое состояние со сбросом', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=case&type=note');

    expect(await screen.findByText(say.case('emptyByTypes'))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: say.case('filters.reset') }));

    await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });
    expect(address.current).toBe('/projects/DEMO?tab=case');
  });

  it('запись из адреса, спрятанная отбором, названа словами со сбросом', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?type=created&entry=5');

    expect(
      await screen.findByText(say.case('window.hiddenByType', { reference: 'DEMO#5' }), {
        exact: false,
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: say.case('window.showAllTypes') }));

    await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });
    expect(address.current).toBe('/projects/DEMO?entry=5');
  });
});
