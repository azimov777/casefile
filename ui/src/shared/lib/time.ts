/**
 * Время для человека: относительная подпись в строке и точная в подсказке
 * (`CONVENTIONS.md`, «Интерфейс»).
 *
 * Обе функции чистые и принимают «сейчас» параметром: время — единственное, что
 * меняется само по себе, и тест, зависящий от системных часов, зеленел бы не всегда.
 */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Склонения и сокращения отдаёт `Intl`, а не наша таблица: «1 минуту», «2 минуты»
 * и «5 минут» — три разные формы, и своя таблица под них была бы копией стандарта.
 */
const relative = new Intl.RelativeTimeFormat('ru-RU', { numeric: 'always', style: 'short' });

const exact = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long', timeStyle: 'medium' });

/** Ступени: до какой границы считаем в этой единице и чему равна единица. */
const STEPS: { limit: number; unit: Intl.RelativeTimeFormatUnit; size: number }[] = [
  { limit: HOUR, unit: 'minute', size: MINUTE },
  { limit: DAY, unit: 'hour', size: HOUR },
  { limit: 30 * DAY, unit: 'day', size: DAY },
  { limit: 365 * DAY, unit: 'month', size: 30 * DAY },
  { limit: Number.POSITIVE_INFINITY, unit: 'year', size: 365 * DAY },
];

/**
 * «3 мин. назад» для метки времени из контракта. `null` — если её нет или она
 * не разбирается: выдумывать за бэкенд интерфейс не имеет права (`CONCEPT.md`, 6).
 */
export function relativeTime(value: string | null | undefined, now: number = Date.now()): string {
  const at = parse(value);
  if (at === null) return '';

  const elapsed = now - at;
  // Разница меньше минуты в обе стороны — «только что»: «через 12 секунд» на часах,
  // разъехавшихся с сервером, читалось бы как ошибка интерфейса.
  if (Math.abs(elapsed) < MINUTE) return 'только что';

  const step = STEPS.find((candidate) => Math.abs(elapsed) < candidate.limit) ?? STEPS.at(-1);
  if (step === undefined) return '';
  return relative.format(-Math.round(elapsed / step.size), step.unit);
}

/** Точное время в часовом поясе браузера: оно уезжает в подсказку `title`. */
export function exactTime(value: string | null | undefined): string {
  const at = parse(value);
  return at === null ? '' : exact.format(at);
}

function parse(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : at;
}
