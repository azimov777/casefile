import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group';
import type { ComponentProps } from 'react';
import { cn } from '../lib';

/*
 * Группа переключателей на Radix Toggle Group (shadcn/ui): несколько значений одного
 * вопроса — «какие приоритеты», «какие признаки» — рядом, каждое нажимается само.
 *
 * Только `type="multiple"`: элементы — кнопки с `aria-pressed`, стрелки ходят по
 * группе, Tab входит в неё один раз. Одиночный выбор здесь не заводится — у Radix он
 * становится ролью `radio`, а переключение вида, где он был бы уместен, живёт ссылками
 * (`segmented-nav.tsx`).
 *
 * Включённое значение — плашка акцентного тона и галочка не нужна: разница видна и
 * цветом, и рамкой, а программе чтения с экрана её называет `aria-pressed`.
 */
export function ToggleGroup({
  className,
  ...rest
}: Omit<ToggleGroupPrimitive.ToggleGroupMultipleProps, 'type'>) {
  return (
    <ToggleGroupPrimitive.Root
      type="multiple"
      className={cn('flex flex-wrap gap-1.5', className)}
      {...rest}
    />
  );
}

export function ToggleGroupItem({
  className,
  ...rest
}: ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  return (
    <ToggleGroupPrimitive.Item
      className={cn(
        'inline-flex min-h-(--ui-control-sm) items-center gap-1 rounded-pill border px-2.5 text-meta leading-[1.2] whitespace-nowrap',
        'transition-colors duration-(--motion-fast) ease-fast',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
        'data-[state=off]:border-line-strong data-[state=off]:bg-transparent data-[state=off]:text-muted',
        'data-[state=off]:hover:bg-sunken data-[state=off]:hover:text-text',
        'data-[state=on]:border-accent data-[state=on]:bg-accent-soft data-[state=on]:text-text',
        className,
      )}
      {...rest}
    />
  );
}
