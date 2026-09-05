import { useQuery } from '@tanstack/react-query';
import { NavLink } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';
import { useLogout } from '@/features/auth';
import { Button, QueryState } from '@/shared/ui';
import styles from './app-header.module.css';

/** Разделы, которых ещё нет: пункт видно, но он никуда не ведёт. */
const SOON = [
  { title: 'Доска', task: '03' },
  { title: 'Вопросы', task: '06' },
];

export function AppHeader() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const logout = useLogout();

  return (
    <header className={styles.header}>
      <span className={styles.brand}>Трекер</span>

      <nav className={styles.nav} aria-label="Разделы">
        <NavLink className={styles.link} to="/tasks">
          Задачи
        </NavLink>
        {SOON.map((item) => (
          <span
            key={item.title}
            className={`${styles.link} ${styles.soon}`}
            aria-disabled="true"
            title={`Появится в задаче ${item.task}`}
          >
            {item.title}
          </span>
        ))}
      </nav>

      <div className={styles.session}>
        {/* Отказ показывается с повтором: чинить бэкенд и перезагружать вкладку —
            разные действия, и второе не должно быть единственным доступным. */}
        <QueryState query={bootstrap} loading="Загружаем участника…" compact />

        {bootstrap.data === undefined ? null : (
          <>
            <span className={styles.participant}>
              {bootstrap.data.participant?.name ?? 'участника нет'}
            </span>
            <span className={styles.questions}>
              Открытых вопросов: {bootstrap.data.open_questions}
            </span>
          </>
        )}

        <Button tone="quiet" onClick={logout}>
          Выйти
        </Button>
      </div>
    </header>
  );
}
