import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  COALESCE_WINDOW_MS,
  holdForRequest,
  holdForWindow,
  holdWhileHidden,
  releaseHidden,
  releaseRequested,
  releaseWindowed,
  requestedTaskCount,
  resetDeferred,
  subscribeWindowClosed,
} from './deferred';

const BOARD = ['tasks', 'board'] as const;
const TABLE = ['tasks', 'table'] as const;

/**
 * Подписки живут в модуле и пережили бы тест: без снятия следующий тест будил бы
 * заодно и чужого слушателя, а падал бы третий — на счётчике, которого не набирал.
 */
const stopped: (() => void)[] = [];

function watchWindow(): ReturnType<typeof vi.fn> {
  const closed = vi.fn();
  stopped.push(subscribeWindowClosed(closed));
  return closed;
}

afterEach(() => {
  for (const stop of stopped.splice(0)) stop();
  resetDeferred();
  vi.useRealTimers();
});

describe('склейка кадров окном', () => {
  it('пачка кадров внутри окна закрывает его один раз и даёт один ключ', () => {
    vi.useFakeTimers();
    const closed = watchWindow();

    // Десять записей за секунду — обычный заход агента по задаче. Кадры идут вразбивку,
    // а не разом: окно обязано пережить паузы внутри пачки, иначе оно склеивало бы
    // только те кадры, что пришли в один тик.
    for (let frame = 0; frame < 10; frame += 1) {
      holdForWindow([BOARD]);
      vi.advanceTimersByTime(COALESCE_WINDOW_MS / 20);
    }
    expect(closed).not.toHaveBeenCalled();

    vi.advanceTimersByTime(COALESCE_WINDOW_MS);

    expect(closed).toHaveBeenCalledTimes(1);
    // Один ключ, а не десять одинаковых: инвалидация по нему десять раз подряд —
    // это десять перечитываний, то есть ровно то, от чего копили.
    expect(releaseWindowed()).toEqual([BOARD]);
  });

  it('кадр после закрытия окна заводит новое, а не попадает в закрытое', () => {
    vi.useFakeTimers();
    const closed = watchWindow();

    holdForWindow([BOARD]);
    vi.advanceTimersByTime(COALESCE_WINDOW_MS);
    expect(releaseWindowed()).toEqual([BOARD]);

    holdForWindow([BOARD]);
    expect(closed).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(COALESCE_WINDOW_MS);
    expect(closed).toHaveBeenCalledTimes(2);
    expect(releaseWindowed()).toEqual([BOARD]);
  });

  it('окно закрывается впустую, если накопленное забрали раньше', () => {
    vi.useFakeTimers();
    const closed = watchWindow();

    holdForWindow([BOARD]);
    // Так уходит вкладка в фон: накопленное переезжает в другой срок, окно остаётся.
    holdWhileHidden(releaseWindowed());

    vi.advanceTimersByTime(COALESCE_WINDOW_MS);
    expect(closed).toHaveBeenCalledTimes(1);
    expect(releaseWindowed()).toEqual([]);
    expect(releaseHidden()).toEqual([BOARD]);
  });
});

describe('три срока не смешиваются', () => {
  it('отложенное до просьбы окном не забирается, а склеиваемое — полосой', () => {
    vi.useFakeTimers();

    holdForRequest([TABLE], 'DEMO-1');
    holdForWindow([BOARD]);

    // Полоса считает свои задачи и о доске не знает ничего.
    expect(requestedTaskCount()).toBe(1);
    vi.advanceTimersByTime(COALESCE_WINDOW_MS);
    expect(releaseWindowed()).toEqual([BOARD]);
    expect(requestedTaskCount()).toBe(1);

    // А просьба человека забирает только табличное.
    expect(releaseRequested()).toEqual([TABLE]);
    expect(requestedTaskCount()).toBe(0);
  });

  it('уборка гасит заведённое окно: чужой кадр не разбудит следующий тест', () => {
    vi.useFakeTimers();
    const closed = watchWindow();

    holdForWindow([BOARD]);
    resetDeferred();

    vi.advanceTimersByTime(COALESCE_WINDOW_MS * 2);
    expect(closed).not.toHaveBeenCalled();
  });
});
