import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import { Button } from '@/shared/ui';
import { useDeferredList } from '../model/use-deferred-list';

/**
 * Полоса «изменилось столько-то · показать». Принадлежность таблицы: доска
 * обновляется сама, и полосы над ней нет вовсе (UI-72).
 *
 * Живой поток знает, что таблица устарела, но не перестраивает её сам: порядок строк
 * сменился бы под курсором, и промах по ссылке увёл бы не туда. Обновление здесь
 * предлагается, а решение остаётся за человеком.
 *
 * Полоса стоит вне потока вёрстки и потому ничего не сдвигает — тем же приёмом, что
 * уведомление о вопросе, и в другом углу, чтобы они не спорили за место.
 *
 * Сама не гаснет: единственный способ её убрать — показать накопленное. Полоса,
 * исчезающая по таймеру, оставила бы человека смотреть на устаревший список, ничего
 * об этом не говоря.
 */
export function UpdatesBar() {
  const { count, vague, show } = useDeferredList();
  const { t } = useTranslation('ui');

  if (count === 0 && !vague) return null;

  return (
    /*
     * Полоса стоит вне потока вёрстки: обновление, о котором человек ещё не просил,
     * не вправе сдвинуть строки, которые он читает. Место — левый нижний угол: правый
     * занят стопкой уведомлений о вопросах, и спорить за него им незачем.
     *
     * Предел ширины общий со стопкой (`--ui-float-max`): и то и другое висит над
     * содержанием в углу, и на узком экране обоим нужны поля по обе стороны.
     */
    <div
      className={cn(
        'fixed bottom-4 left-4 z-10 flex max-w-(--ui-float-max) items-center gap-3',
        'rounded-control border border-progress-line bg-progress-soft px-3 py-2',
        'text-progress shadow-raised',
      )}
      role="status"
      // Имя, а не только роль: `role="status"` носит и индикатор связи в шапке, и без
      // имени их не различить ни программе чтения с экрана, ни сквозному тесту.
      aria-label={t('live.updates')}
    >
      <span className="text-body">
        {count > 0 ? t('live.changed', { count }) : t('live.changedUnknown')}
      </span>
      <Button onClick={show}>{t('live.show')}</Button>
    </div>
  );
}
