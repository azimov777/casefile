import { describe, expect, it } from 'vitest';
import { ApiError } from './error';
import { unwrap, unwrapEmpty, unwrapPage } from './envelope';

function ok<T>(payload: T, status = 200) {
  return Promise.resolve({ data: payload, response: new Response(null, { status }) });
}

function failed(body: unknown, status: number) {
  return Promise.resolve({ error: body, response: new Response(null, { status }) });
}

describe('unwrap', () => {
  it('снимает оболочку ресурса', async () => {
    await expect(unwrap(ok({ data: { name: 'owner' } }))).resolves.toEqual({ name: 'owner' });
  });

  it('превращает отказ бэкенда в ApiError с кодом и подробностями', async () => {
    const promise = unwrap(
      failed(
        { error: { code: 'task_not_found', message: 'Task not found', details: { key: 'UI-9' } } },
        404,
      ),
    );

    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await promise.catch((error: ApiError) => {
      expect(error.code).toBe('task_not_found');
      expect(error.status).toBe(404);
      expect(error.details).toEqual({ key: 'UI-9' });
    });
  });

  it('ответ не в оболочке контракта не выдаётся за отказ по существу', async () => {
    await expect(unwrap(failed('<html>502</html>', 502))).rejects.toMatchObject({
      code: 'malformed_response',
      status: 502,
    });
  });

  it('несостоявшийся запрос приходит тем же типом ошибки', async () => {
    const promise = unwrap(Promise.reject(new TypeError('Failed to fetch')));
    await expect(promise).rejects.toMatchObject({ code: 'network_error', status: 0 });
  });
});

describe('unwrapPage', () => {
  it('разворачивает коллекцию в страницу с курсором', async () => {
    const page = await unwrapPage(
      ok({ data: [{ key: 'UI-1' }], meta: { next_cursor: 'abc', has_more: true } }),
    );

    expect(page.items).toEqual([{ key: 'UI-1' }]);
    expect(page.meta).toEqual({ next_cursor: 'abc', has_more: true });
  });

  it('коллекция без meta отдаёт страницу без курсора, а не undefined', async () => {
    const page = await unwrapPage(ok({ data: [] }));
    expect(page).toEqual({ items: [], meta: null });
  });
});

describe('unwrapEmpty', () => {
  it('ответ без тела — не нарушение контракта: отзыв отвечает `204` и пустотой', async () => {
    await expect(
      unwrapEmpty(Promise.resolve({ response: new Response(null, { status: 204 }) })),
    ).resolves.toBeUndefined();
  });

  it('отказ на ответе без тела приходит тем же `ApiError`', async () => {
    const promise = unwrapEmpty(
      failed({ error: { code: 'token_not_found', message: 'Token not found', details: {} } }, 404),
    );

    await expect(promise).rejects.toMatchObject({ code: 'token_not_found', status: 404 });
  });

  it('несостоявшийся запрос без тела — тоже `ApiError`, а не отказ сети мимо разбора', async () => {
    await expect(
      unwrapEmpty(Promise.reject(new TypeError('Failed to fetch'))),
    ).rejects.toMatchObject({ code: 'network_error', status: 0 });
  });
});
