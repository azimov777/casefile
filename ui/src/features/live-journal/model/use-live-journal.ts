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
  taskKey: string;
  no: number;
  /** Строка описи записи: то, чем вопрос назван, а не всё его тело. */
  title: string;
  blocking: boolean;
}

export interface LiveJournal {
  status: LiveStatus;
  /** Все непрочитанные, в порядке прихода: второй вопрос не затирает первый. */
  incomingQuestions: IncomingQuestion[];
  dismissQuestion: (id: string) => void;
}

/**
 * Один живой поток на вкладку: по кадрам журнала перечитывается то, на что человек
 * сейчас смотрит (`CONCEPT.md`, 5).
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

  /** Последний прочитанный `seq`: с него поток продолжается после обрыва. */
  const cursor = useRef<number | null>(null);
  /** Связь уже теряли: первое открытие потока и восстановление — разные события. */
  const reconnected = useRef(false);
  /**
   * Вопросы, о которых человеку уже сказали, — показанные и закрытые вместе.
   *
   * Поток продолжается по `Last-Event-ID`, а граница там по включению: тот же кадр
   * приезжает второй раз на каждом переподключении. Без этой памяти закрытое
   * уведомление воскресало бы от каждого моргания сети, а человек переставал бы
   * закрывать их вовсе.
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

    /**
     * Раскладывает устаревшее по трём срокам (`deferred.ts`).
     *
     * Таблица не перечитывается потоком никогда: она ждёт, пока человек нажмёт
     * «показать» или перечитает её сам — приходом на экран, сменой отбора; накопленное
     * снимает любое её чтение (`table-reads.ts`). Доска перечитывается сама, но окном
     * склейки, а не на каждый кадр. Всё остальное — сразу. Невидимая вкладка
     * не перечитывает ничего вовсе: перечитывать то, на что никто не смотрит, незачем,
     * а терять кадры нельзя — потому они копятся до возврата.
     */
    function invalidate(
      { immediate, coalesced, deferred }: Invalidation,
      taskKey: string | null,
    ): void {
      holdForRequest(deferred, taskKey);

      if (document.hidden) {
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
      // Вопрос интересен человеку, только если спросили его самого. Тип записи сузил
      // `frame.entry` до варианта задачи: у него `task_key` — всегда строка, вопросов
      // в деле проекта не бывает (TRK-156).
      const me = queryClient.getQueryData<Bootstrap>(sessionKeys.bootstrap)?.participant?.name;
      if (me === undefined || me === null) return;
      if (!frame.entry.payload.addressees.includes(me)) return;

      const id = `${frame.entry.task_key}#${frame.entry.no}`;
      if (announced.current.has(id)) return;
      announced.current.add(id);

      // Собирается до `setState`, а не внутри него: разбор по `type` живёт только
      // в прямом коде — внутри замыкания компилятор о нём уже не помнит и видит
      // нагрузку всех пятнадцати типов записи разом.
      const question: IncomingQuestion = {
        id,
        taskKey: frame.entry.task_key,
        no: frame.entry.no,
        title: frame.entry.title,
        blocking: frame.entry.payload.blocking,
      };
      setIncomingQuestions((shown) => [...shown, question]);
    }

    document.addEventListener('visibilitychange', applyPending);
    const unsubscribe = subscribeWindowClosed(applyWindowed);

    const close = openJournalStream({
      token,
      after: cursor.current,

      onOpen: () => {
        setStatus('live');

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

      onMessage: (data) => {
        const frame = parseFrame(data);
        if (frame !== null) onFrame(frame);
      },

      onLost: () => {
        reconnected.current = true;
        setStatus('reconnecting');
      },

      onUnauthorized: () => {
        /*
         * Токен перестал годиться. Если он от установки, её сначала переспрашивают —
         * ровно один раз, той же дверью, что и запросы: контур могли переподнять, и
         * тогда поток переоткроется свежим ключом сменой зависимости эффекта.
         * Ключ, введённый человеком, отвечает `null` сразу.
         *
         * Дальше работает общая обработка входа: `SessionWatcher` снимет кэш, страж
         * маршрутов уведёт на вход.
         */
        void refreshInstallToken(token).then((fresh) => {
          if (fresh !== null) return;
          clearToken();
          markSessionExpired();
        });
      },
    });

    return () => {
      document.removeEventListener('visibilitychange', applyPending);
      unsubscribe();
      close();
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
