import { useEffect, useState, type ReactNode } from 'react';
import { cn, exitDurationMs } from '@/shared/lib';

interface RevealProps {
  /**
   * Узел уже убран из показа и доживает выход. Считает это `useExitHold`: он же
   * держит узел до конца движения и говорит, рисовать ли его вообще.
   */
  leaving: boolean;
  /**
   * Узел появился в ответ на событие, а не стоял с самого начала. Ложь — входа нет
   * вовсе: движение отвечает на событие (`CONCEPT.md`, 6), а открытая страница
   * с уже раскрытым местом — не событие. Считает это тот же `useExitHold`.
   */
  entering: boolean;
  children: ReactNode;
}

/**
 * Раскрытие в потоке вёрстки: содержимое приезжает вместе со своим местом.
 *
 * Двигаются строки сетки (`grid-template-rows: 0fr → 1fr`), а не `height` и не
 * `transform` (решение UI-59#12). `transform` не двигает **место**: соседнее
 * содержимое прыгнуло бы в первом же кадре, то есть дефект остался бы, а движение
 * объясняло бы не то. `height: auto` не интерполируется вовсе.
 *
 * Обёрток две, и обе обязательны: строки сетки живут на внешней, обрезание
 * содержимого — на внутренней. Без `overflow: hidden` строка `0fr` не станет нулём —
 * у элемента сетки минимальный размер по содержимому, и обнуляет его как раз обрезание.
 *
 * Вход берётся `@starting-style` (`starting:`), а не первым кадром из скрипта: браузер
 * сам знает начальное значение только что вставленного узла, а «поставить 0fr и на
 * следующем кадре 1fr» из React — это лишняя отрисовка и гонка с раскладкой. Начинать
 * есть что не всегда: узлу, стоявшему с самого начала, `starting:` не выдают вовсе,
 * иначе раскрытия въезжали бы на каждой загрузке страницы, ничему не отвечая.
 *
 * Прозрачность здесь не украшение: она прячет край обрезания, у которого содержимое
 * рубится на полустроке. В покое её нет — по концу движения единица (`UI-59#4`).
 *
 * Родитель обязан снимать узел сам, когда `useExitHold` перестал его держать: узнать
 * это отсюда нельзя, а в описи дела раскрытие живёт целой строкой таблицы, и лишним
 * узлом в разметке она быть не вправе.
 */
export function Reveal({ leaving, entering, children }: RevealProps) {
  /*
   * Обрезание нужно ровно пока едет место. В покое его нет намеренно: содержимое
   * бывает шире своего места по замыслу — объяснение отказа разбора запроса наложено
   * на страницу и выходит за нижний край формы (`task-filters.tsx`), — и постоянное
   * `overflow: hidden` резало бы его вместе с движением.
   */
  const [settled, setSettled] = useState(!entering);
  const clipped = leaving || !settled;

  useEffect(() => {
    // Выход снова обрезает: место едет в ноль, и содержимое обязано уезжать вместе с ним.
    if (leaving) {
      setSettled(false);
      return;
    }
    if (settled) return;

    /*
     * Страховка на случай, если конца перехода не будет вовсе: `@starting-style`
     * знают Chrome 117, Safari 17.5 и Firefox 129, а в браузере старше вход просто
     * не поедет — и обрезание, снятое только по `transitionend`, осталось бы навсегда.
     * Срок вдвое длиннее движения, чтобы в живом браузере успевал сработать переход,
     * а не эта страховка: снятое раньше времени обрезание показало бы содержимое
     * за краем места на последних кадрах.
     */
    const timer = setTimeout(() => setSettled(true), exitDurationMs() * 2);
    return () => clearTimeout(timer);
  }, [leaving, settled]);

  return (
    <div
      // Опора для замеров: длительность и кривую снимают с этого узла, а слепок
      // вычисленных стилей минует обе обёртки, сличая то, что внутри них.
      data-reveal="place"
      className={cn(
        'grid transition-[grid-template-rows] duration-(--motion-fast)',
        leaving ? 'grid-rows-[0fr] ease-exit' : 'grid-rows-[1fr] ease-fast',
        !leaving && entering && 'starting:grid-rows-[0fr]',
      )}
      onTransitionEnd={(event) => {
        // Только своё движение: прозрачность внутренней обёртки всплывает сюда же.
        if (event.target !== event.currentTarget) return;
        if (event.propertyName !== 'grid-template-rows') return;
        if (!leaving) setSettled(true);
      }}
    >
      <div
        data-reveal="clip"
        className={cn(
          'transition-opacity duration-(--motion-fast)',
          clipped && 'overflow-hidden',
          leaving ? 'opacity-0 ease-exit' : 'opacity-100 ease-fast',
          !leaving && entering && 'starting:opacity-0',
        )}
      >
        {children}
      </div>
    </div>
  );
}
