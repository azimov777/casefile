import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes, Ref } from 'react';
import { cn } from '../lib';
import { controlSize } from './control-size';

/*
 * Кнопка на shadcn/ui: варианты собирает `cva`, склейку классов — `cn`, а подмену
 * тега — `Slot` из Radix. Тонов по-прежнему два, и это не оформление, а роль:
 * основное действие экрана и второстепенное рядом с ним.
 *
 * Запрет выражен цветом из токенов, а не прозрачностью: `opacity` смешивает текст
 * с фоном и роняет контраст ниже AA (`docs/notes/ui.md`, «Прозрачность поверх
 * цветной поверхности»). Отличать запрещённую кнопку от разрешённой программе
 * чтения с экрана позволяет атрибут `disabled`, а человеку — заливка и курсор.
 *
 * Размер — вариант `size` по общей шкале (`control-size.ts`), а не классы места вызова:
 * «`px-2 py-1 text-meta` рядом с кнопкой» давал каждому месту свою высоту, и кнопка
 * в строке переставала стоять вровень с соседями (UI-128). Размеров два, как и тонов:
 * `md` по умолчанию и `sm` для плотной строки. Переключатель вида (`SegmentedNav`)
 * того же размера той же высоты.
 */
const button = cva(
  [
    'inline-flex items-center justify-center rounded-mark border border-transparent',
    'font-medium leading-[1.2]',
    // Отклик на наведение — единственное движение, которое кнопке позволено:
    // оно отвечает на действие человека, а не начинается само.
    'transition-colors duration-(--motion-fast) ease-fast',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-default disabled:border-line disabled:bg-sunken disabled:text-muted',
  ],
  {
    variants: {
      tone: {
        primary: 'bg-accent text-accent-text enabled:hover:bg-accent-strong',
        // Фон назван явно, а не оставлен на умолчание: у кнопки без `background`
        // браузер рисует свой `ButtonFace` (в тёмной теме это #6b6b6b), и текст на
        // нём даёт 4.47 при норме 4.5 — поймано `axe` в сквозных.
        quiet: 'border-line-strong bg-transparent text-text enabled:hover:bg-sunken',
      },
      size: {
        md: [controlSize.md, 'gap-2 px-4 py-1.5'],
        sm: [controlSize.sm, 'gap-1.5 px-2.5 py-1'],
      },
    },
    defaultVariants: { tone: 'primary', size: 'md' },
  },
);

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  /** Отдать классы и поведение своему ребёнку — ссылке, которая выглядит кнопкой. */
  asChild?: boolean;
  /** Нужен там, где кнопка — якорь фокуса: например, после исчезновения соседа. */
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  tone = 'primary',
  size = 'md',
  className,
  type = 'button',
  asChild = false,
  ...rest
}: ButtonProps) {
  const Tag = asChild ? Slot : 'button';

  return <Tag {...rest} type={type} className={cn(button({ tone, size }), className)} />;
}
