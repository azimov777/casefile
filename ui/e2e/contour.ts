import { execFileSync } from 'node:child_process';
import {
  expect,
  type APIRequestContext,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Каталог, в который контур кладёт ключ установки. Заводится до подъёма: недостающий
 * источник bind-mount Docker создаёт сам и на Linux — от root.
 */
export const SECRETS_DIR = resolve(process.cwd(), '.secrets');

/**
 * Файл с ключом установки: его пишет сервис `local-token`, из него же ключ уезжает
 * в контейнер интерфейса. Тесты читают тот самый файл, который получил образ, — своей
 * копии токена у оснастки больше нет.
 */
export const TOKEN_FILE = resolve(SECRETS_DIR, 'ui-token');

/**
 * Вызов `docker compose`. Файл контура не назван: его берёт сам Docker — из
 * `docker-compose.yml` рядом или из `COMPOSE_FILE`, которым соседние рабочие деревья
 * подсовывают свои теги образов и порты.
 */
export function compose(args: string[], env: Record<string, string> = {}): string {
  return execFileSync('docker', ['compose', ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
    env: { ...process.env, ...env },
  });
}

export function readE2eToken(): string {
  return readFileSync(TOKEN_FILE, 'utf8').trim();
}

/**
 * Установка, которая ключа не выдаёт: `/config.json` отвечает так, как отвечает образ,
 * которому ключа не дали.
 *
 * Нужна сценариям запасного пути — экрана входа. Контур ключ выдаёт всем (иначе
 * продуктовый путь не проверял бы никто), и без этой подмены человек попадал бы сразу
 * на задачи. Подменяется ровно один запрос, а не выдача ключа во всём контуре:
 * ослаблять контур ради одного сценария нельзя (`docs/CONVENTIONS.md`).
 */
export async function installWithoutKey(target: Page | BrowserContext): Promise<void> {
  await target.route('**/config.json', (route) => route.fulfill({ status: 404, body: '' }));
}

/**
 * Установка, где людей несколько, глазами вошедшего: конфигурации с ключом нет, ключ
 * введён руками и лежит в хранилище вкладки.
 *
 * Нужна там, где сценарий проверяет саму кнопку «Выйти»: на локальной установке её нет
 * вовсе — выходить некуда, ключ отдаёт установка (`UI-74`). Это не обход выдачи ключа,
 * а второй из двух путей, и он обязан проверяться так же живьём, как первый.
 */
export async function signedInByHand(page: Page): Promise<void> {
  await installWithoutKey(page);
  await page.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, readE2eToken());
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

/**
 * Боковая панель оболочки: очереди, входящая со счётчиком, участник, состояние потока
 * и выход. До UI-38 всё это стояло в шапке, и тесты искали его в `banner`.
 */
export function side(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Разделы трекера' });
}

/**
 * Ждёт, пока оболочка договорит: участник и счётчик вопросов приходят `bootstrap`ом
 * уже после первой отрисовки. Замер геометрии до этого ведёт мимо.
 *
 * Ссылка ищется по адресу, а не по подписи: подпись счётчика склоняется по числу
 * («вопросов нет», «1 открытый вопрос», «5 открытых вопросов»), и любая её форма
 * в строке ожидания сделала бы готовность оболочки зависящей от того, сколько
 * вопросов в демо-данных.
 */
export async function shellReady(page: Page): Promise<void> {
  await expect(side(page).locator('a[href="/questions"] .sr-only')).toBeVisible();
}

/**
 * Кадр движения, снятый в браузере: чем движение названо, сколько идёт и какой кривой.
 *
 * Разбирается снаружи — внутрь уезжает только чтение вычисленных стилей. Функция
 * уходит в браузер целиком (`locator.evaluate(readFrame)`), поэтому она обязана
 * оставаться без внешних ссылок.
 */
export function readFrame(node: Element): { name: string; duration: string; easing: string } {
  const style = getComputedStyle(node);
  return {
    name: style.animationName,
    duration: style.animationDuration,
    easing: style.animationTimingFunction,
  };
}

/** Длительность в миллисекундах: токен написан в `ms`, вычисленный стиль печатает `s`. */
export function ms(value: string): number {
  const number = Number.parseFloat(value);
  return value.trim().endsWith('ms') ? number : number * 1000;
}

/**
 * Кривая четырьмя числами: сравнивать её строками нельзя. Вычисленный стиль печатает
 * `cubic-bezier(0.2, 0, 0.2, 1)`, а значение токена возвращается таким, каким его
 * оставила сборка, — Lightning CSS срезает ведущий ноль и отдаёт `cubic-bezier(.2,0,.2,1)`.
 */
export function curve(value: string): string {
  return (value.match(/-?\d*\.?\d+/g) ?? []).map(Number).join(',');
}

/**
 * Значения статуса — из контракта соседнего репозитория, а не перечнем в тесте.
 *
 * Перечисление уже менялось дважды (2026-09-05 из него убрали статус, 2026-09-07
 * добавили `waiting`), и тест, выписавший его руками, проверял бы после такой правки
 * не всё: пять форм из шести совпали бы попарно, и шестая осталась бы непроверенной,
 * не уронив ни одного прогона.
 */
export function contractStatuses(): string[] {
  const contract = JSON.parse(
    readFileSync(resolve(process.cwd(), '../tracker/openapi.json'), 'utf8'),
  ) as { components: { schemas: { TaskStatus: { enum: string[] } } } };
  return contract.components.schemas.TaskStatus.enum;
}

/** Сколько дней тишины в деле делают закрытую задачу архивной (UI-97). */
const ARCHIVE_AFTER_DAYS = 3;

/**
 * Что человек видит в списке и на доске по умолчанию: всё, кроме архива — закрытых
 * задач, в делах которых больше трёх дней не писали (UI-97). Закрытая задача без
 * единой записи агента в архиве сразу: в демо это отменённая переходом `DEMO-7`.
 *
 * Правило написано здесь заново, а не взято из кода интерфейса: тест, берущий его
 * оттуда же, откуда его берёт экран, сверял бы экран с самим собой. `now` — часы, от
 * которых считать порог: у браузера со сдвинутыми часами (`page.clock`) он свой.
 */
export function outsideArchive(now: Date = new Date()): string {
  const threshold = new Date(now.getTime() - ARCHIVE_AFTER_DAYS * 24 * 60 * 60 * 1000);
  return `status: not in done, cancelled or last_entry_at: >= "${threshold.toISOString()}"`;
}

/**
 * Какие задачи демо в каком статусе видит человек — по правде бэкенда, а не по памяти
 * теста.
 *
 * Состав демо меняется вместе с бэкендом: 2026-09-07 задача, ждавшая ответа владельца,
 * ушла из `open` в `waiting` (TRK-15), и три сценария, помнившие её ключ и число строк,
 * покраснели разом, ничего не сказав про интерфейс. Спрошенный состав такие правки
 * переживает сам.
 *
 * По умолчанию это состав без архива — ровно то, что список и доска показывают,
 * пока человек не попросил архив (UI-97). `archive: true` — все задачи, как их отдаёт
 * API; `now` — часы, от которых считается порог архива.
 *
 * `params` дописывает условия к отбору: `{ assignee: 'demo_agent' }` отвечает на
 * вопрос «а что из этого его».
 */
export async function tasksByStatus(
  request: APIRequestContext,
  params: Record<string, string> = {},
  { archive = false, now = new Date() }: { archive?: boolean; now?: Date } = {},
): Promise<Map<string, string[]>> {
  const shown: Record<string, string> = archive ? {} : { query: outsideArchive(now) };
  const query = new URLSearchParams({
    queue: 'DEMO',
    fields: 'status',
    limit: '100',
    ...shown,
    ...params,
  });
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, {
    headers: { Authorization: `Bearer ${readE2eToken()}` },
  });
  const body = (await response.json()) as { data: { key: string; status: string }[] };

  const byStatus = new Map<string, string[]>();
  for (const task of body.data) {
    byStatus.set(task.status, [...(byStatus.get(task.status) ?? []), task.key]);
  }
  return byStatus;
}

/**
 * Ключи задач демо, которые видит человек, — все статусы разом. По умолчанию без
 * архива (UI-97): столько строк таблица показывает, открытая без условий.
 */
export async function shownKeys(
  request: APIRequestContext,
  options: { archive?: boolean; now?: Date } = {},
): Promise<string[]> {
  return [...(await tasksByStatus(request, {}, options)).values()].flat();
}
