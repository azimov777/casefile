import type { ReactNode } from 'react';
import styles from './callout.module.css';

interface CalloutProps {
  /** `danger` — отказ или ошибка: сообщение объявляется программе чтения с экрана. */
  tone?: 'neutral' | 'danger';
  children: ReactNode;
}

/**
 * Короткое сообщение о состоянии: отказ, пояснение, честная пустота.
 * Спиннера без текста в интерфейсе нет (CONVENTIONS.md, «Интерфейс»).
 */
export function Callout({ tone = 'neutral', children }: CalloutProps) {
  const classes = [styles.callout, tone === 'danger' ? styles.danger : null]
    .filter(Boolean)
    .join(' ');

  return (
    <p className={classes} role={tone === 'danger' ? 'alert' : undefined}>
      {children}
    </p>
  );
}
