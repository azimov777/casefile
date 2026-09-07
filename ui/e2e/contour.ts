import { execFileSync } from 'node:child_process';
import type { Page } from '@playwright/test';
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

/**
 * Глушит живой поток на этой странице: соединение открывается и молчит навсегда.
 *
 * Нужно там, где сценарий считает запросы. Живой поток перечитывает показанное по
 * кадрам журнала, и в такой проверке он превращается в источник случайных чисел —
 * а проверяется в ней не он, а то, что экран рисуется одним запросом. Сам поток
 * проверяет `live.spec.ts`.
 */
export async function silenceJournal(page: Page): Promise<void> {
  await page.route('**/api/v1/journal/stream*', () => new Promise(() => {}));
}

/**
 * Ждёт, пока страница дорисуется тем шрифтом, которым будет жить.
 *
 * Fira приходит с внешнего хоста уже после первой отрисовки и меняет метрику: ширины
 * ячеек, высоты строк и точки переноса сдвигаются. Координата, снятая до этого, ведёт
 * мимо — протяжка по имени исполнителя начиналась в соседней ячейке. Любой замер
 * геометрии в сквозном тесте снимается после этого ожидания.
 */
export async function fontsReady(page: Page): Promise<void> {
  await page.evaluate(() => document.fonts.ready);
}
