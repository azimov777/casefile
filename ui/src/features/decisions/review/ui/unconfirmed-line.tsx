import { useTranslation } from 'react-i18next';
import { Link, type To } from 'react-router';

/**
 * Строка под счётчиками задач: «Не подтверждено решений: N» ссылкой на вкладку «Решения»
 * с отбором «Не подтверждены» (TRK-758). При нуле — «Все решения подтверждены» словами,
 * без ссылки: открывать нечего. Число — `unconfirmed_decisions` карточки как есть.
 */
export function UnconfirmedLine({ count, to }: { count: number; to: To }) {
  const { t } = useTranslation('decisions');
  return (
    <p className="text-meta" data-unconfirmed={count}>
      {count === 0 ? (
        <span className="text-muted">{t('unconfirmed.none')}</span>
      ) : (
        <Link to={to}>{t('unconfirmed.some', { count })}</Link>
      )}
    </p>
  );
}
