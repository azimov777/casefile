import type { TextareaHTMLAttributes } from 'react';
import { cn } from '../lib';

/*
 * Многострочное поле формы окна: то же, что `Input`, — граница, радиус, фокус, отказ
 * и запрет теми же правилами, — только в несколько строк и с ручкой высоты.
 *
 * Не поле записи в дело: у `Composer` своё поле markdown моноширинным кеглем, потому
 * что там пишут текст с разметкой и ссылками. Здесь — короткий простой текст: описание
 * проекта, значение атрибута, причина.
 */
export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...rest}
      className={cn(
        'w-full resize-y rounded-mark border border-line-strong bg-surface px-3 py-2 text-body',
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
