import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router';
import { caseHref, listReturnHref, taskRefHref } from '@/shared/lib';
import { SegmentedNav, SegmentedNavLink } from '@/shared/ui';

interface TaskNavProps {
  taskKey: string;
  /** Где человек сейчас: это меняет подсветку, а не набор ссылок. */
  view: 'card' | 'case';
  /**
   * Действие страницы — на карточке это «оставить замечание».
   *
   * Живёт здесь, потому что строка липкая: единственное, что человеку разрешено
   * начать самому, должно быть доступно с любой глубины прокрутки, а не лежать
   * за описью в сотню записей. Что именно это за действие, слой сущности не знает
   * и знать не должен.
   *
   * Кнопка сюда приходит размера `sm` (`<Button size="sm">`): переключатель вида
   * рядом того же размера, и строка стоит вровень.
   */
  action?: ReactNode;
}

/**
 * Возврат в список и переключение «Карточка — Дело» одной строкой над задачей.
 *
 * Липкая: дело бывает в тысячи пикселей длиной, и «уйти отсюда» должно быть доступно
 * с любой глубины прокрутки, а не только сверху. Раньше с карточки в дело вела ссылка
 * в заголовке блока «Дело» на 1300-м пикселе, а обратно — только кнопка браузера.
 *
 * Живёт в `entities/task`, потому что её показывают обе страницы задачи: разъехавшись,
 * два экземпляра одной и той же навигации начали бы вести в разные места.
 */
export function TaskNav({ taskKey, view, action }: TaskNavProps) {
  const location = useLocation();
  const back = listReturnHref(location.state);
  const { t } = useTranslation('ui');

  return (
    /*
     * Липнет к самому верху окна: с приходом боковой панели (UI-38) верхняя полоса
     * оболочки прокручивается вместе со страницей, и смещение на её высоту оставляло бы
     * под навигацией пустую щель, сквозь которую проезжало содержимое.
     *
     * Непрозрачный фон обязателен: под липкой строкой проезжает содержимое.
     */
    <nav
      className="sticky top-0 z-5 flex flex-wrap items-center justify-between gap-3 border-b border-b-line bg-ground py-2 text-meta"
      aria-label={t('task.nav.label', { key: taskKey })}
    >
      {/*
       * Настоящая ссылка с адресом, а не `history.back()`: человек должен видеть,
       * куда попадёт, и мочь открыть это в новой вкладке. Когда отбора в памяти нет
       * — вход был прямой, — ссылка честно зовёт ко всем задачам и так и называется.
       */}
      <Link className="whitespace-nowrap" to={back ?? '/tasks'}>
        {back === null ? t('task.nav.backAll') : t('task.nav.backFiltered')}
      </Link>

      {/* Действие и переключатель вида — одной группой справа. */}
      <span className="inline-flex flex-wrap items-center gap-3">
        {action}

        {/*
         * Состояние перехода передаётся дальше: уйдя в дело и вернувшись, человек
         * не должен терять отбор, с которым пришёл из списка. Размер `sm` — тот же,
         * что у действия слева: в одной строке они одной высоты (UI-128).
         */}
        <SegmentedNav label={t('task.nav.view')} size="sm">
          <SegmentedNavLink
            to={taskRefHref({ key: taskKey, entryNo: null })}
            state={location.state}
            current={view === 'card' && 'page'}
          >
            {t('task.nav.card')}
          </SegmentedNavLink>
          <SegmentedNavLink
            to={caseHref(taskKey)}
            state={location.state}
            current={view === 'case' && 'page'}
          >
            {t('task.nav.case')}
          </SegmentedNavLink>
        </SegmentedNav>
      </span>
    </nav>
  );
}
