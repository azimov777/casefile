import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, useLocation, useSearchParams } from 'react-router';
import { Inbox } from 'lucide-react';
import { bootstrapQueryOptions } from '@/entities/session';
import { useLogout } from '@/features/auth';
import { tasksHref } from '@/features/task-filters';
import { LiveStatus, type LiveJournal } from '@/features/live-journal';
import { Button, QueryState } from '@/shared/ui';
import { cn } from '@/shared/lib';
import { readPlace } from './place';

/**
 * Содержимое боковой панели: где человек работает, кто он и жив ли поток.
 *
 * Очередь — место, а не поле формы отбора (решение Д25). Раньше, чтобы перейти из `UI`
 * в `TRK`, человек разворачивал форму на 295 px, менял выпадающий список и сворачивал
 * обратно; при этом очередь — первое, чем он делит работу.
 *
 * Действий, меняющих данные, здесь нет и не будет: человек наблюдает и отвечает,
 * остальное делают агенты (`CONCEPT.md`, 1 и 7). Единственная кнопка — выход.
 */
export function AppSide({ live, onNavigate }: { live: LiveJournal; onNavigate?: () => void }) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const logout = useLogout();
  const [searchParams] = useSearchParams();
  const location = useLocation();

  const queues = bootstrap.data?.queues ?? [];
  const place = readPlace(location.pathname, searchParams);
  const onList = location.pathname === '/tasks';

  /**
   * Переход в очередь сохраняет вид и остальной отбор — тем же правилом, что и
   * переключатель вида. Условия берутся из адреса только на самом списке: на карточке
   * задачи и во входящей в адресе стоит чужое состояние, и тащить его в отбор нельзя.
   */
  function queueHref(queue: string): string {
    return tasksHref(onList ? searchParams : new URLSearchParams(), { queue });
  }

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <span className="flex items-center gap-2 px-2 pt-1 pb-2 font-semibold tracking-[-0.01em]">
        <span
          aria-hidden="true"
          className="grid size-5 place-items-center rounded-mark bg-accent font-mono text-mark text-accent-text"
        >
          Т
        </span>
        Трекер
      </span>

      <nav className="flex flex-col gap-px" aria-label="Разделы">
        <p className="mt-1 mb-0.5 ml-2 text-label font-semibold tracking-caps text-faint uppercase">
          Очереди
        </p>

        {/* «Все задачи» — то же самое, что пустая очередь в отборе: без этого пункта
            из очереди некуда вернуться, кроме как снятием чипа в форме. */}
        <SideLink to={queueHref('')} current={place.queue === null && onList} onClick={onNavigate}>
          Все задачи
        </SideLink>

        {queues.map((queue) => (
          <SideLink
            key={queue.key}
            to={queueHref(queue.key)}
            current={place.queue === queue.key}
            title={queue.title}
            onClick={onNavigate}
          >
            <span className="font-mono">{queue.key}</span>
            <span className="truncate text-faint">{queue.title}</span>
          </SideLink>
        ))}

        <p className="mt-3 mb-0.5 ml-2 text-label font-semibold tracking-caps text-faint uppercase">
          Мне
        </p>

        <NavLink
          to="/questions"
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2 rounded-control px-2 py-1 text-meta no-underline',
              'transition-colors duration-(--motion-fast) ease-fast',
              isActive
                ? 'bg-accent-soft font-semibold text-accent'
                : 'text-muted hover:bg-sunken hover:text-text',
            )
          }
        >
          <Inbox className="size-(--ui-mark) shrink-0" aria-hidden="true" />
          Входящая
          {/*
           * Счётчик читается как число с подписью, а не голой цифрой: «2» рядом со
           * словом «Входящая» диктор произнесёт как часть названия раздела. Само число
           * берётся из `bootstrap` как есть — интерфейс за бэкенд не считает.
           */}
          {bootstrap.data === undefined ? null : (
            <span
              className={cn(
                'ml-auto font-mono text-mark tabular-nums',
                bootstrap.data.open_questions > 0 ? 'font-semibold text-attention' : 'text-faint',
              )}
            >
              <span className="sr-only">
                {bootstrap.data.open_questions > 0
                  ? `Открытых вопросов: ${bootstrap.data.open_questions}`
                  : 'Открытых вопросов нет'}
              </span>
              <span aria-hidden="true">{bootstrap.data.open_questions}</span>
            </span>
          )}
        </NavLink>
      </nav>

      <div className="mt-auto flex flex-col items-start gap-1 border-t border-line px-2 pt-2 text-mark">
        <LiveStatus status={live.status} />

        {/* Отказ показывается с повтором: чинить бэкенд и перезагружать вкладку —
            разные действия, и второе не должно быть единственным доступным. */}
        <QueryState query={bootstrap} loading="Загружаем участника…" compact />

        {bootstrap.data === undefined ? null : (
          <span className="font-mono text-muted">
            {bootstrap.data.participant?.name ?? 'участника нет'}
          </span>
        )}

        <Button tone="quiet" className="px-2 py-1 text-meta" onClick={logout}>
          Выйти
        </Button>
      </div>
    </div>
  );
}

/** Пункт панели. Текущее место помечено `aria-current`, а не только заливкой. */
function SideLink({
  to,
  current,
  title,
  onClick,
  children,
}: {
  to: string;
  current: boolean;
  title?: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      title={title}
      onClick={onClick}
      aria-current={current ? 'page' : undefined}
      className={cn(
        'flex items-center gap-2 overflow-hidden rounded-control px-2 py-1 text-meta no-underline',
        'transition-colors duration-(--motion-fast) ease-fast',
        current
          ? 'bg-accent-soft font-semibold text-accent'
          : 'text-muted hover:bg-sunken hover:text-text',
      )}
    >
      {children}
    </Link>
  );
}
