import type { ButtonHTMLAttributes } from 'react';
import styles from './button.module.css';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `quiet` — второстепенное действие: контур вместо заливки. */
  tone?: 'primary' | 'quiet';
}

export function Button({ tone = 'primary', className, type = 'button', ...rest }: ButtonProps) {
  const classes = [styles.button, tone === 'quiet' ? styles.quiet : null, className]
    .filter(Boolean)
    .join(' ');

  return <button {...rest} type={type} className={classes} />;
}
