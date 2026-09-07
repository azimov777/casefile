import * as SelectPrimitive from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib';

/*
 * Выпадающий список на Radix. Ходьба стрелками, `Esc`, возврат фокуса на триггер,
 * набор с клавиатуры и роль `listbox` приходят готовыми: это образец WAI-ARIA,
 * и писать его руками дороже, чем принять чужой словарь имён (`UI-36`).
 *
 * Своих состояний здесь нет: значение живёт в адресе страницы, как и весь отбор.
 */
interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  /** Подпись для программы чтения с экрана: у поля отбора нет видимой подписи. */
  label: string;
  options: { value: string; label: string }[];
  className?: string;
}

export function Select({ value, onValueChange, label, options, className }: SelectProps) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={label}
        className={cn(
          'inline-flex items-center gap-1 rounded-control border border-transparent bg-transparent px-2 py-1',
          'text-meta text-muted',
          'transition-colors duration-(--motion-fast) ease-fast',
          'hover:bg-sunken hover:text-text',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          className,
        )}
      >
        <SelectPrimitive.Value />
        <SelectPrimitive.Icon>
          <ChevronDown className="size-(--ui-mark) text-faint" aria-hidden="true" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-10 overflow-hidden rounded-control border border-line-strong bg-surface text-body shadow-raised"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <Item key={option.value} value={option.value}>
                {option.label}
              </Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

function Item({ value, children }: { value: string; children: ReactNode }) {
  return (
    <SelectPrimitive.Item
      value={value}
      className={cn(
        'flex cursor-default items-center gap-2 rounded-mark px-2 py-1 text-meta text-text outline-none',
        'data-[highlighted]:bg-sunken data-[state=checked]:font-medium',
      )}
    >
      <span className="w-(--ui-mark) shrink-0">
        <SelectPrimitive.ItemIndicator>
          <Check className="size-(--ui-mark) text-accent" aria-hidden="true" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}
