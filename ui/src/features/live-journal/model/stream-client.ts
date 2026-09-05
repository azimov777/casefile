import { fetchEventSource } from '@microsoft/fetch-event-source';
import { apiBaseUrl } from '@/shared/api';

export interface StreamOptions {
  token: string;
  /** С какого `seq` продолжать. `null` — с текущего конца ленты. */
  after: number | null;
  onOpen: () => void;
  onMessage: (data: string) => void;
  /** Связи нет: идёт переподключение через названную паузу. */
  onLost: () => void;
  /** Токен больше не годится: поток закрыт навсегда. */
  onUnauthorized: () => void;
}

/** Пауза перед переподключением: растёт вдвое, но не дольше полуминуты. */
const FIRST_RETRY = 1_000;
const MAX_RETRY = 30_000;

/**
 * Открывает поток журнала и возвращает функцию закрытия.
 *
 * Отдельным модулем, а не внутри хука, по двум причинам. Первая: браузерный
 * `EventSource` не шлёт заголовков, а токен в адресе уехал бы в журналы прокси —
 * поэтому здесь `fetch`-клиент, и всё, что относится к устройству SSE, собрано
 * в одном месте. Вторая: в jsdom эта библиотека не работает вовсе (её `AbortSignal`
 * не принимает `fetch` из Node), поэтому в страничных тестах модуль подменяется,
 * а сам поток проверяется сквозным тестом в настоящем браузере.
 */
export function openJournalStream(options: StreamOptions): () => void {
  const controller = new AbortController();
  let attempt = 0;

  void fetchEventSource(`${apiBaseUrl}/api/v1/journal/stream`, {
    signal: controller.signal,
    // Вкладка в фоне поток не закрывает: иначе каждое переключение вкладок стоило бы
    // переподключения, а кадры за это время терялись бы.
    openWhenHidden: true,

    headers: {
      Authorization: `Bearer ${options.token}`,
      ...(options.after === null ? {} : { 'Last-Event-ID': String(options.after) }),
    },

    onopen: async (response) => {
      if (response.ok) {
        attempt = 0;
        options.onOpen();
        return;
      }
      if (response.status === 401) {
        options.onUnauthorized();
        throw new FatalStreamError();
      }
      throw new Error(`Поток журнала ответил ${response.status}`);
    },

    onmessage: (message) => options.onMessage(message.data),

    onerror: (error) => {
      if (error instanceof FatalStreamError) throw error;
      options.onLost();
      attempt += 1;
      return Math.min(FIRST_RETRY * 2 ** (attempt - 1), MAX_RETRY);
    },

    // Сервер закрыл поток штатно — для нас это обрыв: возвращаемся через паузу.
    onclose: () => {
      options.onLost();
      throw new Error('Поток журнала закрыт сервером');
    },
  });

  return () => controller.abort();
}

/** Отказ, после которого переподключаться бессмысленно. */
class FatalStreamError extends Error {}
