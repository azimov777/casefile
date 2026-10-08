import { useLayoutEffect, useRef, type ReactNode } from 'react';
import type { To } from 'react-router';
import { useLanguage } from '@/shared/i18n';
import { formatNumber } from '@/shared/lib';
import { Markdown, SegmentedNav, SegmentedNavLink } from '@/shared/ui';
import type { HolderTab } from '../model/holder-tab';

/** Колонка экрана: та же ширина и тот же шаг, что у карточки задачи. */
export const HOLDER_SCREEN = 'flex max-w-(--ui-page-max) flex-col gap-4';

/** Вкладка на полосе: подпись и число, если у раздела оно есть. */
export interface HolderTabLink {
  tab: HolderTab;
  label: string;
  /** Сколько в разделе; у дела числа нет — `meta.total` у дела не считается. */
  count?: number;
}

interface HolderScreenProps {
  /** Пояснение экрана — первым блоком, над шапкой (TRK-363); у архивного его нет. */
  explanation?: ReactNode;
  /** Подпись над заголовком: «Проект», «Область». */
  kicker: string;
  /** Ключ проекта или адрес области — идентификатор контракта, моноширинным. */
  code: string;
  title: string;
  /** Короткое «что это» в markdown; пустое сказано словами `noDescription`. */
  description: string;
  noDescription: string;
  /** Строка ссылок под описанием: задачи проекта, проект области. */
  links: ReactNode;
  /** Меню «⋯» (`ProjectMenu`, `AreaMenu`) или ничего, если действий нет. */
  menu: ReactNode;
  /** Строка счётчиков задач под ссылками, над вкладками (TRK-619, TRK#46). */
  counters?: ReactNode;
  /** Плашка под шапкой: почему на экране нет правок (архив). */
  notice: ReactNode;
  /** Имя полосы вкладок для программы чтения с экрана. */
  tabsLabel: string;
  tabs: readonly HolderTabLink[];
  current: HolderTab;
  tabHref: (tab: HolderTab) => To;
  /** Содержимое открытой вкладки. */
  children: ReactNode;
}

/**
 * Общий каркас экрана проекта и страницы области (TRK-618, решение TRK#46): шапка
 * с меню «⋯», полоса вкладок и открытая вкладка под ней. Две страницы друг друга не
 * импортируют, поэтому каркас лежит здесь, рядом с разделами «Атрибуты» и «Дело», которые
 * они тоже делят.
 *
 * Вкладки — ссылки, а не `tablist`: вкладка живёт в адресе (`?tab=`), смена — переход, и
 * «Назад» возвращает прежнюю (`TRK/ui-list#17`, «Переключатель вида — это переход, а не
 * форма»). Текущая названа `aria-current="true"`: это одна страница в разном виде.
 */
export function HolderScreen({
  explanation,
  kicker,
  code,
  title,
  description,
  noDescription,
  links,
  menu,
  counters,
  notice,
  tabsLabel,
  tabs,
  current,
  tabHref,
  children,
}: HolderScreenProps) {
  return (
    <main className={HOLDER_SCREEN}>
      {explanation}

      <header className="flex flex-col gap-2">
        {/* Меню — справа от заголовка, вне строки чтения: правка и архив не стоят
            посреди того, что человек читает. */}
        <div className="flex items-start gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="text-label font-semibold tracking-caps text-faint uppercase">{kicker}</p>
            {/* Название пишет агент или человек и переносится где угодно: длину чужой
                строки интерфейс не выбирает, а прокрутки вбок на телефоне быть не должно. */}
            <h1 className="flex flex-wrap items-baseline gap-x-3 text-title wrap-anywhere">
              <span className="font-mono">{code}</span>
              <span>{title}</span>
            </h1>
          </div>
          {menu === null ? null : <div className="shrink-0">{menu}</div>}
        </div>
        {description.trim() === '' ? (
          <p className="text-muted italic">{noDescription}</p>
        ) : (
          <div className="max-w-(--ui-text-max)">
            <Markdown>{description}</Markdown>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">{links}</div>
        {counters}
        {notice}
      </header>

      <HolderTabs label={tabsLabel} tabs={tabs} current={current} tabHref={tabHref} />

      {children}
    </main>
  );
}

/**
 * Полоса вкладок. На узком экране она не переносится, а прокручивается вбок сама —
 * страница остаётся без горизонтальной прокрутки. Открытая вкладка подкручивается в поле
 * зрения полосы: по ссылке `?entry=N` открывается «Дело», последнее на полосе, и на 390 px
 * оно стояло бы за правым краем. Крутится только полоса и только вбок: страницу к записи
 * ведёт опись (`EntryIndex`), и её прокрутку трогать нельзя.
 */
function HolderTabs({
  label,
  tabs,
  current,
  tabHref,
}: {
  label: string;
  tabs: readonly HolderTabLink[];
  current: HolderTab;
  tabHref: (tab: HolderTab) => To;
}) {
  const strip = useRef<HTMLDivElement>(null);
  const { language } = useLanguage();

  useLayoutEffect(() => {
    const box = strip.current;
    const open = box?.querySelector<HTMLElement>('[aria-current]');
    if (box === null || box === undefined || open === null || open === undefined) return;
    const right = open.offsetLeft + open.offsetWidth - box.clientWidth;
    if (right > box.scrollLeft) box.scrollLeft = right;
    else if (open.offsetLeft < box.scrollLeft) box.scrollLeft = open.offsetLeft;
  }, [current]);

  return (
    /*
     * `relative` — точка отсчёта `offsetLeft` ссылок: замер выше ведётся от края полосы.
     * Поле `p-1` при `-m-1` — место под обводку фокуса: прокручиваемая обёртка режет всё,
     * что выходит за её край, а обводка ссылки стоит снаружи неё на 4 px. Отрицательное
     * поле возвращает полосу на прежнее место, в боковое поле страницы.
     */
    <div ref={strip} className="relative -m-1 overflow-x-auto p-1">
      <SegmentedNav label={label} className="w-max">
        {tabs.map(({ tab, label: tabLabel, count }) => (
          <SegmentedNavLink
            key={tab}
            to={tabHref(tab)}
            current={tab === current ? 'true' : false}
            data-tab={tab}
          >
            {/* Подпись и число — одной строкой текста, а не двумя элементами флекса:
                пробел между ними — слово, и имя ссылки для диктора — «Решения 3», а не
                «Решения3» (пробел-ребёнок флекса не рисуется и из имени выпадает). */}
            <span className="whitespace-nowrap">
              {tabLabel}
              {count === undefined ? null : (
                <>
                  {' '}
                  <span className="font-normal text-muted tabular-nums">
                    {formatNumber(count, language)}
                  </span>
                </>
              )}
            </span>
          </SegmentedNavLink>
        ))}
      </SegmentedNav>
    </div>
  );
}
