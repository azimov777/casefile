import { cva } from 'class-variance-authority';
import type { ReactNode } from 'react';

/*
 * Тон меняет ту же тройку, что и у плашки: заливку, границу и текст. Склейки `cn`
 * здесь нет: внешнего `className` сообщение не принимает, и мирить с ним нечего —
 * `cva` отдаёт готовую строку прямо в атрибут.
 */
const callout = cva('rounded-mark border px-4 py-3 text-body', {
  variants: {
    tone: {
      neutral: 'border-line bg-sunken text-text',
      danger: 'border-danger-line bg-danger-soft text-danger',
    },
  },
  defaultVariants: { tone: 'neutral' },
});

interface CalloutProps {
  /** `danger` — отказ или ошибка: сообщение объявляется программе чтения с экрана. */
  tone?: 'neutral' | 'danger';
  /**
   * Нужен там, где на сообщение ссылается что-то ещё: запрещённая кнопка называет
   * им причину запрета (`aria-describedby`), и причина обязана быть той же самой,
   * а не второй её копией рядом.
   */
  id?: string;
  children: ReactNode;
}

/**
 * Короткое сообщение о состоянии: отказ, пояснение, честная пустота.
 * Спиннера без текста в интерфейсе нет (CONVENTIONS.md, «Интерфейс»).
 */
export function Callout({ tone = 'neutral', id, children }: CalloutProps) {
  return (
    <p id={id} className={callout({ tone })} role={tone === 'danger' ? 'alert' : undefined}>
      {children}
    </p>
  );
}
