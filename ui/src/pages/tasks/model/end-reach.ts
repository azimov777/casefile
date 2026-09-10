import { useEffect, useRef, useState, type RefObject } from 'react';

/**
 * Докрутили до конца — позвать.
 *
 * Сторож в конце содержимого и наблюдатель пересечения над ним: пока сторож за краем
 * видимой части, ничего не происходит; показался — зовётся `onReach`. Ни таймеров,
 * ни обработчика прокрутки: обработчик считал бы геометрию на каждом кадре прокрутки,
 * а наблюдатель молчит, пока пересечение не изменилось.
 */

/**
 * Насколько раньше края спрашивать следующее: четверть высоты области.
 *
 * Не ноль — иначе человек упирается в дно и ждёт; но и не «экран вперёд»: цель задачи
 * в том, чтобы читать меньше, а не в том, чтобы читать то же самое по другому поводу.
 * Доля, а не пиксели: область бывает и столбцом доски, и окном телефона.
 */
const READ_AHEAD = '0px 0px 25% 0px';

interface EndReach {
  /**
   * Область, внутри которой едет содержимое, — если она прокручивается сама.
   * Наблюдателю она отдаётся корнем; когда область прокруткой не является,
   * корнем остаётся окно (см. `scrollingArea`).
   */
  area: RefObject<HTMLElement | null>;
  /**
   * Стеречь ли конец сейчас. Ложь снимает наблюдателя вовсе — это и запрет
   * («читать больше нечего», «прошлый ответ не дошёл»), и способ перевести
   * сторожа на новое содержимое: наблюдатель, поставленный заново, сразу говорит,
   * виден ли сторож, а оставленный молчит, пока пересечение не изменится.
   */
  enabled: boolean;
  onReach: () => void;
}

/**
 * Ставит сторожа в конец содержимого. Возвращает ссылку, которую вешают на пустой узел
 * после последнего элемента.
 */
export function useEndReach({
  area,
  enabled,
  onReach,
}: EndReach): (node: HTMLElement | null) => void {
  // Узел приходит состоянием, а не ссылкой: наблюдателя ставит эффект, а он обязан
  // проснуться, когда сторож появился в разметке, — на правку `ref.current` React
  // ничего не перерисовывает.
  const [end, setEnd] = useState<HTMLElement | null>(null);

  // Обработчик живёт в ссылке: он собирается заново на каждой отрисовке, и включи его
  // в зависимости эффекта — наблюдатель пересоздавался бы вместе с ним.
  const reach = useRef(onReach);
  useEffect(() => {
    reach.current = onReach;
  });

  useEffect(() => {
    if (!enabled || end === null) return;
    // В jsdom наблюдателя пересечения нет вовсе: без этого падает среда, а не поведение.
    if (typeof IntersectionObserver === 'undefined') return;

    let observer: IntersectionObserver | null = null;

    /*
     * Корень выбирается заново на каждом изменении размера окна: прокручиваемой
     * областью столбец доски становится по ширине окна (`fold`), а ниже неё
     * прокручивается страница, и корнем обязано быть окно (UI-68, UI-70#7).
     */
    const watch = () => {
      observer?.disconnect();
      observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) reach.current();
        },
        { root: scrollingArea(area.current), rootMargin: READ_AHEAD },
      );
      observer.observe(end);
    };

    watch();
    window.addEventListener('resize', watch);
    return () => {
      window.removeEventListener('resize', watch);
      observer?.disconnect();
    };
  }, [area, enabled, end]);

  return setEnd;
}

/**
 * Прокручивается ли область сама — и потому годится ли она в корни наблюдателя.
 *
 * Спрашивается у вычисленного стиля, а не у точки остановки числом: одно и то же
 * правило (`fold:overflow-y-auto`) написано в разметке, и второе его имя в скрипте
 * разошлось бы с ним молча. Не прокручивается — корнем становится окно (`null`).
 */
function scrollingArea(node: HTMLElement | null): HTMLElement | null {
  if (node === null) return null;

  const overflow = getComputedStyle(node).overflowY;
  return overflow === 'auto' || overflow === 'scroll' ? node : null;
}
