import { http } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  areaDetail,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Строка счётчиков в шапке экрана проекта и страницы области (TRK-619, TRK#46):
 * четыре числа из `meta.total` у `GET /api/v1/tasks`, каждое — ссылкой в список с тем же
 * отбором. Мок отвечает по отбору запроса, как бэкенд: в какую графу попадает запрос,
 * видно по `status` и условию в `query`.
 */

type Counter = 'inProgress' | 'open' | 'waiting' | 'warnings';

/** В какую графу строки попал запрос: по статусу и условию языка запросов. */
function counterOf(url: URL): Counter {
  const status = url.searchParams.getAll('status');
  const query = url.searchParams.get('query') ?? '';
  if (status.includes('in_progress')) return 'inProgress';
  if (status.includes('open')) return 'open';
  if (query.includes('open_blocking_questions')) return 'waiting';
  return 'warnings';
}

let requests: URL[] = [];

function serve(totals: Record<Counter, number | null | 'error' | 'never'>) {
  server.use(
    http.get(`${API}/api/v1/tasks`, async ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const total = totals[counterOf(url)];
      if (total === 'never') return new Promise<never>(() => undefined);
      if (total === 'error') return failure('internal_error', 500);
      return collection([], { total });
    }),
  );
}

beforeEach(() => {
  requests = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO'))),
    http.get(`${API}/api/v1/projects/DEMO/areas`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/areas/promotion`, () =>
      data(areaDetail('DEMO/promotion')),
    ),
    http.get(`${API}/api/v1/projects/DEMO/areas/promotion/entries`, () => collection([])),
  );
});

/** Ссылка счётчика по его графе. */
function counter(id: Counter) {
  const strip = screen.getByRole('list', { name: say.tasks('counters.label') });
  return within(strip).getByRole('link', { name: new RegExp(`^${say.tasks(`counters.${id}`)}`) });
}

/** Условия адреса ссылки как пары имя-значение: порядок параметров тесту не важен. */
function params(link: HTMLElement): Record<string, string> {
  const href = link.getAttribute('href') ?? '';
  expect(href.startsWith('/tasks?')).toBe(true);
  return Object.fromEntries(new URL(href, 'http://x').searchParams);
}

describe('счётчики задач в шапке проекта', () => {
  it('данные: четыре числа из meta.total, каждое ссылкой с тем же отбором', async () => {
    serve({ inProgress: 3, open: 12, waiting: 2, warnings: 1 });
    renderApp('/projects/DEMO');

    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(counter('inProgress')).toHaveTextContent(/3$/));
    expect(counter('open')).toHaveTextContent(/12$/);
    expect(counter('waiting')).toHaveTextContent(/2$/);
    expect(counter('warnings')).toHaveTextContent(/1$/);

    expect(params(counter('inProgress'))).toEqual({ project: 'DEMO', status: 'in_progress' });
    expect(params(counter('open'))).toEqual({ project: 'DEMO', status: 'open' });
    expect(params(counter('waiting'))).toEqual({ project: 'DEMO', waiting: 'true' });
    expect(params(counter('warnings'))).toEqual({ project: 'DEMO', warnings: 'true' });

    // Четыре запроса, у каждого `limit=1`: число спрашивается, задачи не читаются.
    await waitFor(() => expect(requests).toHaveLength(4));
    for (const url of requests) {
      expect(url.searchParams.get('limit')).toBe('1');
      expect(url.searchParams.getAll('project')).toEqual(['DEMO']);
    }
  });

  it('ноль показывается нулём и остаётся ссылкой', async () => {
    serve({ inProgress: 0, open: 0, waiting: 0, warnings: 0 });
    renderApp('/projects/DEMO');

    await waitFor(() => expect(counter('inProgress')).toHaveTextContent(/0$/));
    for (const id of ['inProgress', 'open', 'waiting', 'warnings'] as const) {
      expect(counter(id)).toHaveTextContent(/0$/);
      expect(counter(id)).toHaveAttribute('href');
    }
  });

  it('null — без числа, но ссылкой', async () => {
    serve({ inProgress: null, open: 5, waiting: null, warnings: null });
    renderApp('/projects/DEMO');

    await waitFor(() => expect(counter('open')).toHaveTextContent(/5$/));
    expect(counter('inProgress').textContent).toBe(say.tasks('counters.inProgress'));
    expect(counter('inProgress')).toHaveAttribute('href');
    expect(counter('waiting').textContent).toBe(say.tasks('counters.waiting'));
  });

  it('ошибка одного запроса — прочерк с подсказкой, шапка и остальные числа целы', async () => {
    serve({ inProgress: 'error', open: 4, waiting: 1, warnings: 0 });
    renderApp('/projects/DEMO');

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('DEMO');
    await waitFor(() => expect(counter('inProgress')).toHaveTextContent('—'));
    expect(counter('inProgress')).toHaveAttribute('title');
    expect(counter('inProgress').getAttribute('title')).not.toBe('');
    await waitFor(() => expect(counter('open')).toHaveTextContent(/4$/));
    expect(counter('waiting')).toHaveTextContent(/1$/);
    expect(counter('inProgress')).toHaveAttribute('href');
  });

  it('загрузка: пока число не пришло, место занято, ссылка уже есть', async () => {
    serve({ inProgress: 'never', open: 2, waiting: 'never', warnings: 'never' });
    renderApp('/projects/DEMO');

    await waitFor(() => expect(counter('open')).toHaveTextContent(/2$/));
    expect(counter('inProgress')).toHaveTextContent('…');
    expect(counter('inProgress')).toHaveAttribute('href');
    expect(counter('inProgress').querySelector('[aria-busy="true"]')).not.toBeNull();
  });
});

describe('счётчики задач в шапке страницы области', () => {
  it('отбор по проекту и области: тот же адрес у числа и у ссылки', async () => {
    serve({ inProgress: 1, open: 2, waiting: 3, warnings: 4 });
    renderApp('/projects/DEMO/areas/promotion');

    await waitFor(() => expect(counter('warnings')).toHaveTextContent(/4$/));
    expect(counter('inProgress')).toHaveTextContent(/1$/);
    expect(params(counter('inProgress'))).toEqual({
      project: 'DEMO',
      area: 'DEMO/promotion',
      status: 'in_progress',
    });
    expect(params(counter('waiting'))).toEqual({
      project: 'DEMO',
      area: 'DEMO/promotion',
      waiting: 'true',
    });

    await waitFor(() => expect(requests).toHaveLength(4));
    for (const url of requests) {
      expect(url.searchParams.getAll('area')).toEqual(['DEMO/promotion']);
      expect(url.searchParams.get('limit')).toBe('1');
    }
  });
});
