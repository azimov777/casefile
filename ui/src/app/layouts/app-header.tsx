import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, useLocation, useSearchParams } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';
import { useLogout } from '@/features/auth';
import { LiveStatus, type LiveJournal } from '@/features/live-journal';
import { Button, QueryState } from '@/shared/ui';
import styles from './app-header.module.css';

export function AppHeader({ live }: { live: LiveJournal }) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const logout = useLogout();

  // Список и доска — один и тот же путь и разный `view`, поэтому активный пункт
  // считается по пути вместе с параметром: `NavLink` сравнивает только путь
  // и подсветил бы оба пункта сразу.
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const onTasks = pathname.startsWith('/tasks');
  const board = onTasks && searchParams.get('view') === 'board';

  return (
    <header className={styles.header}>
      <span className={styles.brand}>Трекер</span>

      <nav className={styles.nav} aria-label="Разделы">
        <Link
          className={styles.link}
          to="/tasks"
          aria-current={onTasks && !board ? 'page' : undefined}
        >
          Задачи
        </Link>
        <Link
          className={styles.link}
          to="/tasks?view=board"
          aria-current={board ? 'page' : undefined}
        >
          Доска
        </Link>
        <NavLink className={styles.link} to="/questions">
          Вопросы
        </NavLink>
      </nav>

      <div className={styles.session}>
        <LiveStatus status={live.status} />

        {/* Отказ показывается с повтором: чинить бэкенд и перезагружать вкладку —
            разные действия, и второе не должно быть единственным доступным. */}
        <QueryState query={bootstrap} loading="Загружаем участника…" compact />

        {bootstrap.data === undefined ? null : (
          <>
            <span className={styles.participant}>
              {bootstrap.data.participant?.name ?? 'участника нет'}
            </span>
            {/*
             * Счётчик — ссылка во входящую: он был единственным местом, где человек
             * узнавал о вопросах, и при этом никуда не вёл. Число берётся из
             * `bootstrap` как есть: интерфейс за бэкенд не считает (`CONCEPT.md`, 6).
             */}
            <Link
              className={
                bootstrap.data.open_questions > 0 ? styles.questionsWaiting : styles.questions
              }
              to="/questions"
            >
              {bootstrap.data.open_questions > 0
                ? `Открытых вопросов: ${bootstrap.data.open_questions}`
                : 'Открытых вопросов нет'}
            </Link>
          </>
        )}

        <Button tone="quiet" onClick={logout}>
          Выйти
        </Button>
      </div>
    </header>
  );
}
