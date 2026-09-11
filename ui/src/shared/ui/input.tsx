import type { InputHTMLAttributes } from 'react';
import { cn } from '../lib';

/*
 * Поле ввода на утилитах: та же граница, что у кнопки в тихом тоне, тот же радиус,
 * тот же фокус. Состояний пять, и каждое выражено своим правилом: покой, наведение,
 * фокус, запрет и отказ (`aria-invalid`).
 *
 * Запрет — цветом и атрибутом, не прозрачностью: `opacity` смешивает текст с фоном
 * и роняет контраст ниже AA (`docs/notes/ui.md`).
 */
export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      className={cn(
        'w-full rounded-mark border border-line-strong bg-surface px-3 py-2 text-body',
        'text-text placeholder:text-faint',
        'transition-colors duration-(--motion-fast) ease-fast',
        'enabled:hover:border-accent',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
        'disabled:cursor-default disabled:border-line disabled:bg-sunken disabled:text-muted',
        'aria-invalid:border-danger aria-invalid:bg-danger-soft',
        className,
      )}
    />
  );
}
