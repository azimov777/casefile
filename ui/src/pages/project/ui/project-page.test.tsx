import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, entryOfType, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

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

/** Адреса запросов прогона: по ним видно, чем читалась история и тело. */
let seen: URL[] = [];

beforeEach(() => {
  seen = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail())),
    http.get(`${API}/api/v1/projects/DEMO/entries`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      const types = url.searchParams.getAll('types');
      return collection(
        types.length === 0 ? CASE : CASE.filter((entry) => types.includes(entry.type)),
      );
    }),
    http.get(`${API}/api/v1/projects/DEMO/entries/:no`, ({ params, request }) => {
      seen.push(new URL(request.url));
      const entry = CASE.find((item) => item.no === Number(params.no));
      return entry === undefined ? failure('entry_not_found', 404) : data(entry);
    }),
  );
});

describe('экран проекта', () => {
  it('показывает ключ, название, описание, атрибуты и опись дела', async () => {
    renderApp('/projects/DEMO');

    const title = await screen.findByRole('heading', { level: 1 });
    expect(title).toHaveTextContent('DEMO');
    expect(title).toHaveTextContent('Демонстрация');
    expect(screen.getByText('app/')).toBeInTheDocument();

    const attributes = screen.getByRole('region', { name: say.project('attributes') });
    expect(within(attributes).getByRole('button', { name: 'repo' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(within(attributes).getByText('github.com/demo')).toBeInTheDocument();

    const index = await screen.findByRole('table', { name: say.ui('index.count', { count: 5 }) });
    expect(
      within(index).getByRole('button', { name: /Держим ветку main единственной/ }),
    ).toBeInTheDocument();
  });

  it('клик по записи описи читает её тело адресом записи проекта и пишет номер в адрес', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO');

    await user.click(await screen.findByRole('button', { name: /Держим ветку main единственной/ }));

    expect(await screen.findByText(/Так решили в/)).toBeInTheDocument();
    // Ссылка на задачу в теле записи проекта — та же ссылка приложения.
    // В теле и в указателях записи — обе ссылками приложения.
    for (const link of screen.getAllByRole('link', { name: 'DEMO-2' })) {
      expect(link).toHaveAttribute('href', '/tasks/DEMO-2');
    }
    expect(seen.some((url) => url.pathname === '/api/v1/projects/DEMO/entries/5')).toBe(true);
    expect(address.current).toBe('/projects/DEMO?entry=5');
  });

  it('клик по атрибуту показывает его историю: только его записи, было, стало и причина', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO');

    await user.click(await screen.findByRole('button', { name: 'repo' }));

    const history = await screen.findByRole('region', {
      name: say.project('history', { name: 'repo' }),
    });
    // Заведение и правка `repo`, а заведение `branch` сюда не попало.
    expect(await within(history).findAllByRole('article')).toHaveLength(2);
    expect(within(history).getByText('github.com/old')).toBeInTheDocument();
    expect(within(history).getByText('Репозиторий переехал')).toBeInTheDocument();
    expect(within(history).queryByText('main')).not.toBeInTheDocument();
    // Отбор по типу делает бэкенд — все три типа истории названы в запросе.
    const historyCall = seen.find((url) => url.searchParams.has('types'));
    expect(historyCall?.searchParams.getAll('types')).toEqual([
      'attribute_created',
      'attribute_changed',
      'attribute_removed',
    ]);
    expect(address.current).toBe('/projects/DEMO?attribute=repo');

    // Второй клик сворачивает историю и убирает имя из адреса.
    await user.click(screen.getByRole('button', { name: 'repo' }));
    expect(
      screen.queryByRole('region', { name: say.project('history', { name: 'repo' }) }),
    ).not.toBeInTheDocument();
    expect(address.current).toBe('/projects/DEMO');
  });

  it('адрес восстанавливает то же состояние после перезагрузки; проект помечен в панели', async () => {
    renderApp('/projects/DEMO?attribute=repo&entry=5');

    // История атрибута из адреса открыта…
    expect(
      await screen.findByRole('region', { name: say.project('history', { name: 'repo' }) }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'repo' })).toHaveAttribute('aria-expanded', 'true');
    // …и запись из адреса раскрыта с телом.
    expect(await screen.findByText(/Так решили в/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Держим ветку main единственной/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );

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

  it('без описания и атрибутов говорит об этом словами', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail({ description: '', attributes: [] })),
      ),
    );
    renderApp('/projects/DEMO');

    expect(await screen.findByText(say.project('noDescription'))).toBeInTheDocument();
    expect(screen.getByText(say.project('noAttributes'))).toBeInTheDocument();
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
