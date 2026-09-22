import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './openapi';
import { apiBaseUrl } from './base-url';
import { ApiError, CLIENT_ERROR_CODES } from './error';
import { refreshInstallToken } from './install-config';
import { authorizationHeader, clearToken, getInstallToken, getToken } from './token';

export { apiBaseUrl };

/**
 * Отправляет запрос и один раз переспрашивает установку, если ей же выданный ключ
 * получил `401`.
 *
 * Случай, ради которого это есть: контур переподняли, установка выпустила новый ключ,
 * а открытая вкладка держит прежний. Человек в этом не участвовал и участвовать
 * не должен — на локальной установке ему некуда «войти заново».
 *
 * Почему повтор живёт здесь, а не в перехватчике `onResponse`: к моменту ответа тело
 * исходного запроса уже прочитано, и повторить его оттуда нечем. Клон снимается до
 * отправки. Перехватчик при этом видит уже итог — либо удачный повтор, либо второй
 * отказ, и тогда работает прежняя ветка «сеанс истёк».
 *
 * Ключ, введённый человеком, сюда не попадает: его отказ — это истёкший сеанс, а не
 * устаревшая конфигурация. Отличаются они сравнением заголовка с тем, что собрался бы
 * из ключа установки, — так экран входа, проверяющий чужое значение своим заголовком,
 * не выдаёт себя за неё.
 */
async function fetchWithInstallKey(request: Request): Promise<Response> {
  const install = getInstallToken();
  const sent = install === null ? null : authorizationHeader(install);
  const retryable =
    sent !== null && request.headers.get('Authorization') === sent ? request.clone() : null;

  const response = await globalThis.fetch(request);
  if (response.status !== 401 || retryable === null || install === null) return response;

  const fresh = await refreshInstallToken(install);
  const header = fresh === null ? null : authorizationHeader(fresh);
  if (header === null) {
    /*
     * Установка ключа больше не даёт: в режиме входа — сеанс кончился, закрыт выходом в
     * соседней вкладке, сбросом пароля или отключением учётной записи. Ключ вкладки к
     * этому моменту уже забыт (`refreshInstallToken`), и перехватчик ниже отказ не
     * заметит — он смотрит на действующий ключ. Поэтому о конце сеанса говорится здесь:
     * иначе человек оказался бы на экране входа без объяснения, почему.
     */
    if (getToken() === null) {
      for (const listener of expiredListeners) listener();
    }
    return response;
  }

  retryable.headers.set('Authorization', header);
  return globalThis.fetch(retryable);
}

export const apiClient = createClient<paths>({
  baseUrl: apiBaseUrl,
  // Позднее связывание с `globalThis.fetch`: по умолчанию библиотека запоминает ссылку
  // на функцию в момент создания клиента, и подмена сети в тестах (MSW ставит свой
  // `fetch` позже) проходила бы мимо клиента.
  fetch: (request) => fetchWithInstallKey(request),
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
      if (token !== null) {
        const header = authorizationHeader(token);
        if (header === null) {
          // Сохранённый токен испорчен: заголовка из него не выйдет, и запроса
          // не будет. Для человека это тот же случай, что истёкший сеанс, — его
          // ведут на вход. Молча ронять запрос нельзя: он выглядел бы отказом сети.
          clearToken();
          for (const listener of expiredListeners) listener();
          throw new ApiError(
            CLIENT_ERROR_CODES.tokenNotHeaderSafe,
            'Stored token cannot be put into a header',
            0,
            {},
          );
        }
        request.headers.set('Authorization', header);
      }
    }
    return request;
  },

  onResponse({ response }) {
    // Отказ на проверке ещё не сохранённого токена — дело экрана входа, а не сеанса:
    // сбрасывать и объявлять просроченным нечего.
    //
    // Ключ от установки доходит сюда только вторым отказом: первый уже переспросил
    // конфигурацию (`fetchWithInstallKey`). Забывается он вместе с сохранённым —
    // иначе страж пускал бы человека внутрь по ключу, которым ничего не открыть.
    if (response.status === 401 && getToken() !== null) {
      clearToken();
      for (const listener of expiredListeners) listener();
    }
    return response;
  },
};

apiClient.use(authMiddleware);
