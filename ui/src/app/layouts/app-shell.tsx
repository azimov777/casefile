import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation } from 'react-router';
import { QuestionNotice, useLiveJournal } from '@/features/live-journal';
import { Sheet } from '@/shared/ui';
import { ErrorBoundary } from '../providers/error-boundary';
import { AppSide } from './app-side';
import { AppTopbar } from './app-topbar';

export function AppShell() {
  const location = useLocation();
  // Один поток на вкладку: он поднимается здесь, а не на страницах, — переход между
  // экранами не должен стоить переподключения.
  const live = useLiveJournal();
  const { t } = useTranslation('ui');

  /*
   * Шторка узкого экрана. Единственное состояние оболочки, которое не живёт в адресе,
   * — и это правильно: «открыл меню» не то, что пересылают ссылкой (`CONCEPT.md`, 3).
   * На широком экране панель стоит всегда, и это состояние там не читается вовсе.
   */
  const [sideOpen, setSideOpen] = useState(false);
  // Кнопка, которой шторку открыли: в неё возвращается фокус при закрытии.
  const openerRef = useRef<HTMLButtonElement>(null);

  // Переход закрывает шторку: человек нажал ссылку, чтобы уйти, а не чтобы остаться
  // перед закрывающей его содержимое панелью.
  useEffect(() => {
    setSideOpen(false);
  }, [location.pathname, location.search]);

  return (
    /*
     * Панель — первая колонка сетки и занимает все её ряды; всё остальное ложится
     * во вторую без обёртки. `grid-row: 1 / span 99`, а не `1 / -1`: `-1` указывает
     * на последнюю линию явной сетки, а ряды под содержимое создаются неявно, и панель
     * осталась бы в первой строке, растянув её на свою высоту.
     */
    <div className="grid min-h-full grid-cols-[minmax(0,1fr)] fold:grid-cols-[var(--ui-side)_minmax(0,1fr)]">
      <aside
        aria-label={t('app.trackerSections')}
        className="col-start-1 row-start-1 row-end-[span_99] hidden border-r border-line bg-surface fold:block"
      >
        {/* Панель прилипает: очередь — то, куда переходят с любой глубины прокрутки. */}
        <div className="sticky top-0 h-dvh">
          <AppSide />
        </div>
      </aside>

      {/* Шторка узкого экрана: та же панель, вынутая из потока. Одно содержимое на два
          случая — иначе они разъедутся, и на телефоне человек увидит другой трекер. */}
      <Sheet
        open={sideOpen}
        onOpenChange={setSideOpen}
        title={t('app.trackerSections')}
        closeLabel={t('app.closeSections')}
        returnFocusTo={openerRef}
      >
        <AppSide onNavigate={() => setSideOpen(false)} />
      </Sheet>

      <div className="fold:col-start-2">
        <AppTopbar live={live} openerRef={openerRef} onOpenSide={() => setSideOpen(true)} />

        <div className="px-4 pt-4 pb-(--ui-page-tail)">
          {/*
           * Вторая граница, внутри оболочки: упавшая страница не уносит навигацию,
           * и человек уходит с неё ссылкой, а не перезагрузкой.
           *
           * `key` по пути: у границы нет способа узнать, что показывать снова стало
           * нечего, — уйдя со сломанной страницы, человек видел бы её объяснение и на
           * следующей. Смена пути пересоздаёт границу, и та начинает с чистого состояния.
           */}
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>

      {/*
       * Уведомления живут в оболочке, а не на странице: вопрос приходит независимо
       * от того, где человек сейчас находится, и уходить с экрана вместе со страницей
       * не должен. Границей ошибок не накрыты намеренно — упавшая страница не повод
       * замолчать о том, что человека спрашивают.
       */}
      <QuestionNotice {...live} />
    </div>
  );
}
