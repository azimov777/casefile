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
  /**
   * Знак перед значением: говорит, *что* выбирают, когда подпись поля скрыта
   * (`aria-label`), а само значение — фраза вроде «сначала живые в деле».
   */
  icon?: ReactNode;
  className?: string;
}

export function Select({ value, onValueChange, label, options, icon, className }: SelectProps) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={label}
        className={cn(
          // `max-w-full` и усечение значения: подпись порядка приходит из списка, а не
          // из вёрстки, и при увеличенном вдвое тексте она шире узкого экрана — кнопка
          // расширяла документ, вместо того чтобы обрезать своё содержимое.
          'inline-flex max-w-full min-w-0 items-center gap-1 rounded-control border border-transparent bg-transparent px-2 py-1',
          'text-meta text-muted',
          'transition-colors duration-(--motion-fast) ease-fast',
          'hover:bg-sunken hover:text-text',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          className,
        )}
      >
        {icon}
        <span className="truncate">
          <SelectPrimitive.Value />
        </span>
        {/*
         * `block` на самой иконке, а не только на обёртке `SelectPrimitive.Icon`:
         * обёртка — прямой потомок `inline-flex`-ряда и блокируется флексбоксом сама
         * (CSS Display, «blockification»), а вложенный `<svg>` — нет, он остаётся
         * строчным заменяемым элементом со своим `vertical-align: baseline`. Разметки
         * без Preflight это касается напрямую: без сброса `svg { display: block }`
         * браузер подгоняет низ иконки под базовую линию текста, а не её центр под
         * центр строки, и от нижнего поля шрифта («descent») иконка визуально всплывает
         * на 2–3 px выше подписи (замерено: −2.5 px у обоих `Select` разом — общая
         * причина одна, хотя на глаз заметно только там, где рядом нет второй иконки,
         * которая бы тот же сдвиг маскировала, — у выбора языка, UI-146). `block`
         * убирает иконку из строчного контекста: её рамка перестаёт расти под
         * `line-height`, и `items-center` ряда центрирует её как есть.
         */}
        <SelectPrimitive.Icon>
          <ChevronDown className="block size-(--ui-mark) text-faint" aria-hidden="true" />
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
          {/* Та же причина и то же лекарство, что у шеврона выше: без `block` галочка
            строчная и всплывает над центром строки (замерено: −3 px). */}
          <Check className="block size-(--ui-mark) text-accent" aria-hidden="true" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}
