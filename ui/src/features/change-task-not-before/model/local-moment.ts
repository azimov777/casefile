/**
 * Момент между полем `datetime-local` и контрактом (TRK-593, TRK#47, п. 1).
 *
 * Поле даёт «2026-10-12T09:00» — стенное время устройства без пояса. Бэкенд строку без
 * смещения отклоняет (`task_fields_invalid`): он не знает, по каким часам она написана.
 * Поэтому в запрос уходит то же стенное время со смещением пояса браузера на этот момент,
 * а обратно момент из контракта раскладывается в стенное время того же пояса.
 */

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

const two = (value: number) => String(value).padStart(2, '0');

/**
 * «2026-10-12T09:00» → «2026-10-12T09:00:00+02:00» в поясе браузера. `null` — поле
 * пусто или не разбирается: отправлять нечего.
 */
export function fromLocalInput(value: string): string | null {
  const parts = LOCAL.exec(value);
  if (parts === null) return null;
  const [year, month, day, hour, minute] = parts.slice(1).map(Number) as [
    number,
    number,
    number,
    number,
    number,
  ];
  const at = new Date(year, month - 1, day, hour, minute);
  if (Number.isNaN(at.getTime())) return null;

  // Смещение берётся у самого момента, а не у «сейчас»: в день перевода часов оно другое.
  const offset = -at.getTimezoneOffset();
  const sign = offset < 0 ? '-' : '+';
  const abs = Math.abs(offset);
  return `${parts[1]}-${parts[2]}-${parts[3]}T${parts[4]}:${parts[5]}:00${sign}${two(Math.floor(abs / 60))}:${two(abs % 60)}`;
}

/** Момент из контракта → стенное время пояса браузера для поля; пустая строка — не разобрался. */
export function toLocalInput(value: string | null | undefined): string {
  if (value === null || value === undefined) return '';
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '';
  return `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())}T${two(at.getHours())}:${two(at.getMinutes())}`;
}
