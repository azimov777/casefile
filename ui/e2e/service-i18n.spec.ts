import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { LANGUAGE_STORAGE_KEY } from '../src/shared/i18n/languages';
import { readE2eToken, silenceJournal } from './contour';

/*
 * Служебное на языке человека (UI-140): карточка задачи и лента её дела на русском не
 * показывают ни одной английской служебной строки, на английском — ни одной русской.
 *
 * Данные при этом не переводятся (`ui/docs/CONCEPT.md`, 6), и чтобы проверка отличала
 * служебное от данных, данные набраны третьим алфавитом — греческим: в нём нет ни
 * латиницы, ни кириллицы, и любая латинская буква на русском экране или кириллическая
 * на английском пришла не от агента, а от интерфейса или от собранного трекером
 * заголовка. Идентификаторы контракта (ключи, статусы, виды связи, имена участников)
 * набраны моноширинным шрифтом и в счёт не идут — они остаются как есть по правилу.
 *
 * Строк данных не по-гречески две — название очереди `DEMO` в шапке карточки (его
 * написал не этот сценарий) и аватар исполнителя из двух букв его имени; обе
 * вычитаются ровно тем значением, которое отдал бэкенд. Ключи очередей, задач и записей
 * вычитаются образцом: это идентификаторы и там, где стоят в прозе («Дело DEMO-8»).
 */

const token = readE2eToken();

/** Фраза, по которой сценарий узнаёт свою задачу между прогонами (`e2e/AGENTS.md`). */
const MARKER = 'Δοκιμή γλώσσας υπηρεσίας';

const GREEK = {
  title: 'Υπηρεσιακές γραμμές στη γλώσσα του ανθρώπου',
  description: `${MARKER}: σενάριο από άκρο σε άκρο.`,
  goal: 'Στόχος',
  context: 'Πλαίσιο',
  constraints: 'Περιορισμοί',
  output: 'Αποτέλεσμα',
  checks: ['Πρώτος έλεγχος', 'Δεύτερος έλεγχος'],
  text: 'Κείμενο του πράκτορα',
};

async function api(
  request: APIRequestContext,
  method: 'get' | 'post' | 'patch' | 'delete',
  path: string,
  data?: Record<string, unknown>,
  expected = 200,
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    ...(data === undefined ? {} : { data }),
  });
  expect(response.status(), `${method} ${path}: ${await response.text()}`).toBe(expected);
  if (expected === 204) return {};
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

interface Seeded {
  key: string;
  /** Строки данных не по-гречески: название очереди и аватар исполнителя. */
  data: string[];
}

let ready: Promise<Seeded> | null = null;

/**
 * Задача со всеми видами того, что собирает трекер: заведение, правки разделов и поля,
 * смена исполнителя, переходы с причиной и без, связь добавлена и снята, вопрос и
 * ответ, сводка, вердикты обоих исходов, закрывающая сводка с пятой частью, замечание
 * и его разбор. Заводится один раз и узнаётся по фразе.
 */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= (async () => {
    const existing = await request.get(
      `/api/v1/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}&fields=title`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const found = ((await existing.json()) as { data: { key: string }[] }).data;
    let key = found[0]?.key;

    if (key === undefined) {
      const bootstrap = await api(request, 'get', '/api/v1/bootstrap');
      const me = (bootstrap.participant as { name: string }).name;

      const task = await api(
        request,
        'post',
        '/api/v1/tasks',
        {
          queue: 'DEMO',
          title: GREEK.title,
          description: GREEK.description,
          goal: GREEK.goal,
          context: GREEK.context,
          constraints: GREEK.constraints,
          output: GREEK.output,
          checks: GREEK.checks,
        },
        201,
      );
      key = task.key as string;
      const entries = `/api/v1/tasks/${key}/entries`;

      await api(request, 'patch', `/api/v1/tasks/${key}`, {
        goal: `${GREEK.goal} 2`,
        priority: 'high',
        assignee: me,
      });
      await api(request, 'post', `/api/v1/tasks/${key}/transition`, { to: 'open' });
      await api(request, 'post', `/api/v1/tasks/${key}/transition`, { to: 'in_progress' });
      await api(
        request,
        'post',
        `/api/v1/tasks/${key}/links`,
        { kind: 'relates', other: 'DEMO-1' },
        201,
      );
      await api(request, 'delete', `/api/v1/tasks/${key}/links/relates/DEMO-1`, undefined, 204);

      await api(
        request,
        'post',
        entries,
        { type: 'decision', title: GREEK.text, body: GREEK.text },
        201,
      );
      const question = await api(
        request,
        'post',
        entries,
        {
          type: 'question',
          title: GREEK.text,
          body: GREEK.text,
          payload: { addressees: [me], blocking: false },
        },
        201,
      );
      await api(
        request,
        'post',
        entries,
        { type: 'answer', body: GREEK.text, payload: { question_no: question.no } },
        201,
      );
      await api(
        request,
        'post',
        entries,
        {
          type: 'summary',
          payload: {
            done: GREEK.text,
            remaining: GREEK.text,
            blockers: GREEK.text,
            next_step: GREEK.text,
          },
        },
        201,
      );
      await api(
        request,
        'post',
        entries,
        { type: 'verdict', body: GREEK.text, payload: { check_no: 1, outcome: 'failed' } },
        201,
      );
      await api(request, 'post', `/api/v1/tasks/${key}/close`, {
        verdicts: [
          { check_no: 1, outcome: 'passed', evidence: GREEK.text },
          { check_no: 2, outcome: 'passed', evidence: GREEK.text },
        ],
        summary: {
          done: GREEK.text,
          remaining: GREEK.text,
          blockers: GREEK.text,
          next_step: GREEK.text,
          unmeasured: GREEK.text,
        },
      });
      const remark = await api(
        request,
        'post',
        entries,
        { type: 'remark', title: GREEK.text, body: GREEK.text },
        201,
      );
      await api(
        request,
        'post',
        entries,
        {
          type: 'resolution',
          body: GREEK.text,
          payload: { remark_no: remark.no, outcome: 'accepted', task: 'DEMO-1' },
        },
        201,
      );
    }

    const detail = await api(request, 'get', `/api/v1/tasks/${key}`);
    const task = detail.task as { queue: { title: string }; assignee: string };
    /*
     * Аватар исполнителя в шапке карточки — две первые буквы его имени: это данные
     * (имя участника), а не подпись, но набраны они не моноширинным.
     */
    return { key, data: [task.queue.title, task.assignee.slice(0, 2)] };
  })();
  return ready;
}

/**
 * Видимые строки экрана, в которых нашлась буква чужого языка.
 *
 * Обходятся текстовые узлы `main` и подписи, которые человек видит подсказкой или слышит
 * от диктора (`aria-label`, `title`, `placeholder`). Моноширинное — идентификаторы
 * контракта — не считается; из подписей вырезаются ключи задач и записей, а из всего —
 * названные строки данных.
 */
async function foreign(page: Page, letter: RegExp, data: string[]): Promise<string[]> {
  return page.evaluate(
    ({ source, data }) => {
      const pattern = new RegExp(source);
      const found: string[] = [];
      // Названные строки данных и ключи очередей, задач и записей (`DEMO`, `DEMO-8`,
      // `DEMO-8#3`): ключ — идентификатор, даже когда стоит в прозе заголовка.
      const clean = (text: string) =>
        data
          .reduce((rest, value) => rest.split(value).join(''), text)
          .replace(/\b[A-Z][A-Z0-9]+(-\d+(#\d+)?)?\b/g, '');
      const root = document.querySelector('main');
      if (root === null) return ['<main> не найден'];

      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
        const holder = node.parentElement;
        if (holder === null || holder.closest('code, pre, kbd, .font-mono') !== null) continue;
        if (!holder.checkVisibility()) continue;
        const text = clean(node.textContent ?? '');
        if (pattern.test(text)) found.push(text.trim());
      }

      for (const element of Array.from(
        root.querySelectorAll('[aria-label], [title], [placeholder]'),
      )) {
        if (!(element as HTMLElement).checkVisibility()) continue;
        for (const name of ['aria-label', 'title', 'placeholder']) {
          const value = element.getAttribute(name);
          if (value === null) continue;
          const text = clean(value);
          if (pattern.test(text)) found.push(`@${name}: ${value}`);
        }
      }
      return found;
    },
    { source: letter.source, data },
  );
}

const LANGUAGES = [
  // На русском экране ищется латинское слово: одна буква — это `№`-подобные значки и
  // единицы, словом она не бывает.
  { lang: 'ru', letter: /[A-Za-z]{2,}/, card: 'Задание', case: 'Дело' },
  { lang: 'en', letter: /[А-Яа-яЁё]/, card: 'Assignment', case: 'Case' },
] as const;

for (const { lang, letter, card, case: caseHeading } of LANGUAGES) {
  test.describe(`служебное на языке человека: ${lang} (UI-140)`, () => {
    test.beforeEach(async ({ page }) => {
      await silenceJournal(page);
      await page.addInitScript(
        ([key, value]) => window.localStorage.setItem(key, value),
        [LANGUAGE_STORAGE_KEY, lang],
      );
    });

    test('карточка задачи: опись со всеми раскрытыми записями', async ({ page, request }) => {
      const { key, data } = await seed(request);
      await page.goto(`/tasks/${key}`);
      await expect(page.getByRole('heading', { name: card, exact: true })).toBeVisible();

      // Каждая строка описи раскрыта: у раскрытой под заголовком стоит тело записи.
      const toggles = page.locator('main button[aria-expanded="false"]');
      while ((await toggles.count()) > 0) {
        await toggles.first().click();
      }
      await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0);
      await expect(page.locator('main').getByText(GREEK.text).first()).toBeVisible();

      expect(await foreign(page, letter, data)).toEqual([]);
    });

    test('лента дела: служебные записи, сводки и вердикты', async ({ page, request }) => {
      const { key, data } = await seed(request);
      await page.goto(`/tasks/${key}/case`);
      await expect(page.getByRole('heading', { name: `${caseHeading} ${key}` })).toBeVisible();

      // Все типы, которые завёл сценарий, на экране: без этого пустая лента прошла бы.
      for (const type of [
        'created',
        'section_changed',
        'field_changed',
        'assignee_changed',
        'status_changed',
        'link_added',
        'link_removed',
        'question',
        'answer',
        'summary',
        'verdict',
        'remark',
        'resolution',
      ]) {
        await expect(page.locator(`article[data-type="${type}"]`).first()).toBeVisible();
      }

      expect(await foreign(page, letter, data)).toEqual([]);
    });
  });
}
