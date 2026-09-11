import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Сгенерированный клиент коммитится, чтобы сборка образа не зависела от бэкенда.
 * Значит, отставание копии от контракта надо ловить, а не обещать: этот тест
 * перегенерирует типы из `../openapi.json` и сверяет с закоммиченным файлом.
 */
const GENERATED = resolve(process.cwd(), 'src/shared/api/openapi.ts');
const SCHEMA = resolve(process.cwd(), '../openapi.json');

describe('сгенерированный клиент API', () => {
  it('равен тому, что даёт генератор на текущем контракте', () => {
    expect(
      existsSync(SCHEMA),
      `Не найден контракт ${SCHEMA}. Бэкенд — корень этого репозитория, на уровень выше ui/`,
    ).toBe(true);

    const cli = resolve(process.cwd(), 'node_modules/openapi-typescript/bin/cli.js');
    const expected = execFileSync(process.execPath, [cli, SCHEMA], { encoding: 'utf8' });
    const committed = readFileSync(GENERATED, 'utf8');

    expect(
      committed,
      'Контракт бэкенда разошёлся с закоммиченным клиентом — перегенерируй: pnpm gen:api',
    ).toBe(expected);
  }, 60_000);
});
