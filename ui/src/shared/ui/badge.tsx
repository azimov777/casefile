import type { ReactNode } from 'react';
import styles from './badge.module.css';

interface BadgeProps {
  /** `danger` — то, что мешает работе: блокировка, блокирующий вопрос. */
  tone?: 'neutral' | 'danger';
  /** Моноширинный: идентификатор из контракта, а не подпись (`CONVENTIONS.md`). */
  mono?: boolean;
  title?: string;
  children: ReactNode;
}

/** Короткая метка в строке таблицы: статус, приоритет, тег, признак. */
export function Badge({ tone = 'neutral', mono = false, title, children }: BadgeProps) {
  const classes = [
    styles.badge,
    tone === 'danger' ? styles.danger : null,
    mono ? styles.mono : null,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes} title={title}>
      {children}
    </span>
  );
}
