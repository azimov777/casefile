import { ApiError } from './error';
import type { components } from './openapi';

export type PageMeta = components['schemas']['PageMeta'];

/** Страница коллекции: то, что показывают, и то, чем листают. */
export interface Page<T> {
  items: T[];
  meta: PageMeta | null;
}

/**
 * Что возвращает `openapi-fetch`: разобранное тело удачного ответа, тело ошибки
 * и сам ответ. Тип описан здесь, а не берётся из библиотеки, потому что нужна
 * только эта часть её формы.
 */
interface FetchResult<TData> {
  data?: TData;
  error?: unknown;
  response: Response;
}

/**
 * Снимает оболочку `{ data }` с ответа-ресурса.
 *
 * Принимает обещание, а не результат, намеренно: несостоявшийся запрос (сеть, упавший
 * сервер) обязан прийти на страницу тем же `ApiError`, что и отказ бэкенда. Иначе
 * каждому вызову пришлось бы ловить два разных вида беды.
 */
export async function unwrap<T>(call: Promise<FetchResult<{ data: T }>>): Promise<T> {
  const envelope = await settle(call);
  return envelope.data;
}

/** То же для коллекции: `{ data: [...], meta }` разворачивается в страницу. */
export async function unwrapPage<T>(
  call: Promise<FetchResult<{ data: T[]; meta?: PageMeta }>>,
): Promise<Page<T>> {
  const envelope = await settle(call);
  return { items: envelope.data, meta: envelope.meta ?? null };
}

/**
 * Ответ без тела: `204` у отзыва токена. Проверяется один отказ — данных, которые
 * можно было бы развернуть, у такого ответа нет вовсе, и `unwrap` объявил бы пустое
 * тело нарушением контракта (`malformed_response`).
 */
export async function unwrapEmpty(call: Promise<FetchResult<unknown>>): Promise<void> {
  const result = await sent(call);
  if (result.error !== undefined) {
    throw ApiError.fromBody(result.error, result.response.status);
  }
}

async function settle<TData>(call: Promise<FetchResult<TData>>): Promise<TData> {
  const result = await sent(call);

  if (result.error !== undefined) {
    throw ApiError.fromBody(result.error, result.response.status);
  }
  if (result.data === undefined) {
    throw ApiError.fromBody(null, result.response.status);
  }
  return result.data;
}

/** Итог запроса или `ApiError`: несостоявшийся запрос и отказ бэкенда — одна беда. */
async function sent<TData>(call: Promise<FetchResult<TData>>): Promise<FetchResult<TData>> {
  try {
    return await call;
  } catch (cause) {
    // Своя ошибка, брошенная до запроса — например, «из токена не собрать заголовок»,
    // — приходит сюда так же, как обрыв сети. Превращать её в `network_error` значит
    // соврать про причину: запроса не было, и бэкенд ни при чём.
    if (cause instanceof ApiError) throw cause;
    throw ApiError.network(cause);
  }
}
