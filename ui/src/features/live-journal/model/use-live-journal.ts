import { useEffect, useRef, useState } from 'react';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { markSessionExpired, sessionKeys, type Bootstrap } from '@/entities/session';
import { clearToken, getToken } from '@/shared/api';
import { parseFrame, type JournalFrame } from './frames';
import { keysToInvalidate } from './invalidation';
import { openJournalStream } from './stream-client';

/** Что показывает индикатор в шапке. */
export type LiveStatus = 'connecting' | 'live' | 'reconnecting';

export interface LiveJournal {
  status: LiveStatus;
  /** Вопрос, адресованный этому человеку, пришедший при открытом приложении. */
  incomingQuestion: { taskKey: string; no: number } | null;
  dismissQuestion: () => void;
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
  const [incomingQuestion, setIncomingQuestion] = useState<LiveJournal['incomingQuestion']>(null);

  /** Последний прочитанный `seq`: с него поток продолжается после обрыва. */
  const cursor = useRef<number | null>(null);
  /** Что перечитать, когда человек вернётся во вкладку. */
  const pending = useRef<QueryKey[]>([]);
  /** Связь уже теряли: первое открытие потока и восстановление — разные события. */
  const reconnected = useRef(false);

  useEffect(() => {
    const token = getToken();
    if (token === null) return;

    /**
     * Ключи копятся, пока вкладка в фоне: перечитывать невидимое незачем, но и терять
     * кадры нельзя — человек вернётся и должен увидеть то, что есть на самом деле.
     */
    function invalidate(keys: QueryKey[]): void {
      if (document.hidden) {
        pending.current.push(...keys);
        return;
      }
      for (const key of keys) void queryClient.invalidateQueries({ queryKey: key });
    }

    function applyPending(): void {
      if (document.hidden || pending.current.length === 0) return;
      const keys = pending.current;
      pending.current = [];
      for (const key of keys) void queryClient.invalidateQueries({ queryKey: key });
    }

    function onFrame(frame: JournalFrame): void {
      cursor.current = frame.seq;
      invalidate(keysToInvalidate(frame));

      if (frame.entry.type !== 'question') return;
      // Вопрос интересен человеку, только если спросили его самого.
      const me = queryClient.getQueryData<Bootstrap>(sessionKeys.bootstrap)?.participant?.name;
      if (me === undefined || me === null) return;
      if (frame.entry.payload.addressees.includes(me)) {
        setIncomingQuestion({ taskKey: frame.taskKey, no: frame.entry.no });
      }
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
        invalidate([['tasks'], ['task'], ['questions'], sessionKeys.bootstrap]);
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
    incomingQuestion,
    dismissQuestion: () => setIncomingQuestion(null),
  };
}
