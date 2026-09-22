import * as PopoverPrimitive from '@radix-ui/react-popover';
import type { ComponentProps } from 'react';
import { cn } from '../lib';

/*
 * Всплывающая панель у кнопки на Radix Popover (shadcn/ui). Взята ради поведения, а не
 * вида: `Esc` и щелчок мимо закрывают, фокус уходит внутрь и возвращается на кнопку,
 * панель не выходит за край окна и переворачивается, когда снизу нет места.
 *
 * В отличие от меню (`DropdownMenu`) внутри стоят обычные элементы формы — поле,
 * группа переключателей: у меню своя клавиатура (набор с клавиатуры ищет пункт), и поле
 * ввода в нём не работало бы.
 *
 * **Движения нет намеренно**, как у окна (`dialog.tsx`): панель стоит вне потока вёрстки
 * и, появляясь, ничего не сдвигает — сглаживать нечего.
 */
export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

export function PopoverContent({
  className,
  align = 'start',
  sideOffset = 4,
  ...rest
}: ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        // `collisionPadding` — боковое поле узкого экрана: панель прижимается к краю
        // не вплотную, а с тем же отступом, что и содержимое страницы.
        collisionPadding={16}
        className={cn(
          'z-10 max-w-(--radix-popover-content-available-width) rounded-control border border-line-strong',
          'bg-surface p-3 text-body text-text shadow-raised',
          'focus-visible:outline-none',
          className,
        )}
        {...rest}
      />
    </PopoverPrimitive.Portal>
  );
}
