import type { ReactElement } from 'react';
import { cn } from '@/shared/lib';
import type { TaskPriority } from '../api/tasks';

/** Незанятая ступень шкалы: видна, но не считается — иначе шкала теряет длину. */
const EMPTY = 'var(--color-line-strong)';

/**
 * Форма приоритета (решение Д2): высота столбиков. Три ступени одной шкалы и один
 * выход из неё — `critical` получает единственную заливку в строке, потому что это
 * не «ещё выше», а другое положение дел.
 */
const PRIORITY_SHAPE = {
  low: (
    <>
      <rect x="3" y="14" width="5" height="7" rx="1.5" fill="currentColor" />
      <rect x="9.5" y="9" width="5" height="12" rx="1.5" fill={EMPTY} />
      <rect x="16" y="4" width="5" height="17" rx="1.5" fill={EMPTY} />
    </>
  ),
  normal: (
    <>
      <rect x="3" y="14" width="5" height="7" rx="1.5" fill="currentColor" />
      <rect x="9.5" y="9" width="5" height="12" rx="1.5" fill="currentColor" />
      <rect x="16" y="4" width="5" height="17" rx="1.5" fill={EMPTY} />
    </>
  ),
  high: (
    <>
      <rect x="3" y="14" width="5" height="7" rx="1.5" fill="currentColor" />
      <rect x="9.5" y="9" width="5" height="12" rx="1.5" fill="currentColor" />
      <rect x="16" y="4" width="5" height="17" rx="1.5" fill="currentColor" />
    </>
  ),
  critical: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" />
      <path d="M12 7.6v5.6" stroke="var(--color-surface)" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="12" cy="17" r="1.4" fill="var(--color-surface)" />
    </>
  ),
} satisfies Record<TaskPriority, ReactElement>;

/**
 * Цвет приоритета. Красится только выше обычного: `low` и `normal` — обычный ход дел,
 * а «важно» и «горит» человек обязан увидеть, не читая колонку.
 */
const PRIORITY_COLOR = {
  low: 'text-muted',
  normal: 'text-muted',
  high: 'text-attention',
  critical: 'text-danger font-semibold',
} satisfies Record<TaskPriority, string>;

function isKnown(priority: string): priority is TaskPriority {
  return priority in PRIORITY_SHAPE;
}

interface PriorityMarkProps {
  priority: string | null | undefined;
  /** Там, где имени нет (карточка доски), оно уходит в доступное имя, а не пропадает. */
  withName?: boolean;
  className?: string;
}

/** Приоритет задачи: высота столбиков, а не вторая серая плашка рядом со статусом. */
export function PriorityMark({ priority, withName = true, className }: PriorityMarkProps) {
  if (priority === null || priority === undefined || priority === '') return null;

  const known = isKnown(priority);
  const shape = known ? PRIORITY_SHAPE[priority] : PRIORITY_SHAPE.normal;
  const color = known ? PRIORITY_COLOR[priority] : 'text-muted';

  return (
    <span
      data-mark="priority"
      className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', color, className)}
    >
      <svg viewBox="0 0 24 24" fill="none" className="size-(--ui-mark) shrink-0" aria-hidden="true">
        {shape}
      </svg>
      <span className="sr-only">приоритет </span>
      <span className={withName ? 'font-mono text-mark' : 'sr-only'}>{priority}</span>
    </span>
  );
}
