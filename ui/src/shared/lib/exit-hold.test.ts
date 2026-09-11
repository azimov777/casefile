import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exitDurationMs, useExitHold, useExitHoldList } from './exit-hold';

/**
 * Стилей в jsdom не загружено, поэтому длительность выхода задаётся тем же способом,
 * каким её задаёт тема, — свойством на корне документа. Так проверяется и само чтение
 * токена: хук обязан взять её оттуда, а не из числа внутри себя.
 */
function setMotion(value: string | null) {
  if (value === null) document.documentElement.style.removeProperty('--motion-fast');
  else document.documentElement.style.setProperty('--motion-fast', value);
}

beforeEach(() => {
  vi.useFakeTimers();
  setMotion('120ms');
});

afterEach(() => {
  vi.useRealTimers();
  setMotion(null);
});

describe('exitDurationMs', () => {
  it('читает токен движения и понимает обе единицы', () => {
    setMotion('120ms');
    expect(exitDurationMs()).toBe(120);

    // Браузер печатает токен как написано, а секунды, принятые за миллисекунды,
    // дали бы задержку в тысячу раз короче движения.
    setMotion('0.12s');
    expect(exitDurationMs()).toBe(120);
  });

  it('гаснет вместе с движением: `prefers-reduced-motion` переопределяет сам токен', () => {
    // Ровно то значение, которым `shared/styles/index.css` гасит движение.
    setMotion('0.01ms');
    expect(exitDurationMs()).toBe(0.01);
  });

  it('без токена держать нечего', () => {
    setMotion(null);
    expect(exitDurationMs()).toBe(0);
  });
});

describe('useExitHold', () => {
  it('держит узел до конца выхода и снимает его после', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });
    expect(result.current).toEqual({ held: true, leaving: false, entering: false });

    rerender({ open: false });
    // Тот самый кадр, ради которого всё и заведено: узел ещё в разметке и уже уходит.
    expect(result.current).toEqual({ held: true, leaving: true, entering: false });

    act(() => vi.advanceTimersByTime(119));
    expect(result.current.held).toBe(true);

    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toEqual({ held: false, leaving: false, entering: false });
  });

  it('стоявший с самого начала не въезжает, а открытый нажатием — въезжает', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });
    // Страницу просто открыли. Никакого события не было, и приезжать неоткуда:
    // движение отвечает на событие (`CONCEPT.md`, 6).
    expect(result.current.entering).toBe(false);

    rerender({ open: false });
    act(() => vi.advanceTimersByTime(120));
    rerender({ open: true });
    // А это уже нажатие: узел появился заново и обязан приехать.
    expect(result.current).toEqual({ held: true, leaving: false, entering: true });
  });

  it('вернувшийся до конца выхода узел не исчезает по таймеру прошлого закрытия', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });

    rerender({ open: false });
    act(() => vi.advanceTimersByTime(60));
    rerender({ open: true });
    expect(result.current).toEqual({ held: true, leaving: false, entering: false });

    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toEqual({ held: true, leaving: false, entering: false });
  });

  it('закрытый с самого начала узел не рисуется вовсе', () => {
    const { result } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: false },
    });

    expect(result.current).toEqual({ held: false, leaving: false, entering: false });
  });

  it('без длительности узел уходит сразу: держать нечего', () => {
    setMotion(null);
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });

    rerender({ open: false });
    expect(result.current.held).toBe(false);
  });
});

describe('useExitHoldList', () => {
  const key = (item: string) => item;

  it('уходящий остаётся на своём месте, а соседи не трогаются', () => {
    const { result, rerender } = renderHook(({ shown }) => useExitHoldList(shown, key), {
      initialProps: { shown: ['a', 'b', 'c'] },
    });
    expect(result.current.map((held) => held.key)).toEqual(['a', 'b', 'c']);

    rerender({ shown: ['a', 'c'] });
    // Стопка, где закрываемая карточка перепрыгнула вниз, движением ничего не объясняет.
    expect(result.current.map((held) => [held.key, held.leaving])).toEqual([
      ['a', false],
      ['b', true],
      ['c', false],
    ]);

    act(() => vi.advanceTimersByTime(120));
    expect(result.current.map((held) => held.key)).toEqual(['a', 'c']);
  });

  it('новый элемент появляется в том же кадре, а не через один, и въезжает один он', () => {
    const { result, rerender } = renderHook(({ shown }) => useExitHoldList(shown, key), {
      initialProps: { shown: ['a'] },
    });

    rerender({ shown: ['a', 'b'] });
    expect(result.current.map((held) => held.key)).toEqual(['a', 'b']);
    expect(result.current.every((held) => !held.leaving)).toBe(true);
    // Приехал только пришедший: сосед, стоявший с самого начала, никуда не двигался.
    expect(result.current.map((held) => held.entering)).toEqual([false, true]);
  });

  it('содержимое уходящего берётся последним виденным', () => {
    const items = { a: { id: 'a', text: 'первый' }, b: { id: 'b', text: 'второй' } };
    const { result, rerender } = renderHook(
      ({ shown }) => useExitHoldList(shown, (item: { id: string }) => item.id),
      { initialProps: { shown: [items.a, items.b] } },
    );

    rerender({ shown: [items.a] });
    expect(result.current.map((held) => held.item.text)).toEqual(['первый', 'второй']);
  });

  it('вернувшийся элемент снимает свой таймер, а сосед уходит своим чередом', () => {
    const { result, rerender } = renderHook(({ shown }) => useExitHoldList(shown, key), {
      initialProps: { shown: ['a', 'b'] },
    });

    rerender({ shown: [] });
    act(() => vi.advanceTimersByTime(60));
    rerender({ shown: ['a'] });
    expect(result.current.map((held) => [held.key, held.leaving])).toEqual([
      ['a', false],
      ['b', true],
    ]);

    act(() => vi.advanceTimersByTime(120));
    expect(result.current.map((held) => held.key)).toEqual(['a']);
  });
});
