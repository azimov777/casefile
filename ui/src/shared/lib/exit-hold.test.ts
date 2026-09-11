import { act, render, renderHook, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exitDurationMs, useExitHold, useExitHoldList, type ExitHold } from './exit-hold';

/**
 * Стилей в jsdom не загружено, поэтому длительность выхода задаётся тем же способом,
 * каким её задаёт тема, — свойством на корне документа. Так проверяется и само чтение
 * токена: хук обязан взять её оттуда, а не из числа внутри себя.
 */
function setMotion(value: string | null) {
  if (value === null) document.documentElement.style.removeProperty('--motion-fast');
  else document.documentElement.style.setProperty('--motion-fast', value);
}

/** Признаки задержки без ссылки: ссылка — функция, и сравнивать её не с чем. */
function flags({ held, leaving, entering }: ExitHold) {
  return { held, leaving, entering };
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

/*
 * Здесь узла нет вовсе: `renderHook` ссылку никуда не ставит, и задержка держит узел
 * сроком токена от коммита — так же, как держала до UI-111 и как держит в jsdom, где
 * движений браузер не отдаёт. Конец выхода по движениям узла — в describe ниже.
 */
describe('useExitHold', () => {
  it('держит узел до конца выхода и снимает его после', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });
    expect(flags(result.current)).toEqual({ held: true, leaving: false, entering: false });

    rerender({ open: false });
    // Тот самый кадр, ради которого всё и заведено: узел ещё в разметке и уже уходит.
    expect(flags(result.current)).toEqual({ held: true, leaving: true, entering: false });

    act(() => vi.advanceTimersByTime(119));
    expect(result.current.held).toBe(true);

    act(() => vi.advanceTimersByTime(1));
    expect(flags(result.current)).toEqual({ held: false, leaving: false, entering: false });
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
    expect(flags(result.current)).toEqual({ held: true, leaving: false, entering: true });
  });

  it('вернувшийся до конца выхода узел не исчезает по таймеру прошлого закрытия', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });

    rerender({ open: false });
    act(() => vi.advanceTimersByTime(60));
    rerender({ open: true });
    expect(flags(result.current)).toEqual({ held: true, leaving: false, entering: false });

    act(() => vi.advanceTimersByTime(200));
    expect(flags(result.current)).toEqual({ held: true, leaving: false, entering: false });
  });

  it('закрытый с самого начала узел не рисуется вовсе', () => {
    const { result } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: false },
    });

    expect(flags(result.current)).toEqual({ held: false, leaving: false, entering: false });
  });

  it('без длительности узел уходит сразу: держать нечего', () => {
    setMotion(null);
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });

    rerender({ open: false });
    expect(result.current.held).toBe(false);
  });

  it('ссылка у узла одна на всю его жизнь, пока он показан и пока уходит', () => {
    const { result, rerender } = renderHook(({ open }) => useExitHold(open), {
      initialProps: { open: true },
    });
    const shown = result.current.ref;

    rerender({ open: true });
    expect(result.current.ref).toBe(shown);
    rerender({ open: false });
    // Новая ссылка на уходящем заставила бы React снять старую и поставить новую —
    // задержка на мгновение потеряла бы узел, чьи движения ждёт.
    expect(result.current.ref).toBe(shown);
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

/**
 * Движение узла, каким его отдаёт `getAnimations`: идёт, пока тест не скажет, что оно
 * кончилось (`end`) или его сняли (`cancel`).
 */
interface Motion {
  playState: AnimationPlayState;
  effect: { getComputedTiming: () => { endTime: number } };
  finished: Promise<void>;
  end: () => void;
  cancel: () => void;
}

function motion(endTime = 120): Motion {
  let resolve = () => {};
  let reject = (_reason: unknown) => {};
  const finished = new Promise<void>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  // Снятое движение отклоняет `finished`; обработчик задержки стоит не сразу.
  finished.catch(() => undefined);

  const made: Motion = {
    playState: 'running',
    effect: { getComputedTiming: () => ({ endTime }) },
    finished,
    end: () => {
      made.playState = 'finished';
      resolve();
    },
    cancel: () => {
      made.playState = 'idle';
      reject(new DOMException('движение снято', 'AbortError'));
    },
  };
  return made;
}

/**
 * Конец выхода — конец движений самого узла (UI-111). Узел здесь настоящий: ссылка
 * задержки стоит на нём, а движения поддерева ему отдаёт подменённый `getAnimations`
 * (в jsdom его нет), по `data-key` узла. Кадры идут подменёнными часами — каждые 16 мс.
 */
describe('конец выхода по движениям узла', () => {
  let motions = new Map<string, Motion[]>();

  beforeEach(() => {
    motions = new Map();
    Object.defineProperty(Element.prototype, 'getAnimations', {
      configurable: true,
      value(this: Element) {
        return motions.get(this.getAttribute('data-key') ?? '') ?? [];
      },
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(Element.prototype, 'getAnimations');
    vi.unstubAllGlobals();
  });

  /** Один узел под `useExitHold`, со ссылкой на месте. */
  function One({ open }: { open: boolean }) {
    const hold = useExitHold(open);
    return hold.held
      ? createElement('div', {
          ref: hold.ref,
          'data-key': 'one',
          'data-testid': 'one',
          'data-leaving': String(hold.leaving),
        })
      : null;
  }

  /** Узлы списка под `useExitHoldList`, у каждого своя ссылка. */
  function Many({ shown }: { shown: string[] }) {
    const held = useExitHoldList(shown, (item) => item);
    return createElement(
      'div',
      null,
      held.map((item) =>
        createElement('div', {
          key: item.key,
          ref: item.ref,
          'data-key': item.key,
          'data-testid': item.key,
        }),
      ),
    );
  }

  it('узел держится, пока идут его движения, — и дольше токена, — а снимается сразу после', async () => {
    const place = motion();
    motions.set('one', [place]);
    const { rerender } = render(createElement(One, { open: true }));

    rerender(createElement(One, { open: false }));
    expect(screen.getByTestId('one')).toHaveAttribute('data-leaving', 'true');

    // Кадры были, срок токена прошёл, а движение ещё идёт: переход начался позже
    // коммита, и узел, снятый по сроку, оборвал бы его.
    act(() => vi.advanceTimersByTime(200));
    expect(screen.queryByTestId('one')).not.toBeNull();

    await act(async () => place.end());
    expect(screen.queryByTestId('one')).toBeNull();
  });

  it('движение, пришедшее на смену посреди выхода, тоже дожидаются', async () => {
    const first = motion();
    motions.set('one', [first]);
    const { rerender } = render(createElement(One, { open: true }));
    rerender(createElement(One, { open: false }));
    act(() => vi.advanceTimersByTime(50));

    const second = motion();
    await act(async () => {
      motions.set('one', [first, second]);
      first.cancel();
    });
    expect(screen.queryByTestId('one')).not.toBeNull();

    await act(async () => second.end());
    expect(screen.queryByTestId('one')).toBeNull();
  });

  it('при погашенном движении узел уходит сразу, до первого кадра', () => {
    // `prefers-reduced-motion`: движения есть, но короче промежутка до кадра.
    setMotion('0.01ms');
    motions.set('one', [motion(0.01)]);
    const { rerender } = render(createElement(One, { open: true }));

    rerender(createElement(One, { open: false }));
    // Первый кадр подменённых часов — на шестнадцатой миллисекунде.
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByTestId('one')).toBeNull();
  });

  it('кадров нет вовсе — вкладка в фоне — и узел уходит по сроку токена', () => {
    vi.stubGlobal('requestAnimationFrame', () => 0);
    vi.stubGlobal('cancelAnimationFrame', () => {});
    motions.set('one', [motion()]);
    const { rerender } = render(createElement(One, { open: true }));

    rerender(createElement(One, { open: false }));
    act(() => vi.advanceTimersByTime(119));
    expect(screen.queryByTestId('one')).not.toBeNull();

    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByTestId('one')).toBeNull();
  });

  it('вернувшийся до конца выхода узел не снимается, когда кончилось старое движение', async () => {
    const leaving = motion();
    motions.set('one', [leaving]);
    const { rerender } = render(createElement(One, { open: true }));

    rerender(createElement(One, { open: false }));
    act(() => vi.advanceTimersByTime(50));
    rerender(createElement(One, { open: true }));
    // Открытый снова узел перебивает переход выхода, и тот отклоняет `finished`.
    await act(async () => leaving.cancel());
    act(() => vi.advanceTimersByTime(300));

    expect(screen.getByTestId('one')).toHaveAttribute('data-leaving', 'false');
  });

  it('движений нет — ждать нечего, и бесконечное движение выхода не держит', () => {
    motions.set('one', [motion(Number.POSITIVE_INFINITY)]);
    const { rerender } = render(createElement(One, { open: true }));

    rerender(createElement(One, { open: false }));
    expect(screen.queryByTestId('one')).toBeNull();
  });

  it('в списке каждый уходящий ждёт своих движений', async () => {
    const a = motion();
    const b = motion();
    motions.set('a', [a]);
    motions.set('b', [b]);
    const { rerender } = render(createElement(Many, { shown: ['a', 'b'] }));

    rerender(createElement(Many, { shown: [] }));
    act(() => vi.advanceTimersByTime(200));

    await act(async () => a.end());
    expect(screen.queryByTestId('a')).toBeNull();
    expect(screen.queryByTestId('b')).not.toBeNull();

    await act(async () => b.end());
    expect(screen.queryByTestId('b')).toBeNull();
  });
});
