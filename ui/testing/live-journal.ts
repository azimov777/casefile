import { vi } from 'vitest';
import type { StreamOptions } from '@/features/live-journal';

/**
 * Подмена живого потока для страничных тестов.
 *
 * Настоящий клиент (`@microsoft/fetch-event-source`) в jsdom не работает вовсе: он
 * создаёт свой `AbortController` из jsdom, а `fetch` в этом окружении из Node, и они
 * друг друга не принимают. Поэтому в тестах подменяется ровно граница «как открыть
 * поток», а вся наша логика — позиция, видимость вкладки, инвалидация, статус,
 * уведомление о вопросе — проверяется на настоящем хуке. Сам SSE проверяется сквозным
 * тестом в браузере.
 *
 * Подмена ведёт себя как бэкенд, а не как труба. Запись (`send`) ложится в журнал.
 * Открытый поток получает её кадром сразу; закрытого потока для неё нет, и придёт она
 * только тому, кто откроется с позиции раньше неё. Каждый открытый поток первым блоком
 * называет свою позицию: `after`, с которым его открыли, либо конец журнала.
 */

/** Один открытый приложением поток. */
interface Stream {
  options: StreamOptions;
  /** Позиция, которую поток называет первым блоком: после неё он выдаёт записи. */
  start: number;
  /** Первый блок уже отдан: до него записи потоку не идут. */
  named: boolean;
  /** Приложение поток ещё не закрыло: закрытому не приходит ничего. */
  alive: boolean;
}

/** Конец журнала подмены, пока в него ничего не подшито. */
const FIRST_POSITION = 1000;

let log: Record<string, unknown>[] = [];
let current: Stream | null = null;

/** Отдаёт потоку первый блок и записи, подшитые после его позиции. */
function name(stream: Stream): void {
  if (!stream.alive || stream.named) return;
  stream.named = true;
  stream.options.onPosition(stream.start);
  for (const entry of log) {
    // Приложение могло закрыть поток прямо из обработчика: дальше ему не идёт ничего.
    if (!stream.alive) return;
    if ((entry.seq as number) > stream.start) stream.options.onMessage(JSON.stringify(entry));
  }
}

export const liveJournal = {
  /** Параметры потока, открытого сейчас. `null` — потока нет: не открывали или закрыт. */
  options: null as StreamOptions | null,
  /** Сколько раз приложение открывало поток за прогон. */
  connections: 0,
  closed: 0,
  /** Конец журнала: позиция, которую назовёт поток, открытый без `after`. */
  position: FIRST_POSITION,
  /**
   * Придержать первый блок: поток открыт, а позиции ещё не назвал — как ответ, чьи
   * заголовки пришли раньше тела. Отпускает `namePosition`.
   */
  holdPosition: false,

  /** Запись подшита: открытому потоку — кадром сразу, остальным — когда откроются. */
  send(entry: Record<string, unknown>): void {
    log.push(entry);
    this.position = Math.max(this.position, entry.seq as number);
    if (current?.alive === true && current.named) {
      current.options.onMessage(JSON.stringify(entry));
    }
  },

  /** Отпустить придержанный первый блок: открытый поток называет позицию, следующие — сразу. */
  namePosition(): void {
    this.holdPosition = false;
    if (current !== null) name(current);
  },

  reset(): void {
    log = [];
    // Страница прошлого теста снимается уже после этой уборки и закрывает свой поток
    // тогда же: в счёт следующего теста это закрытие попасть не должно.
    if (current !== null) current.alive = false;
    current = null;
    this.options = null;
    this.connections = 0;
    this.closed = 0;
    this.position = FIRST_POSITION;
    this.holdPosition = false;
  },
};

vi.mock('@/features/live-journal/model/stream-client', () => ({
  openJournalStream: (options: StreamOptions) => {
    const stream: Stream = {
      options,
      start: options.after ?? liveJournal.position,
      named: false,
      alive: true,
    };
    current = stream;
    liveJournal.options = options;
    liveJournal.connections += 1;

    /*
     * Настоящий поток отвечает открытием почти сразу, но не раньше, чем вызов вернёт
     * функцию закрытия: обработчики зовёт сеть. Повторяем и то и другое.
     *
     * В `act` обработчики не завёрнуты намеренно. `act` из Testing Library нельзя
     * подключить отсюда: на импорте она заводит свою уборку после теста, и та встала бы
     * раньше уборки оснастки — порядок изменился бы для всех тестов разом. Тест ждёт
     * открытия поиском (`findBy…`, `waitFor`), а они перерисовку дожидаются сами.
     */
    queueMicrotask(() => {
      if (!stream.alive) return;
      options.onOpen();
      if (!liveJournal.holdPosition) name(stream);
    });

    return () => {
      if (!stream.alive) return;
      stream.alive = false;
      liveJournal.closed += 1;
      if (current !== stream) return;
      current = null;
      liveJournal.options = null;
    };
  },
}));
