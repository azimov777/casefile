import { Outlet, useLocation } from 'react-router';
import { QuestionNotice, useLiveJournal } from '@/features/live-journal';
import { ErrorBoundary } from '../providers/error-boundary';
import { AppHeader } from './app-header';
import styles from './app-shell.module.css';

export function AppShell() {
  const location = useLocation();
  // Один поток на вкладку: он поднимается здесь, а не на страницах, — переход между
  // экранами не должен стоить переподключения.
  const live = useLiveJournal();

  return (
    <div className={styles.shell}>
      <AppHeader live={live} />
      <div className={styles.content}>
        {/*
         * Вторая граница, внутри оболочки: упавшая страница не уносит шапку, и человек
         * уходит с неё ссылкой, а не перезагрузкой.
         *
         * `key` по пути: у границы нет способа узнать, что показывать снова стало
         * нечего, — уйдя со сломанной страницы, человек видел бы её объяснение и на
         * следующей. Смена пути пересоздаёт границу, и та начинает с чистого состояния.
         */}
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
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
