/*
 * `scripts/merge-task-branch.sh` под тестом: его запускают редко, в единственный
 * неудобный момент — слияние ветки задачи в `main`, — и там же меньше всего хочется
 * разбираться с самим инструментом. Четыре вещи ломаются молча и обнаруживаются ровно
 * тогда:
 *
 * - потерянный бит запуска: файл в репозитории есть, а `scripts/merge-task-branch.sh`
 *   отвечает «Permission denied»;
 * - опечатка в самом скрипте: `bash -n` ловит её здесь, а не на первом слиянии;
 * - разъехавшиеся скрипт и документы: строка-доказательство и обе команды прогона
 *   названы в прозе (`README.md`, `docs/CONVENTIONS.md`), и переименование в скрипте без
 *   правки документов оставляет ревизию непроверенных слияний без единой находки — тихо
 *   и навсегда, а человека — с командой в README, которой в скрипте больше нет;
 * - сообщение из `-m` теряется на конфликте (UI-96): скрипт выходит подсказкой про
 *   `--continue` раньше, чем кладёт `MESSAGE` в `MERGE_MSG`, и повторный вызов
 *   `--continue` этого сообщения уже не знает — коммит слияния получает заголовок,
 *   который предложил сам git.
 *
 * Последнюю проверку ведут на временном git-репозитории с настоящим конфликтом: сам
 * `scripts/merge-task-branch.sh` запускается по-настоящему, а `pnpm check`/`pnpm e2e`
 * подменены поддельным `pnpm` на `PATH` — мгновенным и не трогающим ни Docker, ни этот
 * репозиторий.
 *
 * Аналог в бэкенде — `../tracker/tests/test_merge_script.py`; там набор и вопросы к нему
 * те же, но команда одна (`docker compose run --rm test`), а здесь их две разной цены
 * (`pnpm check`, `pnpm e2e`), и обе обязаны быть названы. Проверки конфликта там нет —
 * тот же дефект живёт и в `../tracker/scripts/merge-task-branch.sh`, но это отдельная
 * задача очереди `TRK`, не этого файла.
 */

import { execFileSync, spawnSync } from 'node:child_process';
import {
  accessSync,
  chmodSync,
  constants,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

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

// --- Сообщение из `-m` через конфликт -------------------------------------------------

/** Поддельный `pnpm`: отвечает на `check` и `e2e` мгновенно и зелёным, не трогая ни
 *  Docker, ни настоящий набор. Формат строк подобран под `summary_of_check`/
 *  `summary_of_e2e` скрипта — им всё равно, откуда строка, лишь бы форма совпала. */
const FAKE_PNPM = `#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  check) echo "Tests  1 passed (1)" ;;
  e2e) echo "1 passed (0.1s)" ;;
  *)
    echo "поддельный pnpm не знает команду: \${1:-}" >&2
    exit 1
    ;;
esac
`;

const cleanupPaths: string[] = [];

afterEach(() => {
  while (cleanupPaths.length > 0) {
    rmSync(cleanupPaths.pop() as string, { recursive: true, force: true });
  }
});

function git(cwd: string, args: string[]): void {
  execFileSync('git', args, { cwd, stdio: 'pipe' });
}

/** Каталог с единственным поддельным `pnpm` на `PATH`, впереди настоящего. */
function makeFakeBin(): string {
  const bin = mkdtempSync(join(tmpdir(), 'merge-script-fakebin-'));
  cleanupPaths.push(bin);
  const pnpmPath = join(bin, 'pnpm');
  writeFileSync(pnpmPath, FAKE_PNPM);
  chmodSync(pnpmPath, 0o755);
  return bin;
}

/** Временный репозиторий с веткой `task/UI-0`, конфликтующей с `main` в одной строке
 *  одного файла: обе ветки меняют её по-своему от общей базы. */
function makeRepoWithConflict(): string {
  const repo = mkdtempSync(join(tmpdir(), 'merge-script-repo-'));
  cleanupPaths.push(repo);
  git(repo, ['init', '--quiet']);
  git(repo, ['checkout', '--quiet', '-b', 'main']);
  git(repo, ['config', 'user.email', 'test@example.invalid']);
  git(repo, ['config', 'user.name', 'Test']);

  const file = join(repo, 'file.txt');
  writeFileSync(file, 'база\n');
  git(repo, ['add', 'file.txt']);
  git(repo, ['commit', '--quiet', '-m', 'база']);

  git(repo, ['checkout', '--quiet', '-b', 'task/UI-0']);
  writeFileSync(file, 'из ветки\n');
  git(repo, ['add', 'file.txt']);
  git(repo, ['commit', '--quiet', '-m', 'из ветки']);

  git(repo, ['checkout', '--quiet', 'main']);
  writeFileSync(file, 'из main\n');
  git(repo, ['add', 'file.txt']);
  git(repo, ['commit', '--quiet', '-m', 'из main']);

  return repo;
}

function runScript(repo: string, fakeBin: string, args: string[]) {
  return spawnSync(SCRIPT, args, {
    cwd: repo,
    encoding: 'utf8',
    env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH ?? ''}` },
  });
}

function resolveConflict(repo: string): void {
  writeFileSync(join(repo, 'file.txt'), 'разрешено\n');
  git(repo, ['add', 'file.txt']);
}

function commitBody(repo: string): string {
  return execFileSync('git', ['log', '-1', '--format=%B'], { cwd: repo, encoding: 'utf8' });
}

describe('scripts/merge-task-branch.sh: сообщение из -m через конфликт (UI-96)', () => {
  it('с -m: заголовок коммита после --continue — переданное сообщение, а не предложение git', () => {
    const repo = makeRepoWithConflict();
    const fakeBin = makeFakeBin();
    const message = 'merge(x): проверка (UI-0)';

    const conflicted = runScript(repo, fakeBin, ['task/UI-0', '-m', message]);
    expect(conflicted.status, conflicted.stdout + conflicted.stderr).toBe(1);
    expect(conflicted.stdout).toContain('--continue');

    resolveConflict(repo);

    const continued = runScript(repo, fakeBin, ['--continue']);
    expect(continued.status, continued.stdout + continued.stderr).toBe(0);

    const body = commitBody(repo);
    expect(body.split('\n')[0]).toBe(message);
    expect(body).toContain('Merge-verified:');
  });

  it('без -m: заголовок после --continue — прежнее поведение, предложение git', () => {
    const repo = makeRepoWithConflict();
    const fakeBin = makeFakeBin();

    const conflicted = runScript(repo, fakeBin, ['task/UI-0']);
    expect(conflicted.status, conflicted.stdout + conflicted.stderr).toBe(1);

    resolveConflict(repo);

    const continued = runScript(repo, fakeBin, ['--continue']);
    expect(continued.status, continued.stdout + continued.stderr).toBe(0);

    const body = commitBody(repo);
    expect(body).toMatch(/^Merge branch 'task\/UI-0'/);
    expect(body).toContain('Merge-verified:');
  });
});
