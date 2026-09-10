/*
 * `scripts/merge-task-branch.sh` под тестом: его запускают редко, в единственный
 * неудобный момент — слияние ветки задачи в `main`, — и там же меньше всего хочется
 * разбираться с самим инструментом. Три вещи ломаются молча и обнаруживаются ровно
 * тогда:
 *
 * - потерянный бит запуска: файл в репозитории есть, а `scripts/merge-task-branch.sh`
 *   отвечает «Permission denied»;
 * - опечатка в самом скрипте: `bash -n` ловит её здесь, а не на первом слиянии;
 * - разъехавшиеся скрипт и документы: строка-доказательство и обе команды прогона
 *   названы в прозе (`README.md`, `docs/CONVENTIONS.md`), и переименование в скрипте без
 *   правки документов оставляет ревизию непроверенных слияний без единой находки — тихо
 *   и навсегда, а человека — с командой в README, которой в скрипте больше нет.
 *
 * Аналог в бэкенде — `../tracker/tests/test_merge_script.py`; там набор и вопросы к нему
 * те же, но команда одна (`docker compose run --rm test`), а здесь их две разной цены
 * (`pnpm check`, `pnpm e2e`), и обе обязаны быть названы.
 */

import { execFileSync } from 'node:child_process';
import { accessSync, constants, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = resolve(__dirname, '..');
const SCRIPT = resolve(ROOT, 'scripts', 'merge-task-branch.sh');

/** Документы, описывающие слияние. Оба обязаны звать те же строку и команды, что и
 *  скрипт: расхождение здесь — это правило, которое исполняют по памяти. */
const DOCUMENTS = [resolve(ROOT, 'docs', 'CONVENTIONS.md'), resolve(ROOT, 'README.md')];

const scriptText = () => readFileSync(SCRIPT, 'utf8');

/** Значение объявления из шапки скрипта, вида `ИМЯ="значение"` или `ИМЯ=(значение)`. */
function declaration(name: string): string {
  const found = scriptText().match(new RegExp(`^${name}=(?:"([^"]+)"|\\(([^)]+)\\))`, 'm'));
  const value = found?.[1] ?? found?.[2];
  expect(value, `в скрипте нет объявления ${name}`).toBeDefined();
  return (value ?? '').trim();
}

describe('scripts/merge-task-branch.sh', () => {
  it('лежит в репозитории и несёт бит запуска', () => {
    expect(() => accessSync(SCRIPT, constants.X_OK)).not.toThrow();
  });

  it('разбирается bash без синтаксических ошибок', () => {
    expect(() => execFileSync('bash', ['-n', SCRIPT], { stdio: 'pipe' })).not.toThrow();
  });

  it('строку-доказательство называют оба документа', () => {
    const key = declaration('TRAILER_KEY');
    const missing = DOCUMENTS.filter((document) => !readFileSync(document, 'utf8').includes(key));
    expect(
      missing,
      `строка ${JSON.stringify(key)} из скрипта не названа в: ${missing.join(', ')}`,
    ).toEqual([]);
  });

  it('README называет обе команды слияния как прогон проверок', () => {
    const readme = readFileSync(resolve(ROOT, 'README.md'), 'utf8');
    for (const name of ['CHECK_COMMAND', 'E2E_COMMAND']) {
      const command = declaration(name).split(/\s+/).join(' ');
      expect(readme, `README не называет ${JSON.stringify(command)} прогоном проверок`).toContain(
        `\`${command}\``,
      );
    }
  });
});
