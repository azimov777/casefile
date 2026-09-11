import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode, RefObject } from 'react';
import { cn } from '../lib';

/*
 * Шторка сбоку на Radix Dialog — `Sheet` из shadcn/ui, сокращённый до того, что
 * приложению нужно: одна сторона (левая), заголовок и содержимое.
 *
 * Берётся готовым ровно ради поведения, которое дорого написать и легко написать
 * неправильно: `Esc` закрывает, фокус запирается внутри и возвращается на кнопку,
 * фон под шторкой скрыт от программы чтения с экрана, прокрутка страницы под ней
 * заблокирована. Своими руками это тот же объём, что и меню из UI-36.
 *
 * Движение шторки описано признаками, которые Radix печатает на узле сам:
 * `data-[state=open]` и `data-[state=closed]`. Отсюда же требование к его виду —
 * `@keyframes`, а не `transition`: узел до конца выхода держит `Presence`, а он ждёт
 * `animationend` и переход не заметит. Имена движения объявлены в `theme.css`
 * (`--animate-sheet-*`, `--animate-overlay-*`) вместе с длительностью и кривой из
 * словаря UI-59: своё число здесь вывело бы шторку из-под `prefers-reduced-motion`.
 * Подложка гаснет и появляется теми же длительностью и кривой — она часть того же
 * события, а не отдельная жизнь.
 *
 * Полный `Sidebar` из shadcn/ui сюда не взят намеренно: он держит свёрнутость
 * в cookie, а состояние в этом приложении живёт в адресе (`CONVENTIONS.md`,
 * «Состояние»). На широком экране панель стоит всегда и сворачиваться не должна —
 * из всего компонента нужна была бы одна его мобильная половина, то есть эта шторка.
 */
export function Sheet({
  open,
  onOpenChange,
  title,
  closeLabel,
  returnFocusTo,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Имя шторки: диалогу без имени программа чтения с экрана говорит «диалог». */
  title: string;
  /**
   * Имя кнопки закрытия. Приходит снаружи вместе с именем шторки: кирпич `shared`
   * не знает, что за ней стоит, и подписи в его словаре быть не может.
   */
  closeLabel: string;
  /**
   * Куда вернуть фокус при закрытии. Radix возвращает его туда, где фокус был в момент
   * открытия, — но кнопка здесь не `Dialog.Trigger` (шторка и кнопка живут в разных
   * частях оболочки), и полагаться на совпадение нельзя: человек, закрывший шторку
   * с клавиатуры, оказывался бы в начале страницы.
   */
  returnFocusTo?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            'fixed inset-0 z-40 bg-ground/70',
            'data-[state=open]:animate-overlay-in data-[state=closed]:animate-overlay-out',
          )}
        />
        <DialogPrimitive.Content
          onCloseAutoFocus={(event) => {
            if (returnFocusTo?.current == null) return;
            event.preventDefault();
            returnFocusTo.current.focus();
          }}
          className={cn(
            'fixed inset-y-0 left-0 z-50 flex w-(--ui-side) flex-col',
            'border-r border-line bg-surface shadow-raised',
            'focus-visible:outline-none',
            'data-[state=open]:animate-sheet-in data-[state=closed]:animate-sheet-out',
          )}
        >
          <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Close
            aria-label={closeLabel}
            className={cn(
              'absolute top-2 right-2 grid size-7 place-items-center rounded-control text-muted',
              'transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
            )}
          >
            <X className="size-(--ui-mark)" aria-hidden="true" />
          </DialogPrimitive.Close>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
