import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Куда кладётся токен, добытый из контура: тесты читают его отсюда. */
export const TOKEN_FILE = resolve(process.cwd(), '.e2e-token');

export function compose(args: string[]): string {
  return execFileSync('docker', ['compose', ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  });
}

export function readE2eToken(): string {
  return readFileSync(TOKEN_FILE, 'utf8').trim();
}

export function writeE2eToken(token: string): void {
  writeFileSync(TOKEN_FILE, token, 'utf8');
}
