import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../lib';

/*
 * Кнопка на shadcn/ui: варианты собирает `cva`, склейку классов — `cn`, а подмену
 * тега — `Slot` из Radix. Тонов по-прежнему два, и это не оформление, а роль:
 * основное действие экрана и второстепенное рядом с ним.
 *
 * Запрет выражен цветом из токенов, а не прозрачностью: `opacity` смешивает текст
 * с фоном и роняет контраст ниже AA (`docs/notes/ui.md`, «Прозрачность поверх
 * цветной поверхности»). Отличать запрещённую кнопку от разрешённой программе
 * чтения с экрана позволяет атрибут `disabled`, а человеку — заливка и курсор.
 */
const button = cva(
  [
    'inline-flex items-center justify-center gap-2 rounded-sm border border-transparent',
    'px-4 py-2 text-md font-medium leading-[1.2]',
    // Отклик на наведение — единственное движение, которое кнопке позволено:
    // оно отвечает на действие человека, а не начинается само.
    'transition-colors duration-(--motion-fast) ease-(--motion-ease)',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-default disabled:border-border disabled:bg-surface-sunken',
    'disabled:text-text-muted',
  ],
  {
    variants: {
      tone: {
        primary: 'bg-accent text-accent-contrast enabled:hover:bg-accent-hover',
        quiet: 'border-border-strong text-text enabled:hover:bg-surface-sunken',
      },
    },
    defaultVariants: { tone: 'primary' },
  },
);

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  /** Отдать классы и поведение своему ребёнку — ссылке, которая выглядит кнопкой. */
  asChild?: boolean;
}

export function Button({
  tone = 'primary',
  className,
  type = 'button',
  asChild = false,
  ...rest
}: ButtonProps) {
  const Tag = asChild ? Slot : 'button';

  return <Tag {...rest} type={type} className={cn(button({ tone }), className)} />;
}
