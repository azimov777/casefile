import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/*
 * `ui/docker-compose.yml` не монтирует ничего внутрь каталога, приехавшего с хоста
 * бинд-маунтом (UI-109). Смонтировать что-нибудь внутрь такого каталога значит
 * потребовать точку монтирования, а недостающую Docker заводит сам — в источнике
 * внешнего монтирования, то есть прямо в репозитории на диске хозяина, на Linux от
 * root. Ровно так анонимный том `- /app/.venv` заводил пустой `.venv` в корне дерева
 * до этой задачи: `..:/app` монтирует репозиторий целиком, `/app/.venv` требует под
 * собой каталог, и Docker создавал его на хосте — прятать в нём уже нечего с TRK-66,
 * когда зависимости дев-образа переехали в `/opt/venv` (`../docs/notes/docker.md`,
 * «Том, вложенный в смонтированный репозиторий, заводит каталог на машине хозяина»).
 *
 * Тот же приём уже стережёт бэкенд — `../tests/test_compose.py`,
 * `test_no_contour_mounts_anything_inside_a_directory_taken_from_the_host` — но его
 * набор `COMPOSE_FILES` держит ровно два файла (дев и прод) и почти все его проверки
 * сравнивают их попарно по общим якорям (`x-app-service`, `x-app-environment`).
 * `ui/docker-compose.yml` называет якорь иначе (`x-backend`), пары «прод» не имеет и
 * форме этих сравнений не подходит — дописать его в тот словарь означало бы чинить
 * парные сравнения под непарный третий файл. Поэтому здесь свой сторож, часть
 * `pnpm check` (vitest собирает `testing/**` наравне с `src/**`), а не строка в
 * бэкенд-наборе. Аналогичное дублирование уже есть у `merge-script.test.ts` — свой
 * сторож `scripts/merge-task-branch.sh` рядом с `../tests/test_merge_script.py`.
 *
 * Разбор — без полного YAML-парсера, по отступам, тем же приёмом, что у питоновского
 * сторожа: ради одной проверки библиотека в проект не тянется, а промах разбора
 * ловят сторожевые условия ниже, а не зеленят тест молча.
 */

const ROOT = resolve(__dirname, '..');
const COMPOSE_FILE = resolve(ROOT, 'docker-compose.yml');

/**
 * Точки монтирования, вложенные в чужой каталог хоста намеренно — с доводом словами,
 * а не общим ослаблением правила. Список читается на ревизии целиком, и строка,
 * которая ни одной проверке не понадобилась, роняет прогон — тот же приём, что у
 * `NOT_IN_CODE` в `notes.test.ts`.
 */
const ALLOWED_NESTED_TARGETS: Record<string, string> = {
  '/app/.secrets':
    'local-token: `./.secrets:/app/.secrets` подменяет собой `/app/.secrets` ' +
    'смонтированного репозитория намеренно — так путь `--output` совпадает с ' +
    'рабочим каталогом образа, а ключ сквозного контура уходит не в `../.secrets` ' +
    'дев-контура бэкенда, который бы этот же вызов отозвал (UI-75)',
};

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

/** Строки файла без пустых и без комментариев: их отступ ни о чём не говорит. */
function meaningfulLines(text: string): string[] {
  return text.split('\n').filter((line) => {
    const trimmed = line.trim();
    return trimmed !== '' && !trimmed.startsWith('#');
  });
}

/**
 * Тома всех блоков `volumes:` файла, парами «источник, точка монтирования».
 *
 * У анонимного тома источника нет: строка состоит из одной точки монтирования, и
 * источник выходит пустым — `- /app/.venv` даёт `['', '/app/.venv']`. Права доступа
 * третьей частью (`- ./.secrets:/app/.secrets:ro`) отбрасываются.
 */
function mounts(lines: string[]): Array<[string, string]> {
  const found: Array<[string, string]> = [];
  let inside = false;
  let base = 0;

  for (const line of lines) {
    const stripped = line.trim();
    if (stripped === 'volumes:') {
      inside = true;
      base = indentOf(line);
      continue;
    }
    if (inside && indentOf(line) <= base) inside = false;
    if (inside && stripped.startsWith('- ')) {
      const [first = '', second] = stripped.slice(2).split(':');
      found.push(second === undefined ? ['', first] : [first, second]);
    }
  }

  return found;
}

/**
 * Источник монтирования — путь на хосте, а не том Docker. Путь на хосте записан
 * относительным (`./`, `..`) или абсолютным; имя тома с точки и косой черты не
 * начинается никогда, а у анонимного тома источника нет вовсе.
 */
function fromHost(source: string): boolean {
  return source.startsWith('.') || source.startsWith('/');
}

/** Лежит ли точка монтирования `target` внутри каталога `root`. */
function under(target: string, root: string): boolean {
  return target === root || target.startsWith(`${root}/`);
}

describe('ui/docker-compose.yml: том не вложен в каталог хоста', () => {
  it('внутри `..:/app` нет ничего, кроме разрешённых исключений', () => {
    const found = mounts(meaningfulLines(readFileSync(COMPOSE_FILE, 'utf8')));
    const fromHostTargets = found
      .filter(([source]) => fromHost(source))
      .map(([, target]) => target);

    // Сторожевое условие: без каталогов хоста проверке не с чем сравнивать, и промах
    // разбора зеленил бы её молча — файл такой каталог объявляет всегда (`..:/app`).
    expect(
      fromHostTargets.length,
      `каталоги хоста не разобраны: ${JSON.stringify(found)}`,
    ).toBeGreaterThan(0);

    const usedReliefs = new Set<string>();
    const offending: string[] = [];

    for (const [source, target] of found) {
      const nestedUnder = fromHostTargets.filter((host) => host !== target && under(target, host));
      if (nestedUnder.length === 0) continue;

      if (target in ALLOWED_NESTED_TARGETS) {
        usedReliefs.add(target);
        continue;
      }

      offending.push(
        `том \`${source || 'анонимный'}\` монтируется в ${target} — внутрь каталога ` +
          `${nestedUnder[0]}, приехавшего из репозитория хозяина. Docker заведёт там ` +
          'каталог на машине хозяина, и хозяин не сможет в него писать',
      );
    }

    expect(offending).toEqual([]);

    const idle = Object.keys(ALLOWED_NESTED_TARGETS).filter((target) => !usedReliefs.has(target));
    expect(idle, 'исключение из ALLOWED_NESTED_TARGETS не понадобилось — пора снести').toEqual([]);
  });
});
