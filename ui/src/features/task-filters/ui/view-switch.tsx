import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { tasksHref } from '../model/href';
import type { TaskView } from '../model/filters';
import { Columns3, Rows3, type LucideIcon } from 'lucide-react';
import { SegmentedNav, SegmentedNavLink } from '@/shared/ui';

/** Порядок видов. Подписи к ним живут в словаре (`tasks.view`), а не рядом. */
const VIEWS: TaskView[] = ['table', 'board'];

/**
 * Знак вида — для узкого экрана. Там подпись уходит диктору (`max-fold:sr-only`), а на
 * виду остаётся знак: переключатель со словами, язык и состояние потока вместе с
 * крошками в одну строку 390 px не помещались, и полоса ломалась надвое (UI-134).
 * Выше точки остановки знака нет — там стоят слова, как и стояли.
 */
const ICONS: Record<TaskView, LucideIcon> = { table: Rows3, board: Columns3 };

/**
 * Переключатель вида: та же выдача таблицей или доской.
 *
 * Ссылки, а не радиогруппа. Вид живёт в адресе наравне с отбором, а значит смена
 * вида — это переход, и выглядеть он должен переходом: адрес виден в строке
 * состояния, доску можно открыть в новой вкладке, «назад» возвращает к таблице.
 * Радиогруппа обещала форму, которой нет: ни отправки, ни отмены у неё не было.
 *
 * Адрес строит `tasksHref` — то же правило, которым пользуется любая другая точка
 * навигации. Отдельной ветки переключения, собирающей адрес с нуля, в приложении
 * больше нет: именно она теряла отбор (`UI-22`).
 */
export function ViewSwitch({ view }: { view: TaskView }) {
  const [searchParams] = useSearchParams();
  const { t } = useTranslation('tasks');

  return (
    // Размер `sm`: переключатель стоит в верхней полосе рядом с выбором языка и
    // состоянием потока — плотной строкой, а не формой.
    <SegmentedNav label={t('view.label')} size="sm">
      {VIEWS.map((option) => (
        <SegmentedNavLink
          key={option}
          to={tasksHref(searchParams, { view: option })}
          /*
           * `aria-current="true"`, а не `page`: оба вида — одна и та же страница
           * списка, и «текущая страница» сказало бы неправду. Здесь текущий
           * элемент набора, а не текущий раздел.
           */
          current={option === view && 'true'}
        >
          <ViewIcon view={option} />
          <span className="max-fold:sr-only">{t(`view.${option}`)}</span>
        </SegmentedNavLink>
      ))}
    </SegmentedNav>
  );
}

function ViewIcon({ view }: { view: TaskView }) {
  const Icon = ICONS[view];
  return <Icon className="size-(--ui-mark) fold:hidden" aria-hidden="true" />;
}
