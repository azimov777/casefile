import { exactTime, relativeTime } from '../lib';

interface RelativeTimeProps {
  /** Метка времени из контракта; `null` бывает у полей, которых у объекта ещё нет. */
  value: string | null | undefined;
  /** Чем заменить отсутствующее время: у каждого столбца свой знак пустоты. */
  fallback?: string;
}

/**
 * «3 мин. назад» с точным временем в подсказке. Тег `time` с машинным `dateTime`:
 * относительная подпись читается глазами, точная — программой чтения с экрана
 * и наведением.
 */
export function RelativeTime({ value, fallback = '—' }: RelativeTimeProps) {
  const relative = relativeTime(value);
  if (relative === '') return <span aria-hidden="true">{fallback}</span>;

  return (
    <time dateTime={value ?? undefined} title={exactTime(value)}>
      {relative}
    </time>
  );
}
