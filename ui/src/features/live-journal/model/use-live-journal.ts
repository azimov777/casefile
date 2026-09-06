import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { markSessionExpired, sessionKeys, type Bootstrap } from '@/entities/session';
import { clearToken, getToken } from '@/shared/api';
import { holdForRequest, holdWhileHidden, releaseHidden } from './deferred';
import { parseFrame, type JournalFrame } from './frames';
import { keysAfterReconnect, keysToInvalidate, type Invalidation } from './invalidation';
import { openJournalStream } from './stream-client';

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

  useEffect(() => {
    const token = getToken();
    if (token === null) return;

    /**
     * Раскладывает устаревшее по двум срокам.
     *
     * Список и доска не перечитываются никогда сами: они ждут, пока человек нажмёт
     * «показать» (`deferred.ts`). Всё остальное перечитывается сразу — или копится до
     * возврата во вкладку, потому что перечитывать невидимое незачем, а терять кадры
     * нельзя.
     */
    function invalidate({ immediate, deferred }: Invalidation, taskKey: string | null): void {
      holdForRequest(deferred, taskKey);

      if (document.hidden) {
        holdWhileHidden(immediate);
        return;
      }
      for (const key of immediate) void queryClient.invalidateQueries({ queryKey: key });
    }

    function applyPending(): void {
      if (document.hidden) return;
      for (const key of releaseHidden()) void queryClient.invalidateQueries({ queryKey: key });
    }

    function onFrame(frame: JournalFrame): void {
      cursor.current = frame.seq;
      invalidate(keysToInvalidate(frame), frame.taskKey);

      if (frame.entry.type !== 'question') return;
      // Вопрос интересен человеку, только если спросили его самого.
      const me = queryClient.getQueryData<Bootstrap>(sessionKeys.bootstrap)?.participant?.name;
      if (me === undefined || me === null) return;
      if (!frame.entry.payload.addressees.includes(me)) return;

      const id = `${frame.taskKey}#${frame.entry.no}`;
      if (announced.current.has(id)) return;
      announced.current.add(id);

      // Собирается до `setState`, а не внутри него: разбор по `type` живёт только
      // в прямом коде — внутри замыкания компилятор о нём уже не помнит и видит
      // нагрузку всех пятнадцати типов записи разом.
      const question: IncomingQuestion = {
        id,
        taskKey: frame.taskKey,
        no: frame.entry.no,
        title: frame.entry.title,
        blocking: frame.entry.payload.blocking,
      };
      setIncomingQuestions((shown) => [...shown, question]);
    }

    document.addEventListener('visibilitychange', applyPending);

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
        // Токен перестал годиться: дальше работает общая обработка входа
        // (`SessionWatcher` снимет кэш, страж маршрутов уведёт на вход).
        clearToken();
        markSessionExpired();
      },
    });

    return () => {
      document.removeEventListener('visibilitychange', applyPending);
      close();
    };
  }, [queryClient]);

  return {
    status,
    incomingQuestions,
    // Закрытое убирается с экрана, но остаётся в `announced`: человек сказал «видел».
    dismissQuestion: (id: string) =>
      setIncomingQuestions((shown) => shown.filter((question) => question.id !== id)),
  };
}
