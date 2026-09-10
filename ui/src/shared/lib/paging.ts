/**
 * Арифметика страниц: из общего числа строк и размера страницы — сколько страниц,
 * из номера текущей — какие номера показать.
 *
 * Считается только из того, что отдал контракт: общее число выдачи (`meta.total`)
 * и размер страницы, который клиент сам же и просил. Выводить число страниц из
 * `has_more` или из числа уже прочитанных строк нельзя — это догадка, а номер
 * страницы, оказавшийся догадкой, врёт человеку точным числом.
 */

/** Пропуск в ряду номеров: между соседними кнопками спрятано больше одной страницы. */
export const PAGE_GAP = 'gap';

export type PageSlot = number | typeof PAGE_GAP;

/**
 * Сколько страниц у выдачи в `total` строк по `size` строк на странице.
 *
 * Пустая выдача даёт ноль страниц, а не одну: «страница 1 из 1» над пустой таблицей
 * обещала бы строки, которых нет.
 */
export function pageCount(total: number, size: number): number {
  if (total <= 0 || size <= 0) return 0;
  return Math.ceil(total / size);
}

/** Сколько номеров стоит в ряду рядом с текущим, не считая первого и последнего. */
const WINDOW = 3;

/**
 * Номера страниц для ряда кнопок: `1 2 [3] 4 … 7`.
 *
 * Первая и последняя страницы стоят всегда — по ним видно, где границы выдачи;
 * рядом с текущей — окно из трёх соседних, которое у краёв сдвигается внутрь, а не
 * ужимается: ряд не должен менять длину от того, куда человек ушёл.
 *
 * Пропуск ставится только там, где за ним прячется больше одной страницы. Многоточие
 * вместо единственного номера крало бы у человека переход и не экономило бы ничего:
 * места они занимают поровну.
 */
export function pageWindow(current: number, count: number): PageSlot[] {
  if (count <= 0) return [];

  const page = Math.min(Math.max(current, 1), count);
  const start = Math.min(Math.max(page - 1, 1), Math.max(count - WINDOW + 1, 1));
  const near = new Set<number>();
  for (let number = start; number < start + WINDOW && number <= count; number += 1) {
    near.add(number);
  }
  near.add(1);
  near.add(count);

  const numbers = [...near].sort((left, right) => left - right);
  const slots: PageSlot[] = [];
  let previous = 0;

  for (const number of numbers) {
    const skipped = number - previous - 1;
    if (previous !== 0 && skipped === 1) slots.push(number - 1);
    else if (skipped > 1) slots.push(PAGE_GAP);
    slots.push(number);
    previous = number;
  }

  return slots;
}
