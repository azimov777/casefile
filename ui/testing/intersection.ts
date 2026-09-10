import { act } from '@testing-library/react';

/**
 * Наблюдатель пересечения, которым можно управлять из теста.
 *
 * В jsdom своего нет вовсе, а раскладки нет тем более: настоящий наблюдатель здесь
 * молчал бы всегда, потому что ничего не пересекается ни с чем. Заглушка не изображает
 * геометрию — она даёт тесту сказать «сторож показался» и проверить, что из этого
 * вышло. Прокрутку в живом браузере проверяет `e2e/board.spec.ts`.
 */

interface Watch {
  root: Element | Document | null;
  rootMargin: string;
  targets: Set<Element>;
  fire: () => void;
}

const watches = new Set<Watch>();

class ControlledObserver implements IntersectionObserver {
  readonly root: Element | Document | null;
  readonly rootMargin: string;
  readonly thresholds: readonly number[] = [0];
  private readonly watch: Watch;

  constructor(callback: IntersectionObserverCallback, options: IntersectionObserverInit = {}) {
    this.root = options.root ?? null;
    this.rootMargin = options.rootMargin ?? '0px';
    this.watch = {
      root: this.root,
      rootMargin: this.rootMargin,
      targets: new Set<Element>(),
      fire: () => {
        const entries = [...this.watch.targets].map(
          (target) => ({ target, isIntersecting: true }) as IntersectionObserverEntry,
        );
        if (entries.length > 0) callback(entries, this);
      },
    };
  }

  observe(target: Element): void {
    this.watch.targets.add(target);
    watches.add(this.watch);
  }

  unobserve(target: Element): void {
    this.watch.targets.delete(target);
  }

  disconnect(): void {
    this.watch.targets.clear();
    watches.delete(this.watch);
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

/**
 * Ставит управляемого наблюдателя на весь прогон. Зовётся из общей обвязки.
 *
 * Имя без `use`: правило хуков считает хуком любое `useЧто-то` и не пускает такой
 * вызов на верхний уровень модуля, а это не хук, а подмена глобального объекта.
 */
export function installIntersection(): void {
  globalThis.IntersectionObserver = ControlledObserver as unknown as typeof IntersectionObserver;
}

/** Забыть наблюдателей прошлого теста: узлы их страниц уже сняты. */
export function resetIntersection(): void {
  watches.clear();
}

/** Что стерегут прямо сейчас: корень и запас каждого живого наблюдателя. */
export function watched(): { root: Element | Document | null; rootMargin: string }[] {
  return [...watches].map(({ root, rootMargin }) => ({ root, rootMargin }));
}

/**
 * «Сторож показался» — всем живым наблюдателям сразу.
 *
 * Внутри `act`: из обработчика идёт запрос и перерисовка, и без него React жалуется
 * на обновление состояния вне действия, а тест видит экран до ответа.
 */
export async function reachEnd(): Promise<void> {
  await act(async () => {
    for (const watch of [...watches]) watch.fire();
  });
}
