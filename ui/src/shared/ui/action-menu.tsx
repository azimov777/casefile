import { useRef, useState, type Ref } from 'react';
import { Ellipsis, type LucideIcon } from 'lucide-react';
import { cn } from '../lib';
import { Button } from './button';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

/** Один пункт меню: подпись, знак и действие. */
export interface ActionMenuItem {
  /** Устойчивое имя пункта: ключ строки, не подпись. */
  id: string;
  label: string;
  icon: LucideIcon;
  onSelect: () => void;
}

interface ActionMenuProps {
  /** Имя кнопки «⋯» для программы чтения с экрана: что за действия за ней. */
  label: string;
  items: readonly ActionMenuItem[];
  /** Кнопка «⋯» — сюда окно пункта возвращает фокус после закрытия (`Dialog`, `returnFocus`). */
  ref?: Ref<HTMLButtonElement>;
}

/**
 * Меню «⋯» действий над тем, что показано на экране (TRK-618): правка и архив стоят не
 * посреди чтения, а за одной кнопкой в шапке.
 *
 * На `Popover`, а не на `DropdownMenu`: пунктов два-три, каждый открывает окно, и ради
 * них не заводим зависимость. Пункты — обычные кнопки; ролей `menu`/`menuitem` нет
 * намеренно: они обещают стрелочную навигацию, которой здесь нет, — кнопки ходят `Tab`.
 * От `Popover` остаётся нужное поведение: `Esc` и щелчок мимо закрывают, фокус уходит
 * внутрь и возвращается на кнопку, панель не выходит за край окна.
 *
 * Выбор пункта сперва закрывает меню, потом зовёт действие: окно пункта живёт вне меню и
 * само возвращает фокус на «⋯». Поэтому возврат фокуса меню после выбора пункта отменён —
 * иначе оно забрало бы фокус у только что открытого окна.
 */
export function ActionMenu({ label, items, ref }: ActionMenuProps) {
  const [open, setOpen] = useState(false);
  const chosen = useRef(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button ref={ref} tone="quiet" size="sm" aria-label={label} className="px-2">
          <Ellipsis className="size-(--ui-mark)" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      {/* Панель `Popover` — `role="dialog"`, и ей нужно имя (`axe`, `aria-dialog-name`):
          то же, что у кнопки «⋯». */}
      <PopoverContent
        aria-label={label}
        align="end"
        className="w-max min-w-40 p-1"
        onCloseAutoFocus={(event) => {
          if (!chosen.current) return;
          chosen.current = false;
          event.preventDefault();
        }}
      >
        <ActionMenuItems
          items={items}
          onChoose={() => {
            chosen.current = true;
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

/**
 * Пункты меню — отдельно от всплывающего слоя: их проверяет модульный тест без `Popover`,
 * который в jsdom раскрывается секундами (`TRK/ui-testing#51`, «Панель `Popover` в
 * jsdom открывается десятки секунд»). Открытие, `Esc` и возврат фокуса проверяет сквозной.
 */
export function ActionMenuItems({
  items,
  onChoose,
}: {
  items: readonly ActionMenuItem[];
  /** Пункт выбран: меню закрывается раньше, чем пункт делает своё. */
  onChoose: () => void;
}) {
  return (
    <ul className="flex list-none flex-col p-0">
      {items.map(({ id, label, icon: Icon, onSelect }) => (
        <li key={id}>
          <button
            type="button"
            data-action={id}
            className={cn(
              // Фон и рамка названы явно: без объявленного фона браузер рисует свой
              // `ButtonFace` (`TRK/ui-shared#16`, «Кнопка без объявленного фона»).
              'flex w-full cursor-pointer items-center gap-2 rounded-mark border-none border-current bg-transparent px-2.5 py-1.5 text-left text-body text-text',
              'transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken max-fold:min-h-(--ui-tap)',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
            )}
            onClick={() => {
              onChoose();
              onSelect();
            }}
          >
            <Icon className="size-(--ui-mark) shrink-0 text-muted" aria-hidden="true" />
            {label}
          </button>
        </li>
      ))}
    </ul>
  );
}
