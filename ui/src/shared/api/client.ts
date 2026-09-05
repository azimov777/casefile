import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './openapi';
import { clearToken, getToken } from './token';

/**
 * Клиент API. Базовый адрес пуст: и dev-сервер Vite, и nginx в образе проксируют
 * `/api` на бэкенд, поэтому запрос всегда идёт на свой источник. Так токен не уезжает
 * в чужой источник и не нужен CORS.
 */
export const apiClient = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
  // Позднее связывание с `globalThis.fetch`: по умолчанию библиотека запоминает ссылку
  // на функцию в момент создания клиента, и подмена сети в тестах (MSW ставит свой
  // `fetch` позже) проходила бы мимо клиента.
  fetch: (request) => globalThis.fetch(request),
});

type Listener = () => void;

const expiredListeners = new Set<Listener>();

/**
 * Подписка на «сохранённый токен больше не годится»: приложение сбрасывает состояние
 * и ведёт человека на вход. Событие приходит из перехватчика ниже, а не с каждой
 * страницы: `401` может прийти на любой запрос.
 */
export function onSessionExpired(listener: Listener): () => void {
  expiredListeners.add(listener);
  return () => {
    expiredListeners.delete(listener);
  };
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    // Явно переданный заголовок не трогаем: так экран входа проверяет ещё не
    // сохранённый токен тем же клиентом.
    if (!request.headers.has('Authorization')) {
      const token = getToken();
      if (token !== null) request.headers.set('Authorization', `Bearer ${token}`);
    }
    return request;
  },

  onResponse({ response }) {
    // Отказ на проверке ещё не сохранённого токена — дело экрана входа, а не сеанса:
    // сбрасывать и объявлять просроченным нечего.
    if (response.status === 401 && getToken() !== null) {
      clearToken();
      for (const listener of expiredListeners) listener();
    }
    return response;
  },
};

apiClient.use(authMiddleware);
