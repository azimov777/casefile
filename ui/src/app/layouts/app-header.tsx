import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, useLocation, useSearchParams } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';
import { useLogout } from '@/features/auth';
import { tasksHref } from '@/features/task-filters';
import { LiveStatus, type LiveJournal } from '@/features/live-journal';
import { Button, QueryState } from '@/shared/ui';
import styles from './app-header.module.css';

export function AppHeader({ live }: { live: LiveJournal }) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const logout = useLogout();

  /*
   * Разделов два, а не три: доска — не раздел, а вид того же списка, и переключается
   * она там же, где живёт, — на самой странице задач. Пока «Доска» стояла в шапке
   * рядом с «Задачами», это был второй переключатель вида, собиравший адрес с нуля
   * и терявший отбор (`UI-22`).
   *
   * Раздел «Задачи» подсвечен и на таблице, и на доске, и на карточке задачи: человек
   * находится в одном месте независимо от того, каким видом он на него смотрит.
   */
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const onTasks = pathname.startsWith('/tasks');
  const onList = pathname === '/tasks';

  return (
    <header className={styles.header}>
      <span className={styles.brand}>Трекер</span>

      <nav className={styles.nav} aria-label="Разделы">
        {/*
         * Со списка ссылка ведёт в него же вместе с отбором — тем же правилом, что
         * и переключатель вида: возврат в раздел не должен незаметно показывать
         * другие задачи. С прочих экранов условиям взяться неоткуда, и ссылка честно
         * зовёт ко всем задачам.
         */}
        <Link
          className={styles.link}
          to={onList ? tasksHref(searchParams) : '/tasks'}
          aria-current={onTasks ? 'page' : undefined}
        >
          Задачи
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
