import { Outlet, useLocation } from 'react-router';
import { ErrorBoundary } from '../providers/error-boundary';
import { AppHeader } from './app-header';
import styles from './app-shell.module.css';

export function AppShell() {
  const location = useLocation();

  return (
    <div className={styles.shell}>
      <AppHeader />
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
    </div>
  );
}
