import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib';

/*
 * Модальное окно посреди экрана на Radix Dialog — тот же примитив, что у шторки
 * (`sheet.tsx`), и взят он ради того же поведения: `Esc`, ловушка фокуса, возврат
 * фокуса, скрытый от программы чтения с экрана фон, заблокированная прокрутка
 * страницы под ним.
 *
 * Отдельный компонент, а не вариант шторки: шторка — это место сбоку, у которого своё
 * движение и своя ширина, а здесь окно посреди экрана, и общего у них ровно столько,
 * сколько даёт сам Radix.
 *
 * **Движения нет намеренно.** Словарь движения (`theme.css`) пополняется, только когда
 * движению есть что сгладить: окно стоит вне потока вёрстки и ничего не сдвигает,
 * появляясь. Заодно это снимает гонку замера доступности с промежуточными кадрами
 * (`docs/notes/testing.md`, «Замер `axe` на экране, куда может прийти уведомление»).
 *
 * **Щелчок мимо окна его не закрывает.** В окне стоит либо то, что показано один раз
 * и второй раз не покажется (секрет выпущенного токена), либо вопрос о необратимом
 * действии: случайный щелчок по фону не должен ни того, ни другого решать. `Esc` и
 * кнопка закрытия остаются — это действия, а не промах.
 */
/**
 * Роль окна, спрашивающего о необратимом. Объявлена здесь, а не в разметке: роль —
 * значение ARIA, а не подпись, и сторож подписей в разметке видит только строку.
 */
const ALERT_ROLE = { role: 'alertdialog' } as const;

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  closeLabel,
  alert = false,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Заголовок окна. Он же — его имя для программы чтения с экрана. */
  title: string;
  /**
   * Что случилось или о чём спрашивают — одной фразой. Приходит подписью самого окна
   * (`aria-describedby`), поэтому программа чтения с экрана произносит её сразу за
   * заголовком, а не когда человек доберётся до текста.
   */
  description: ReactNode;
  closeLabel: string;
  /**
   * Окно спрашивает о необратимом действии: роль `alertdialog`. Разница не в виде,
   * а в том, как окно объявляет себя, — отдельной зависимости (`react-alert-dialog`)
   * ради этого не берём: у Radix роль перекрывается пропсом.
   */
  alert?: boolean;
  children: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ground/70" />
        <DialogPrimitive.Content
          // Роль ставится только своя: `role={undefined}` перебило бы `role="dialog"`,
          // который Radix печатает сам, — и окно осталось бы без роли вовсе.
          {...(alert ? ALERT_ROLE : {})}
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          className={cn(
            'fixed top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2',
            'flex max-h-(--ui-dialog-height) w-(--ui-dialog-max) flex-col gap-3',
            'rounded-block border border-line bg-surface p-4 shadow-raised',
            'focus-visible:outline-none',
          )}
        >
          <div className="flex items-start gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <DialogPrimitive.Title className="text-screen">{title}</DialogPrimitive.Title>
              <DialogPrimitive.Description className="max-w-(--ui-text-max) text-meta text-muted">
                {description}
              </DialogPrimitive.Description>
            </div>

            <DialogPrimitive.Close
              aria-label={closeLabel}
              className={cn(
                'ml-auto grid size-7 shrink-0 place-items-center rounded-control text-muted',
                'transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
              )}
            >
              <X className="size-(--ui-mark)" aria-hidden="true" />
            </DialogPrimitive.Close>
          </div>

          {/* Прокручивается содержимое, а не окно: заголовок и вопрос остаются на виду,
              а фрагменты подключения бывают длиннее экрана. Область достижима с
              клавиатуры сама — в ней стоят кнопки копирования. */}
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
