import { useTranslation } from 'react-i18next';
import { useLanguage } from '../i18n';
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
 *
 * Язык берётся здесь, а не внутри `relativeTime`: функции там чистые и принимают его
 * параметром. `useLanguage` заодно подписывает компонент на смену языка — без подписки
 * подпись времени осталась бы русской посреди английского экрана до следующей
 * отрисовки (`docs/notes/ui.md`, «Текст ошибки берёт язык у экземпляра»).
 */
export function RelativeTime({ value, fallback = '—' }: RelativeTimeProps) {
  const { t } = useTranslation('ui');
  const { language } = useLanguage();

  const relative = relativeTime(value, { language, justNow: t('time.justNow') });
  if (relative === '') return <span aria-hidden="true">{fallback}</span>;

  return (
    <time dateTime={value ?? undefined} title={exactTime(value, language)}>
      {relative}
    </time>
  );
}
