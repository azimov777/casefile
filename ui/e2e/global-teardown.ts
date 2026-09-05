import { rmSync } from 'node:fs';
import { compose, TOKEN_FILE } from './contour';

/** Контур гасится вместе с данными: следующий прогон начинается с чистой установки. */
async function globalTeardown(): Promise<void> {
  rmSync(TOKEN_FILE, { force: true });
  compose(['down', '-v']);
}

export default globalTeardown;
