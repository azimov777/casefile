import { vi } from 'vitest';
import type { StreamOptions } from '@/features/live-journal';

/**
 * Подмена живого потока для страничных тестов.
 *
 * Настоящий клиент (`@microsoft/fetch-event-source`) в jsdom не работает вовсе: он
 * создаёт свой `AbortController` из jsdom, а `fetch` в этом окружении из Node, и они
 * друг друга не принимают. Поэтому в тестах подменяется ровно граница «как открыть
 * поток», а вся наша логика — курсор, инвалидация, статус, уведомление о вопросе —
 * проверяется на настоящем хуке. Сам SSE проверяется сквозным тестом в браузере.
 */
export const liveJournal = {
  /** Параметры последнего открытого потока: через них тест шлёт кадры. */
  options: null as StreamOptions | null,
  /** Сколько раз приложение открывало поток за прогон. */
  connections: 0,
  closed: 0,

  /** Кадр журнала так, как его отдаёт бэкенд: тело записи строкой JSON. */
  send(entry: Record<string, unknown>): void {
    this.options?.onMessage(JSON.stringify(entry));
  },

  reset(): void {
    this.options = null;
    this.connections = 0;
    this.closed = 0;
  },
};

vi.mock('@/features/live-journal/model/stream-client', () => ({
  openJournalStream: (options: StreamOptions) => {
    liveJournal.options = options;
    liveJournal.connections += 1;
    // Настоящий поток отвечает открытием почти сразу; повторяем это, чтобы состояние
    // «на связи» в тестах достигалось так же, как в браузере.
    options.onOpen();
    return () => {
      liveJournal.closed += 1;
    };
  },
}));
