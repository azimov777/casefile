import { rmSync } from 'node:fs';
import { compose, SECRETS_DIR } from './contour';

/**
 * Контур гасится вместе с данными: следующий прогон начинается с чистой установки.
 * Ключ установки уходит вместе с ней — он выпущен для этой базы и после `down -v`
 * не значит ничего.
 */
async function globalTeardown(): Promise<void> {
  rmSync(SECRETS_DIR, { recursive: true, force: true });
  compose(['down', '-v']);
}

export default globalTeardown;
