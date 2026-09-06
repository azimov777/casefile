import type { ReactNode } from 'react';
import styles from './badge.module.css';

/**
 * Тон плашки: положение дел, а не сущность. Поэтому `positive` носит и статус
 * `done`, и удачный вердикт, а `danger` — и блокировку, и `critical`.
 *
 * Тонов ровно шесть, по числу различимых положений: цвет на каждую сущность
 * превратил бы список в радугу, в которой не читается ничего. Цвета живут
 * в `tokens.css` — здесь только имена.
 */
export type BadgeTone = 'neutral' | 'progress' | 'positive' | 'dropped' | 'attention' | 'danger';

interface BadgeProps {
  /** Нейтральный по умолчанию: плашка без своего положения дел (тег, исполнитель). */
  tone?: BadgeTone;
  /** Моноширинный: идентификатор из контракта, а не подпись (`CONVENTIONS.md`). */
  mono?: boolean;
  title?: string;
  children: ReactNode;
}

/**
 * Короткая метка в строке таблицы: статус, приоритет, тег, признак.
 *
 * Цвет не единственный носитель смысла: подпись внутри плашки остаётся всегда
 * (`CONCEPT.md`, 6) — тон только позволяет просканировать список взглядом,
 * не читая каждую строку.
 */
export function Badge({ tone = 'neutral', mono = false, title, children }: BadgeProps) {
  const classes = [styles.badge, styles[tone], mono ? styles.mono : null].filter(Boolean).join(' ');

  return (
    <span className={classes} title={title}>
      {children}
    </span>
  );
}
