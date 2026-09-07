import { Link, useSearchParams } from 'react-router';
import { tasksHref, type TaskView } from '@/features/task-filters';
import { cn } from '@/shared/lib';

const VIEWS: { value: TaskView; label: string }[] = [
  { value: 'table', label: 'Таблица' },
  { value: 'board', label: 'Доска' },
];

/**
 * Переключатель вида: та же выдача таблицей или доской.
 *
 * Ссылки, а не радиогруппа. Вид живёт в адресе наравне с отбором, а значит смена
 * вида — это переход, и выглядеть он должен переходом: адрес виден в строке
 * состояния, доску можно открыть в новой вкладке, «назад» возвращает к таблице.
 * Радиогруппа обещала форму, которой нет: ни отправки, ни отмены у неё не было.
 *
 * Адрес строит `tasksHref` — то же правило, которым пользуется любая другая точка
 * навигации. Отдельной ветки переключения, собирающей адрес с нуля, в приложении
 * больше нет: именно она теряла отбор (`UI-22`).
 */
export function ViewSwitch({ view }: { view: TaskView }) {
  const [searchParams] = useSearchParams();

  return (
    <nav
      aria-label="Вид списка"
      className="inline-flex items-center gap-px rounded-control border border-line-strong p-px"
    >
      {VIEWS.map((option) => {
        const current = option.value === view;

        return (
          <Link
            key={option.value}
            to={tasksHref(searchParams, { view: option.value })}
            /*
             * `aria-current="true"`, а не `page`: оба вида — одна и та же страница
             * списка, и «текущая страница» сказало бы неправду. Здесь текущий
             * элемент набора, а не текущий раздел.
             */
            aria-current={current ? 'true' : undefined}
            className={cn(
              'rounded-[calc(var(--radius-control)-1px)] px-3 py-1 text-meta no-underline',
              'transition-colors duration-(--motion-fast) ease-fast',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
              current
                ? 'bg-accent-soft font-semibold text-accent-strong'
                : 'text-muted hover:bg-sunken hover:text-text',
            )}
          >
            {option.label}
          </Link>
        );
      })}
    </nav>
  );
}
