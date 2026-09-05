import { Outlet } from 'react-router';
import { AppHeader } from './app-header';
import styles from './app-shell.module.css';

export function AppShell() {
  return (
    <div className={styles.shell}>
      <AppHeader />
      <div className={styles.content}>
        <Outlet />
      </div>
    </div>
  );
}
