import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  markSessionExpired,
  sessionKeys,
  useSessionToken,
  type Bootstrap,
} from '@/entities/session';
import { clearToken, getToken, refreshInstallToken } from '@/shared/api';
import {
  holdForRequest,
  holdForWindow,
  holdWhileHidden,
  releaseHidden,
  releaseWindowed,
  subscribeWindowClosed,
} from './deferred';
import { parseFrame, type JournalFrame } from './frames';
import { keysAfterReconnect, keysToInvalidate, type Invalidation } from './invalidation';
import { openJournalStream } from './stream-client';
import { watchTableReads } from './table-reads';

/**
 * Что показывает индикатор в шапке.
 *
 * `connecting` и `reconnecting` разделены не ради полноты: первое — обычное начало
 * работы, второе — потеря связи. Слив их в одно, интерфейс краснел бы на каждой
 * загрузке страницы и приучал бы не верить красному.
 */
export type LiveStatus = 'connecting' | 'live' | 'reconnecting';

/** Вопрос, адресованный этому человеку и пришедший при открытом приложении. */
export interface IncomingQuestion {
  /**
   * Пара «задача и номер записи»: она же признак того, что это тот же самый вопрос.
   * Больше ничем один вопрос от другого не отличить — номер уникален внутри задачи.
   */
  id: string;
  /** Задача, в деле которой задан вопрос; `null` у вопроса обсуждения. */
  taskKey: string | null;
  /** Адрес обсуждения `TRK~7`, в деле которого задан вопрос; `null` у вопроса в деле задачи. */
  discussion: string | null;
  no: number;
  /** Строка описи записи: то, чем вопрос назван, а не всё его тело. */
  title: string;
  blocking: boolean;
}

/**
 * Сколько поток должен молчать, чтобы пачку пропущенного считать отданной.
 *
 * Поток, открытый с позиции, первым делом отдаёт всё, что случилось после неё, — подряд,
 * без пауз, — и только потом ждёт новых записей. Конец пачки поток не называет, поэтому
 * он узнаётся по тишине. Ошибиться можно в обе стороны, и обе безвредны: тишина,
 * наступившая посреди пачки, оставит хвост перечитываться по кадру, а запись,
 * пришедшая сразу за пачкой, подождёт перечитывания ещё одну такую паузу.
 */
const CATCH_UP_QUIET_MS = 150;

export interface LiveJournal {
  status: LiveStatus;
  /** Все непрочитанные, в порядке прихода: второй вопрос не затирает первый. */
  incomingQuestions: IncomingQuestion[];
  dismissQuestion: (id: string) => void;
}

/**
 * Живой поток вкладки: по кадрам журнала перечитывается то, на что человек сейчас
 * смотрит. Поток держит только видимая вкладка, скрытая догоняет при возврате (TRK-697).
 *
 * Хук поднимается один раз в оболочке приложения: страницы своих потоков не открывают,
 * иначе каждый переход между экранами стоил бы нового соединения.
 */
export function useLiveJournal(): LiveJournal {
  const queryClient = useQueryClient();
  /*
   * Ключ берётся подпиской, а не разовым `getToken()`: у него два источника, и ключ
   * от установки может смениться прямо посреди работы вкладки — контур переподняли.
   * Смена значения пересобирает эффект, то есть закрывает поток и открывает новый
   * тем ключом, которым уже ходят запросы.
   */
  const token = useSessionToken();
  const [status, setStatus] = useState<LiveStatus>('connecting');
  const [incomingQuestions, setIncomingQuestions] = useState<IncomingQuestion[]>([]);

  /**
   * Позиция вкладки в журнале: `seq`, после которого ей ещё ничего не приходило.
   * Называет её первый блок потока, двигает каждый кадр записи; с неё поток
   * продолжается после обрыва, смены ключа и возврата вкладки из фона. `null` —
   * позиции ещё нет. `0` — позиция пустого журнала, поэтому сверяется она с `null`,
   * а не на истинность.
   */
  const cursor = useRef<number | null>(null);
  /** Связь уже теряли: первое открытие потока и восстановление — разные события. */
  const reconnected = useRef(false);
  /**
   * Вопросы, о которых человеку уже сказали, — показанные и закрытые вместе.
   *
   * Поток продолжается по `Last-Event-ID`, и граница там исключающая: установка тот же
   * кадр второй раз не шлёт (TRK/ui-api#60). Память — защита на случай, если он всё же
   * приедет: закрытое уведомление не должно воскресать от моргания сети, иначе человек
   * перестал бы закрывать их вовсе.
   */
  const announced = useRef(new Set<string>());

  /*
   * Полосу таблицы копит поток, а снимает чтение таблицы, кто бы его ни вызвал (UI-95).
   * Слежение живёт здесь, а не на странице: страница может быть уже снята, когда ответ
   * ляжет, — ушли в карточку посреди чтения, — и исход чтения ушёл бы мимо полосы.
   * Эффект свой, а не общий с потоком: смена ключа переоткрывает поток, а слежению
   * переподписываться незачем — кэш тот же.
   */
  useEffect(() => watchTableReads(queryClient), [queryClient]);

  useEffect(() => {
    /*
     * Ключ мог пропасть между отрисовкой и эффектом: испорченное значение сбрасывает
     * перехватчик прямо на первом запросе экрана, и происходит это раньше, чем сюда
     * доходит очередь. Поток, открытый снимком с отрисовки, был бы открыт тем, чего
     * уже нет; эффект перезапустится со свежим значением сам.
     */
    if (token === null || getToken() !== token) return;
    // Объявленным ниже функциям ключ нужен уже строкой: сужение до них не доходит.
    const key = token;

    /** Поток этого эффекта — функция его закрытия. `null` — потока сейчас нет. */
    let close: (() => void) | null = null;
    /**
     * Этот ключ бэкенд отверг, и поток им больше не открывается: дальше либо придёт
     * свежий ключ и эффект пересоберётся, либо человека уведут на вход. Без этой памяти
     * каждый возврат во вкладку за это время повторял бы отказ.
     */
    let refused = false;
    /**
     * Вкладка догоняет пропущенное: поток открыт с позиции и ещё не затих. Всё, что он
     * отдаёт в это время, случилось, пока потока не было, и применяется разом — как
     * накопленное за время в фоне, чем оно и является. Перечитывать по кадру здесь
     * нельзя: сотня записей открытой задачи, подшитых в фоне, стоила бы сотни чтений
     * её карточки подряд (замер TRK-697).
     */
    let catchingUp = false;
    /** Отсчёт тишины, которой кончается пачка пропущенного. */
    let quiet: ReturnType<typeof setTimeout> | null = null;

    /**
     * Раскладывает устаревшее по трём срокам (`deferred.ts`).
     *
     * Таблица не перечитывается потоком никогда: она ждёт, пока человек нажмёт
     * «показать» или перечитает её сам — приходом на экран, сменой отбора; накопленное
     * снимает любое её чтение (`table-reads.ts`). Доска перечитывается сама, но окном
     * склейки, а не на каждый кадр. Всё остальное — сразу. Невидимая вкладка
     * не перечитывает ничего вовсе: перечитывать то, на что никто не смотрит, незачем.
     * Потока у неё нет, и кадры она получит после возврата — пачкой, которая копится
     * в том же сроке «до возврата» и уходит одним перечитыванием, когда поток затихнет.
     * При скрытой вкладке сюда доходит только восстановление после обрыва, случившегося,
     * пока она ждала первого блока.
     */
    function invalidate(
      { immediate, coalesced, deferred }: Invalidation,
      taskKey: string | null,
    ): void {
      holdForRequest(deferred, taskKey);

      if (document.hidden || catchingUp) {
        holdWhileHidden([...immediate, ...coalesced]);
        return;
      }
      for (const key of immediate) void queryClient.invalidateQueries({ queryKey: key });
      holdForWindow(coalesced);
    }

    function applyPending(): void {
      if (document.hidden) return;
      for (const key of releaseHidden()) void queryClient.invalidateQueries({ queryKey: key });
    }

    /**
     * Окно склейки закрылось: накопленное уходит одним перечитыванием.
     *
     * Вкладка могла уйти в фон, пока окно шло. Тогда накопленное не выбрасывается и не
     * перечитывается, а переезжает в срок «до возврата»: правило «невидимое не читаем»
     * старше окна, а забытый кадр человек уже ничем не догонит.
     */
    function applyWindowed(): void {
      const keys = releaseWindowed();
      if (keys.length === 0) return;
      if (document.hidden) {
        holdWhileHidden(keys);
        return;
      }
      for (const key of keys) void queryClient.invalidateQueries({ queryKey: key });
    }

    function onFrame(frame: JournalFrame): void {
      cursor.current = frame.seq;
      invalidate(keysToInvalidate(frame), frame.taskKey);

      if (frame.entry.type !== 'question') return;
      // Вопрос интересен человеку, только если спросили его самого. Вопросов в деле
      // проекта не бывает (TRK-156); вопрос обсуждения (TRK-669) владельцем называет
      // `discussion`, и `task_key` у него пуст — уведомление о нём ведёт на экран
      // обсуждения (TRK-672).
      const taskKey = frame.entry.task_key;
      const discussion = frame.entry.discussion ?? null;
      const owner = taskKey ?? discussion;
      if (owner === null) return;
      const me = queryClient.getQueryData<Bootstrap>(sessionKeys.bootstrap)?.participant?.name;
      if (me === undefined || me === null) return;
      if (!frame.entry.payload.addressees.includes(me)) return;

      const id = `${owner}#${frame.entry.no}`;
      if (announced.current.has(id)) return;
      announced.current.add(id);

      // Собирается до `setState`, а не внутри него: разбор по `type` живёт только
      // в прямом коде — внутри замыкания компилятор о нём уже не помнит и видит
      // нагрузку всех пятнадцати типов записи разом.
      const question: IncomingQuestion = {
        id,
        taskKey,
        discussion,
        no: frame.entry.no,
        title: frame.entry.title,
        blocking: frame.entry.payload.blocking,
      };
      setIncomingQuestions((shown) => [...shown, question]);
    }

    /** Поток затих: пропущенное отдано, и накопленное уходит одним перечитыванием. */
    function caughtUp(): void {
      quiet = null;
      catchingUp = false;
      applyPending();
    }

    /** Поток открылся или отдал ещё блок: тишина отсчитывается заново. */
    function awaitQuiet(): void {
      if (!catchingUp) return;
      if (quiet !== null) clearTimeout(quiet);
      quiet = setTimeout(caughtUp, CATCH_UP_QUIET_MS);
    }

    function open(): void {
      // С позиции поток начнёт с пропущенного; без неё — с конца журнала, и догонять нечего.
      catchingUp = cursor.current !== null;
      if (quiet !== null) clearTimeout(quiet);
      quiet = null;

      close = openJournalStream({
        token: key,
        after: cursor.current,

        onOpen: () => {
          setStatus('live');
          awaitQuiet();

          // Перечитываем показанное только после обрыва: в паузу могло случиться что
          // угодно, и догонять пропущенные кадры поштучно интерфейс не станет. На первом
          // открытии перечитывать нечего — страница только что спросила всё сама, а лишний
          // запрос здесь означал бы два обращения к списку на одну отрисовку.
          if (!reconnected.current) return;
          reconnected.current = false;
          // Задача не названа: за время обрыва могло измениться что угодно, и числа для
          // полосы взять неоткуда — она скажет об этом словами, а не выдуманным числом.
          invalidate(keysAfterReconnect(), null);
        },

        onPosition: (seq) => {
          cursor.current = seq;
          awaitQuiet();
          // Скрытая вкладка ждала только этого: позиция есть — поток больше не нужен.
          follow();
        },

        onMessage: (data) => {
          const frame = parseFrame(data);
          if (frame !== null) onFrame(frame);
          awaitQuiet();
        },

        onLost: () => {
          reconnected.current = true;
          setStatus('reconnecting');
        },

        onUnauthorized: () => {
          refused = true;
          /*
           * Токен перестал годиться. Если он от установки, её сначала переспрашивают —
           * ровно один раз, той же дверью, что и запросы: контур могли переподнять, и
           * тогда поток переоткроется свежим ключом сменой зависимости эффекта.
           * Ключ, введённый человеком, отвечает `null` сразу.
           *
           * Дальше работает общая обработка входа: `SessionWatcher` снимет кэш, страж
           * маршрутов уведёт на вход.
           */
          void refreshInstallToken(key).then((fresh) => {
            if (fresh !== null) return;
            clearToken();
            markSessionExpired();
          });
        },
      });
    }

    /**
     * Приводит поток в соответствие с видимостью вкладки.
     *
     * Поток держит только видимая вкладка. Соединений на адрес браузер даёт шесть, поток
     * занимает одно на всё время жизни, и вкладки, державшие его в фоне, оставляли без
     * сети всё, что открыто после пятой. Скрытой вкладке поток нужен ровно до первого
     * блока — узнать позицию; вкладка, открытая в фоне, за этим его и открывает. Дальше
     * потока нет, а случившееся за время в фоне приходит кадрами после возврата,
     * с позиции: записи постоянны, граница исключающая — без пропусков и повторов.
     * Приходит оно пачкой и применяется разом (`catchingUp`).
     *
     * Закрытие здесь — не обрыв: статус остаётся каким был, и перечитывать показанное
     * после возврата незачем. Обрыв, случившийся до ухода в фон, обрывом и остаётся:
     * закрытие его не забывает, и возврат перечитает показанное, как после любого
     * восстановления.
     */
    function follow(): void {
      if (refused) return;
      if (document.hidden && cursor.current !== null) {
        close?.();
        close = null;
        return;
      }
      if (close === null) open();
    }

    function onVisibility(): void {
      applyPending();
      follow();
    }

    document.addEventListener('visibilitychange', onVisibility);
    const unsubscribe = subscribeWindowClosed(applyWindowed);
    follow();

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      unsubscribe();
      if (quiet !== null) clearTimeout(quiet);
      close?.();
    };
  }, [queryClient, token]);

  return {
    status,
    incomingQuestions,
    // Закрытое убирается с экрана, но остаётся в `announced`: человек сказал «видел».
    dismissQuestion: (id: string) =>
      setIncomingQuestions((shown) => shown.filter((question) => question.id !== id)),
  };
}
