import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { leaveEnd, reachEnd, watched } from '@testing/intersection';
import { useBeyondEdge, useEndReach } from './end-reach';

/**
 * Область и сторож: два узла в живом документе. Настоящей раскладки в jsdom нет,
 * поэтому проверяется не геометрия, а то, что наблюдателю отдали в корень и когда
 * его сняли; саму прокрутку проверяет `e2e/board.spec.ts`.
 */
function nodes(overflow: string) {
  const area = document.createElement('section');
  area.style.overflowY = overflow;
  const end = document.createElement('div');
  area.append(end);
  document.body.append(area);
  return { area, end };
}

afterEach(() => {
  document.body.replaceChildren();
});

describe('useEndReach', () => {
  it('корнем берёт саму область, когда та прокручивается', () => {
    const { area, end } = nodes('auto');

    const { result } = renderHook(() =>
      useEndReach({ area: { current: area }, enabled: true, onReach: () => {} }),
    );
    // Ссылку React зовёт сам, когда узел встаёт в разметку; здесь её зовёт тест.
    act(() => result.current(end));

    expect(watched()).toHaveLength(1);
    expect(watched()[0]?.root).toBe(area);
  });

  it('корнем оставляет окно, когда область прокруткой не является', () => {
    // Ниже точки остановки столбец доски не прокручиваемая область вовсе: там едет
    // страница, и наблюдатель с корнем-областью не показал бы сторожа никогда (UI-68).
    const { area, end } = nodes('visible');

    const { result } = renderHook(() =>
      useEndReach({ area: { current: area }, enabled: true, onReach: () => {} }),
    );
    // Ссылку React зовёт сам, когда узел встаёт в разметку; здесь её зовёт тест.
    act(() => result.current(end));

    expect(watched()[0]?.root).toBeNull();
  });

  it('запрет снимает наблюдателя, а разрешение ставит его заново', async () => {
    const { area, end } = nodes('auto');
    const onReach = vi.fn();

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useEndReach({ area: { current: area }, enabled, onReach }),
      { initialProps: { enabled: true } },
    );
    // Ссылку React зовёт сам, когда узел встаёт в разметку; здесь её зовёт тест.
    act(() => result.current(end));
    await reachEnd();
    expect(onReach).toHaveBeenCalledTimes(1);

    // Пока идёт запрос — а «идёт запрос» и есть запрет, — сторож молчит: иначе он
    // звал бы снова в каждом кадре, пока ответ в пути.
    rerender({ enabled: false });
    expect(watched()).toEqual([]);
    await reachEnd();
    expect(onReach).toHaveBeenCalledTimes(1);

    /*
     * Разрешение ставит наблюдателя заново, и это не мелочь: наблюдатель говорит
     * о **смене** пересечения, а сторож после прихода страницы остаётся видимым.
     * Оставленный, он промолчал бы — и столбец, которому одной страницы не хватило
     * на экран, замер бы недочитанным.
     */
    rerender({ enabled: true });
    expect(watched()).toHaveLength(1);
    await reachEnd();
    expect(onReach).toHaveBeenCalledTimes(2);
  });
});

describe('useBeyondEdge', () => {
  it('конец за краем — за краем есть ещё; показался — знака нет', async () => {
    const { area, end } = nodes('auto');

    const { result } = renderHook(() => useBeyondEdge({ area: { current: area } }));
    // Ссылку React зовёт сам, когда узел встаёт в разметку; здесь её зовёт тест.
    act(() => result.current.end(end));

    // До первого слова наблюдателя знака нет: нарисованный раньше замера, он обещал бы
    // содержимое за краем там, где его нет.
    expect(result.current.beyond).toBe(false);

    await leaveEnd();
    expect(result.current.beyond).toBe(true);

    await reachEnd();
    expect(result.current.beyond).toBe(false);
  });

  it('область не прокручивается — нет ни наблюдателя, ни знака', async () => {
    /*
     * Ниже точки остановки столбец доски прокручиваемой областью не является, и корнем
     * стало бы окно: «сторож за нижним краем окна» это не «в столбце есть ещё карточки»,
     * а «страница длинная». Знак по такому корню обещал бы прокрутку, которой нет (UI-91).
     */
    const { area, end } = nodes('visible');

    const { result } = renderHook(() => useBeyondEdge({ area: { current: area } }));
    // Ссылку React зовёт сам, когда узел встаёт в разметку; здесь её зовёт тест.
    act(() => result.current.end(end));

    expect(watched()).toEqual([]);
    await leaveEnd();
    expect(result.current.beyond).toBe(false);
  });
});
