import { http } from 'msw';
import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API, failure, task, taskPage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { ApiError } from '@/shared/api';
import {
  fetchTasks,
  tasksColumnQueryOptions,
  tasksQueryOptions,
  tasksTotalQueryOptions,
} from './tasks';

/** Значения `query` всех запросов списка, по порядку: `null` — параметра не было. */
let sent: (string | null)[] = [];

beforeEach(() => {
  sent = [];
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-09-11T12:00:00.000Z') });
});

afterEach(() => {
  vi.useRealTimers();
});

function listing(respond: (query: string | null) => Response = () => taskPage([task('DEMO-1')])) {
  return http.get(`${API}/api/v1/tasks`, ({ request }) => {
    const query = new URL(request.url).searchParams.get('query');
    sent.push(query);
    return respond(query);
  });
}

/** Правило показа при часах `at` — написано здесь заново, а не собрано кодом. */
function rule(at: string): string {
  return `status: not in done, cancelled or last_entry_at: >= "${at}"`;
}

describe('порог архива', () => {
  it('в ключе его нет: ключ один, а каждое чтение идёт со свежим порогом', async () => {
    server.use(listing());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const params = { hideArchived: true, query: 'status: done' };

    const first = tasksQueryOptions(params);
    await client.fetchQuery(first);

    // Прошло полдня: ключ, собранный заново, тот же самый — отрисовка нового чтения
    // не позовёт. А чтение, которое всё-таки случилось, считает порог от нового часа.
    vi.setSystemTime(new Date('2026-09-12T00:00:00.000Z'));
    const second = tasksQueryOptions(params);
    expect(second.queryKey).toEqual(first.queryKey);
    expect(JSON.stringify(second.queryKey)).not.toMatch(/\d{4}-\d{2}-\d{2}T/);

    await client.fetchQuery({ ...second, staleTime: 0 });

    expect(client.getQueryCache().getAll()).toHaveLength(1);
    expect(sent).toEqual([
      `(status: done) and (${rule('2026-09-08T12:00:00.000Z')})`,
      `(status: done) and (${rule('2026-09-09T00:00:00.000Z')})`,
    ]);
  });

  it('столбец доски и число выдачи несут тот же признак без даты', () => {
    const params = { hideArchived: true };

    for (const key of [
      tasksColumnQueryOptions('done', params).queryKey,
      tasksTotalQueryOptions(params).queryKey,
    ]) {
      expect(JSON.stringify(key)).toContain('"hideArchived":true');
      expect(JSON.stringify(key)).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    }
  });
});

describe('чтение списка с правилом архива', () => {
  it('без признака запрос уходит как есть: выдача API по умолчанию прежняя', async () => {
    server.use(listing());

    await fetchTasks({ query: 'status: done' });
    await fetchTasks({});

    expect(sent).toEqual(['status: done', null]);
  });

  it('с признаком и без запроса уходит одно правило', async () => {
    server.use(listing());

    await fetchTasks({ hideArchived: true });

    expect(sent).toEqual([rule('2026-09-08T12:00:00.000Z')]);
  });

  it('отказ разбора склейки приходит с позицией в строке человека', async () => {
    const query = 'status: donee';
    // Бэкенд называет позицию в той строке, которую получил, — в склейке.
    server.use(
      listing((received) =>
        failure('search_value_invalid', 422, 'Search value is invalid', {
          field: 'status',
          position: (received ?? '').indexOf('donee'),
          value: 'donee',
        }),
      ),
    );

    const refused = await fetchTasks({ hideArchived: true, query }).catch(
      (error: unknown) => error,
    );

    expect(sent[0]).toBe(`(${query}) and (${rule('2026-09-08T12:00:00.000Z')})`);
    expect(refused).toBeInstanceOf(ApiError);
    expect((refused as ApiError).details).toMatchObject({ position: 8, query });
  });

  it('строку с несошедшейся скобкой отправляет одну, и отказ приходит как есть', async () => {
    const query = 'status: done) or (status: cancelled';
    server.use(
      listing(() => failure('invalid_search_query', 422, 'Cannot parse', { position: 12, query })),
    );

    const refused = await fetchTasks({ hideArchived: true, query }).catch(
      (error: unknown) => error,
    );

    expect(sent).toEqual([query]);
    expect((refused as ApiError).details).toMatchObject({ position: 12, query });
  });
});
