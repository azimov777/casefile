/**
 * Время для человека: относительная подпись в строке и точная в подсказке
 * (`CONVENTIONS.md`, «Интерфейс»).
 *
 * Обе функции чистые и принимают внешние величины параметром. Таких величин две,
 * и обе меняются сами по себе: «сейчас» — потому что время идёт, язык — потому что
 * человек его выбирает. Тест, зависящий от системных часов или от языка машины,
 * зеленел бы не всегда и не у всех.
 *
 * Язык берёт вызывающий: внутри компонента — хуком `useLanguage`, снаружи —
 * `currentLanguage()` (`@/shared/i18n`). Прочитать его прямо здесь значило бы вернуть
 * ту же зависимость от глобального состояния, только незаметную.
 */

import type { Language } from '../../i18n';
import { perLanguage } from './intl';

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Склонения и сокращения отдаёт `Intl`, а не наша таблица: «1 минуту», «2 минуты»
 * и «5 минут» — три разные формы, и своя таблица под них была бы копией стандарта
 * на каждый язык интерфейса.
 *
 * Форматтеры разобраны по языку и созданы один раз на язык, а не на вызов: в списке
 * из сотни строк подпись рисуется сотни раз за отрисовку (`intl.ts`, `perLanguage`).
 */
const relative = perLanguage(
  (language) => new Intl.RelativeTimeFormat(language, { numeric: 'always', style: 'short' }),
);

const exact = perLanguage(
  (language) => new Intl.DateTimeFormat(language, { dateStyle: 'long', timeStyle: 'medium' }),
);

/** Ступени: до какой границы считаем в этой единице и чему равна единица. */
const STEPS: { limit: number; unit: Intl.RelativeTimeFormatUnit; size: number }[] = [
  { limit: HOUR, unit: 'minute', size: MINUTE },
  { limit: DAY, unit: 'hour', size: HOUR },
  { limit: 30 * DAY, unit: 'day', size: DAY },
  { limit: 365 * DAY, unit: 'month', size: 30 * DAY },
  { limit: Number.POSITIVE_INFINITY, unit: 'year', size: 365 * DAY },
];

export interface RelativeTimeOptions {
  /** Язык, на котором `Intl` склоняет и сокращает единицы. */
  language: Language;
  /**
   * Подпись ступени ниже минуты. Она живёт в словаре (`ui.time.justNow`), а не здесь:
   * такой ступени `RelativeTimeFormat` не знает вовсе, и сказать её нечем, кроме слов.
   */
  justNow: string;
  /** «Сейчас». Параметром — чтобы тест не зависел от системных часов. */
  now?: number;
}

/**
 * «3 мин. назад» для метки времени из контракта. Пустая строка — если метки нет или
 * она не разбирается: выдумывать за бэкенд интерфейс не имеет права (`CONCEPT.md`, 6).
 */
export function relativeTime(
  value: string | null | undefined,
  { language, justNow, now = Date.now() }: RelativeTimeOptions,
): string {
  const at = parse(value);
  if (at === null) return '';

  const elapsed = now - at;
  // Разница меньше минуты в обе стороны — «только что»: «через 12 секунд» на часах,
  // разъехавшихся с сервером, читалось бы как ошибка интерфейса.
  if (Math.abs(elapsed) < MINUTE) return justNow;

  const step = STEPS.find((candidate) => Math.abs(elapsed) < candidate.limit) ?? STEPS.at(-1);
  if (step === undefined) return '';
  return relative(language).format(-Math.round(elapsed / step.size), step.unit);
}

/**
 * Точное время в часовом поясе браузера: оно уезжает в подсказку `title`.
 *
 * Пояс местный и от языка не зависит: человек с английским интерфейсом сидит в своём
 * поясе, а не в лондонском. Поэтому `timeZone` здесь не назван — `Intl` берёт
 * системный.
 */
export function exactTime(value: string | null | undefined, language: Language): string {
  const at = parse(value);
  return at === null ? '' : exact(language).format(at);
}

function parse(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : at;
}
