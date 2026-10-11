import { fetchEventSource } from '@microsoft/fetch-event-source';
import { apiBaseUrl, authorizationHeader } from '@/shared/api';

export interface StreamOptions {
  token: string;
  /** С какого `seq` продолжать. `null` — с текущего конца ленты. */
  after: number | null;
  onOpen: () => void;
  /**
   * Поток назвал свою позицию — `seq`, после которого он выдаёт записи. Приходит первым
   * блоком каждого открытия, до первой записи: с `after` это сам `after`, без него —
   * конец ленты на момент открытия. `0` — законная позиция: лента пуста.
   */
  onPosition: (seq: number) => void;
  /** Кадр записи: её тело строкой JSON. */
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
 * Заголовок позиции — тем же ключом, каким его ведёт библиотека.
 *
 * Номер последнего блока она запоминает сама, для своих повторов после обрыва, и кладёт
 * в тот же объект заголовков ключом в нижнем регистре. Положи мы свой ключом
 * `Last-Event-ID`, в объекте стало бы два ключа одного заголовка: браузер склеил бы
 * значения через запятую, бэкенд такую позицию не разбирает, и поток, однажды открытый
 * с позиции, после первого же обрыва не открылся бы уже никогда.
 */
const LAST_EVENT_ID = 'last-event-id';

/** Номер из `id:` блока. Блок без номера — тик — позиции не называет. */
function parsePosition(id: string): number | null {
  return /^\d+$/.test(id) ? Number(id) : null;
}

/**
 * Открывает поток журнала и возвращает функцию закрытия.
 *
 * Отдельным модулем, а не внутри хука, по двум причинам. Первая: браузерный
 * `EventSource` не шлёт заголовков, а токен в адресе уехал бы в журналы прокси —
 * поэтому здесь `fetch`-клиент, и всё, что относится к устройству SSE, собрано
 * в одном месте. Вторая: в jsdom эта библиотека не работает вовсе (её `AbortSignal`
 * не принимает `fetch` из Node), поэтому в страничных тестах модуль подменяется,
 * а сам поток проверяется сквозным тестом в настоящем браузере.
 *
 * Обработчики зовутся из сети, то есть не раньше, чем этот вызов вернёт функцию
 * закрытия; исключение одно — `onUnauthorized` для токена, из которого не собрать
 * заголовок. После закрытия не зовётся ни один: закрытый поток молчит, даже если
 * в уже прочитанном куске ответа остались блоки.
 */
export function openJournalStream(options: StreamOptions): () => void {
  const controller = new AbortController();
  let attempt = 0;

  /*
   * Токен, из которого не собрать заголовок, поток не откроет никогда. Без этой
   * ветки библиотека молча падала бы на каждой попытке, и человек видел бы вечное
   * «нет связи» — единственное объяснение, и притом неверное. Для него это тот же
   * случай, что истёкший сеанс: его ведут на вход.
   */
  const authorization = authorizationHeader(options.token);
  if (authorization === null) {
    options.onUnauthorized();
    return () => controller.abort();
  }

  void fetchEventSource(`${apiBaseUrl}/api/v1/journal/stream`, {
    signal: controller.signal,
    // Видимостью вкладки управляет хук, а не библиотека: её режим закрывает поток
    // только по событию смены видимости, и вкладка, открытая в фоне, держала бы
    // соединение до первого переключения.
    openWhenHidden: true,

    headers: {
      Authorization: authorization,
      ...(options.after === null ? {} : { [LAST_EVENT_ID]: String(options.after) }),
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

    onmessage: (message) => {
      // Поток закрыли из его же обработчика, а библиотека дочитывает уже полученный
      // кусок ответа до конца. Остальные блоки куска не отдаются: их принесёт следующее
      // открытие — позиция осталась на последнем отданном блоке.
      if (controller.signal.aborted) return;
      if (message.data !== '') {
        options.onMessage(message.data);
        return;
      }
      const position = parsePosition(message.id);
      if (position !== null) options.onPosition(position);
    },

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
