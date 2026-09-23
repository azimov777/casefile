import { useId, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '../lib';

/*
 * Кирпичи строки состояния отбора и панели «Фильтр»: общий кусок отбора задач (UI-130)
 * и отбора записей дела (UI-137). Два экрана с одним смыслом обязаны выглядеть
 * одинаково, а не разойтись каждый своим классом, — сюда переехало то, что раньше жило
 * дважды: в `features/task-filters/ui/task-filters.tsx` и `pages/case/ui/case-filters.tsx`.
 */

/** Часть чипа: своя мишень с откликом на наведение и видимым фокусом. */
const CHIP_PART =
  'rounded-pill border-none bg-transparent leading-[1.4] transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus';

/**
 * Список чипов включённых условий. Список, а не абзац: программа чтения с экрана
 * называет число условий вслух, а `aria-label` роль абзаца не принимает.
 */
export function FilterChipList({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul className="flex min-w-0 list-none flex-wrap items-center gap-1.5 p-0" aria-label={label}>
      {children}
    </ul>
  );
}

interface FilterChipProps {
  /** Текст чипа: слово из контракта или условие, собранное словами. */
  label: ReactNode;
  removeLabel: string;
  onOpen: () => void;
  onRemove: () => void;
}

/**
 * Одно условие — две соседние мишени, а не кнопка в кнопке: текст открывает панель
 * «Фильтр» (человек передумал и хочет его поправить), крестик снимает условие целиком.
 */
export function FilterChip({ label, removeLabel, onOpen, onRemove }: FilterChipProps) {
  return (
    <li className="inline-flex items-center rounded-pill bg-accent-soft text-mark whitespace-nowrap text-text">
      <button type="button" className={cn(CHIP_PART, 'py-0.5 pr-1 pl-2.5')} onClick={onOpen}>
        {label}
      </button>
      <button
        type="button"
        className={cn(CHIP_PART, 'mr-0.5 grid size-5 place-items-center text-muted')}
        aria-label={removeLabel}
        onClick={onRemove}
      >
        <X className="size-(--ui-mark)" aria-hidden="true" />
      </button>
    </li>
  );
}

/** Сброс — действие-ссылка в строке состояния, а не третья кнопка рядом с чипами. */
export function FilterResetButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="rounded-mark border-none bg-transparent p-0 text-meta text-muted underline underline-offset-2 hover:text-text focus-visible:outline-2 focus-visible:outline-focus"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/**
 * Число условий на кнопке «Фильтр» — чтобы связать её с чипами под строкой. Глазам
 * хватает цифры, диктору чипы и так называют всё списком (`aria-hidden`).
 */
export function FilterCountBadge({ count }: { count: number }) {
  return (
    <span
      className="grid min-w-4 place-items-center rounded-pill bg-accent px-1 text-label leading-[1.4] text-accent-text"
      aria-hidden="true"
    >
      {count}
    </span>
  );
}

/** Одна группа панели «Фильтр»: подпись над переключателями, связанная с ними по `aria-labelledby`. */
export function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: (labelId: string) => ReactNode;
}) {
  const labelId = useId();

  return (
    <div className="flex flex-col gap-1.5">
      <span id={labelId} className="text-label text-muted">
        {label}
      </span>
      {children(labelId)}
    </div>
  );
}
