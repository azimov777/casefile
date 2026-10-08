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
 * Выдача доступа агенту от имени человека — теми же службами, что у бэкенда
 * (`issue_token`, `agent_of`), а не записью в базу: подключение OAuth на экране «Доступы»
 * — строка вида `oauth`, и выдать её из браузера нечем, вход по OAuth идёт через клиента
 * агента и страницу согласия (TRK-450). Контур интерфейса MCP-сервера не поднимает, и
 * сквозной сценарий собирает строку так, как её собрал бы вход, — службой выпуска.
 *
 * Агент берётся по клиенту и хозяину: `claude` и `alice` дают `claude_alice` (TRK-475#14,
 * `agent_of`), тот же путь, которым его заведёт первый вход в сети. Пустой `client` —
 * агент назван явно и уже есть в реестре (`demo_agent`).
 */
const ISSUE_ACCESS = `
import asyncio, sys
from datetime import UTC, datetime, timedelta
from app.db.repositories import ParticipantRepository
from app.db.session import dispose_engine, session_scope
from app.domain.tokens import TokenKind
from app.services import participants
from app.services.auth import Actor
from app.services.tokens import issue_token

async def main(human, kind, client, agent, name):
    async with session_scope() as session:
        issuer = await ParticipantRepository(session).get_by_name(human)
        if client:
            target = await participants.agent_of(session, client=client, owner=issuer)
        else:
            target = await ParticipantRepository(session).get_by_name(agent)
        oauth = kind == 'oauth'
        issued = await issue_token(
            session,
            actor=Actor(author=issuer.author, participant=issuer),
            participant=target,
            name=name,
            kind=TokenKind.OAUTH if oauth else TokenKind.KEY,
            expires_at=datetime.now(UTC) + timedelta(days=30) if oauth else None,
        )
        issued.token.last_used_at = datetime.now(UTC) - timedelta(minutes=5)
    await dispose_engine()

asyncio.run(main(*sys.argv[1:6]))
`;

export interface AccessGrant {
  /** Человек, который выдаёт доступ: он станет «кто выдал» и хозяином агента по клиенту. */
  human: string;
  /** `oauth` — подключение со сроком, `key` — ключ агента. */
  kind: 'oauth' | 'key';
  /** Клиент, по которому берётся агент хозяина (`claude` → `claude_alice`); иначе пусто. */
  client?: string;
  /** Уже заведённый агент, если клиент не назван. */
  agent?: string;
  /** Имя доступа: у подключения — клиент, у ключа — свободная строка. */
  name: string;
}

/** Выдаёт доступ от имени человека. Секрет не печатается и никому не нужен. */
export function grantAccess({ human, kind, client = '', agent = '', name }: AccessGrant): void {
  compose([
    ...['run', '--rm', '--no-deps', 'api'],
    ...['python', '-c', ISSUE_ACCESS, human, kind, client, agent, name],
  ]);
}

/**
 * Снятие связи между задачами. Ручки REST у него нет — интерфейс связей не снимает
 * (TRK#53), — а запись `link_removed` ленте дела нужна: её рождает тот же сервис, что
 * зовёт инструмент MCP `unlink`, и сценарий вызывает его так же, как `grantAccess`.
 */
const REMOVE_LINK = `
import asyncio, sys
from app.db.repositories import ParticipantRepository
from app.db.session import dispose_engine, session_scope
from app.domain.links import LinkKind
from app.services import links, tasks
from app.services.auth import Actor

async def main(human, key, kind, other):
    async with session_scope() as session:
        issuer = await ParticipantRepository(session).get_by_name(human)
        await links.remove_link(
            session,
            await tasks.get_task(session, key),
            await tasks.get_task(session, other),
            actor=Actor(author=issuer.author, participant=issuer),
            kind=LinkKind(kind),
        )
    await dispose_engine()

asyncio.run(main(*sys.argv[1:5]))
`;

/** Снимает связь `kind` задачи `key` с задачей `other` от имени человека. */
export function removeLink(human: string, key: string, kind: string, other: string): void {
  compose([
    ...['run', '--rm', '--no-deps', 'api'],
    ...['python', '-c', REMOVE_LINK, human, key, kind, other],
  ]);
}

/**
 * Прежний вопрос в деле задачи — так его подшивали до обсуждений. Новый вопрос в деле задачи
 * трекер отвергает (`question_not_a_task_entry`, TRK-671: вопросы — в обсуждениях), а
 * прежние лежат в делах установок, и карточка, опись и входящая их по-прежнему показывают.
 * Сценарий заводит такой вопрос той же функцией, что демо, — `file_legacy_task_question`, —
 * как `grantAccess` заводит доступ. Автор — участник по имени или временный агент по метке.
 */
const LEGACY_QUESTION = `
import asyncio, json, sys
from app.db.repositories import ParticipantRepository
from app.db.session import dispose_engine, session_scope
from app.domain.authors import label_author
from app.services import case, tasks
from app.services.auth import Actor

async def main(key, author, title, body, blocking, addressees):
    async with session_scope() as session:
        participant = await ParticipantRepository(session).get_by_name(author)
        actor = (
            Actor(author=participant.author, participant=participant)
            if participant is not None
            else Actor(author=label_author(author), participant=None)
        )
        entry = await case.file_legacy_task_question(
            session,
            await tasks.get_task(session, key),
            actor=actor,
            addressees=json.loads(addressees),
            title=title,
            body=body,
            blocking=blocking == 'true',
        )
        filed = {'no': entry.no, 'seq': entry.seq}
    await dispose_engine()
    print('LEGACY_QUESTION ' + json.dumps(filed))

asyncio.run(main(*sys.argv[1:7]))
`;

export interface LegacyQuestion {
  /** Ключ задачи, в дело которой ложится вопрос. */
  key: string;
  title: string;
  body?: string;
  blocking?: boolean;
  /** Подпись автора: имя участника реестра или метка временного агента. */
  author?: string;
  addressees?: string[];
}

/** Заводит прежний вопрос в деле задачи и отдаёт его номер и место в ленте. */
export function fileLegacyQuestion({
  key,
  title,
  body = '',
  blocking = false,
  author = 'demo_agent',
  addressees = ['owner'],
}: LegacyQuestion): { no: number; seq: number } {
  const output = compose([
    ...['run', '--rm', '--no-deps', 'api'],
    ...['python', '-c', LEGACY_QUESTION, key, author, title, body, String(blocking)],
    JSON.stringify(addressees),
  ]);
  const line = output.split('\n').find((row) => row.startsWith('LEGACY_QUESTION '));
  if (line === undefined) throw new Error(`legacy question not filed: ${output}`);
  return JSON.parse(line.slice('LEGACY_QUESTION '.length)) as { no: number; seq: number };
}

/**
 * Свой открытый прежний вопрос владельцу и способ убрать за собой: его закрывает ответ через
 * REST. Демо открытых вопросов в делах задач не держит (TRK-684: ожидание ответа — вопрос
 * в обсуждении), поэтому сценарию, которому нужна форма ответа на карточке задачи или кромка
 * блокирующего вопроса в истории, вопрос нужен свой. Такие сценарии — пишущие (проект «запись»):
 * читающие идут в двух темах разом и видели бы чужой открытый вопрос.
 */
export async function askLegacyOwner(
  request: APIRequestContext,
  { key, title, body = '', blocking = false }: Omit<LegacyQuestion, 'author' | 'addressees'>,
): Promise<{ no: number; cleanup: () => Promise<void> }> {
  const { no } = fileLegacyQuestion({ key, title, body, blocking, author: 'owner' });
  return {
    no,
    cleanup: async () => {
      const closed = await request.post(`/api/v1/tasks/${key}/entries`, {
        headers: { Authorization: `Bearer ${readE2eToken()}` },
        data: {
          type: 'answer',
          body: 'Закрыт сквозным тестом, чтобы входящая осталась какой была.',
          payload: { question_no: no },
        },
      });
      expect(closed.status()).toBe(201);
    },
  };
}

/**
 * Файл с ключом агента для запасного пути — входа на `/login`. Выпускается отдельно от
 * ключа установки (`e2e/global-setup.ts`): наборов у ключей больше нет (TRK-471), а
 * сценарию, проверяющему экран глазами агента, нужен именно ключ агента без учётной
 * записи — «человеческого» ключа, кроме `local-ui`, не существует (TRK-472).
 */
export const AGENT_KEY_FILE = resolve(SECRETS_DIR, 'agent-key');

export function readAgentKey(): string {
  return readFileSync(AGENT_KEY_FILE, 'utf8').trim();
}

/**
 * Пароль администратора контура: его хеш стоит в `TRACKER_PASSWORD_HASH` бэкенда
 * (`docker-compose.yml`), и шаг `local-token` переносит его в учётную запись
 * `E2E_EMAIL` (`TRK-113`). Учебный, как и весь контур.
 */
export const E2E_PASSWORD = 'e2e contour password';

/**
 * Почта администратора контура: учётную запись `owner@localhost` установка заводит себе
 * сама, и пароль переносом получает именно она.
 */
export const E2E_EMAIL = 'owner@localhost';

/**
 * Порт второго экземпляра интерфейса — той же службы `ui`, поднятой одноразовым
 * контейнером в режиме входа по учётным записям (`global-setup.ts`). Свой порт, а не свой адрес на том же:
 * режим задаётся контейнеру при старте, и в одном nginx двух режимов нет.
 */
export const LOGIN_PORT = process.env.UI_LOGIN_PORT ?? '8082';

/** Адрес установки в режиме входа: тот же бэкенд, другой режим интерфейса. */
export const LOGIN_URL = `http://localhost:${LOGIN_PORT}`;

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
 * Боковая панель оболочки: проекты, входящая со счётчиком, участник, состояние потока
 * и выход. До UI-38 всё это стояло в шапке, и тесты искали его в `banner`.
 */
export function side(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Разделы Casefile' });
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
  // `.first()`: подписей счётчика две, когда ждут и вопросы, и обсуждения (TRK-672).
  await expect(side(page).locator('a[href="/questions"] .sr-only').first()).toBeVisible();
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
 * Значения статуса — из контракта бэкенда, а не перечнем в тесте.
 *
 * Перечисление уже менялось трижды (2026-09-05 из него убрали `review`, 2026-09-07
 * добавили `waiting`, 2026-10-06 его сняли, TRK-573), и тест, выписавший его руками,
 * проверял бы после такой правки не всё: формы совпали бы попарно, и одна осталась бы
 * непроверенной, не уронив ни одного прогона.
 */
export function contractStatuses(): string[] {
  const contract = JSON.parse(readFileSync(resolve(process.cwd(), '../openapi.json'), 'utf8')) as {
    components: { schemas: { TaskStatus: { enum: string[] } } };
  };
  return contract.components.schemas.TaskStatus.enum;
}

/**
 * Столбцы доски слева направо: статусы контракта и «Ждёт ответа» (ключ `waiting`) сразу
 * за `in_progress`. Статуса ожидания у бэкенда нет (TRK-573) — столбец вычисляется из
 * вопросов `blocking` (`boardColumn`), — поэтому в перечислении статуса его и нет.
 * Правило выписано здесь заново, а не взято из кода интерфейса.
 */
export function boardColumns(): string[] {
  const statuses = contractStatuses();
  const after = statuses.indexOf('in_progress') + 1;
  return [...statuses.slice(0, after), 'waiting', ...statuses.slice(after)];
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
  // Задача с открытым предупреждением в архив не уходит (TRK-561#9).
  return `status: not in done, cancelled or last_entry_at: >= "${threshold.toISOString()}" or open_warnings: > 0`;
}

/**
 * В каком столбце доски стоит задача (TRK-571, TRK#177): «Ждёт ответа»
 * (ключ `waiting`) — задача из работы с открытым вопросом `blocking`; остальные — в
 * столбце своего статуса. Правило выписано здесь заново, а не взято из кода интерфейса.
 */
export function boardColumn(status: string, openBlockingQuestions: number): string {
  const held = ['backlog', 'open', 'in_progress'].includes(status);
  return held && openBlockingQuestions > 0 ? 'waiting' : status;
}

/**
 * Какие задачи демо в каком столбце доски видит человек — по правде бэкенда, а не по памяти
 * теста.
 *
 * Ключ — столбец (`boardColumn`), он же статус везде, кроме «Ждёт ответа».
 *
 * Состав демо меняется вместе с бэкендом: 2026-09-07 задача, ждавшая ответа владельца,
 * ушла из `open` в статус ожидания (TRK-15), а 2026-10-06 вернулась в `open` с вопросом
 * `blocking` (TRK-573), и сценарии, помнившие её ключ и число строк, краснели разом,
 * ничего не сказав про интерфейс. Спрошенный состав такие правки переживает сам.
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
    project: 'DEMO',
    fields: 'status,features',
    limit: '100',
    ...shown,
    ...params,
  });
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, {
    headers: { Authorization: `Bearer ${readE2eToken()}` },
  });
  const body = (await response.json()) as {
    data: { key: string; status: string; features: { open_blocking_questions: number } }[];
  };

  const byStatus = new Map<string, string[]>();
  for (const task of body.data) {
    const shown = boardColumn(task.status, task.features.open_blocking_questions);
    byStatus.set(shown, [...(byStatus.get(shown) ?? []), task.key]);
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

/**
 * Ждёт покоя движения на узле — не первого `finished`, а раунда, после которого
 * работающих анимаций не осталось (`UI-102`).
 *
 * `Promise.all(node.getAnimations({ subtree: true }).map((a) => a.finished))` падает
 * там, где под неподвижным указателем едет что-то с переходом по наведению: элемент
 * проезжает под указателем, наведение начинается и снимается тем же кадром, отменённый
 * переход отклоняет `finished` `AbortError`, и `Promise.all` роняет всё ожидание —
 * законную гонку, а не дефект интерфейса. Отмена к тому же чаще всего запускает
 * встречный переход тем же кадром (цвет едет назад), и его тоже нужно дождаться —
 * поэтому одного `allSettled` мало, нужен раунд за раундом, пока список работающих
 * анимаций не станет пуст. Потолок раундов не проверка, а сторож самого ожидания:
 * настоящий бесконечный цикл (не эта гонка, а сломанное движение) должен упасть
 * с понятной причиной, а не висеть до общего таймаута сценария.
 */
export async function motionSettled(node: Locator): Promise<void> {
  await node.evaluate(async (element) => {
    const ROUNDS = 20;
    for (let round = 0; round < ROUNDS; round += 1) {
      const animations = element.getAnimations({ subtree: true });
      await Promise.allSettled(animations.map((animation) => animation.finished));
      const stillRunning = element
        .getAnimations({ subtree: true })
        .some((animation) => animation.playState === 'running');
      if (!stillRunning) return;
    }
    throw new Error(`движение на узле не улеглось за ${ROUNDS} раундов ожидания`);
  });
}

/**
 * Ждёт, пока геометрия узла не перестанет меняться — не «шрифт готов», а «место,
 * куда сейчас метит клик, больше не сдвинется» (`UI-139`).
 *
 * `document.fonts.ready`, взятый один раз, ловит только те шрифты, о которых
 * браузер уже знает на момент вызова. Вторая подшрифтовка Fira Code (кириллический
 * диапазон одного `@font-face`) грузится лениво — только когда что-то с ней впервые
 * попадает в перекраску, — и это может случиться уже после того, как `fonts.ready`
 * разрешился: замерено, что запрос второго файла шрифта стартует во время самого
 * `click()`, спустя ~130 мс после того, как `fontsReady` уже отработал. Раскладка
 * при этом переезжает несколькими раундами подряд (`scroll y=` прыгало 228 → 312 →
 * 380 → 435 → 45 → 81 в пределах одного клика — замер собственным слушателем `click`
 * на странице, трасса Playwright по какому узлу пришёлся настоящий клик не говорит),
 * и клик, попавший в целевую точку до того, как она легла, промахивается мимо
 * переехавшей ссылки: адрес остаётся прежним, будто нажатия не было.
 *
 * Поэтому ждать нужно не событие (шрифт, анимация — их можно не знать заранее), а
 * сам факт: положение и размер узла не изменились между двумя последовательными
 * снимками. Приём тот же, что и у `motionSettled` — раунд за раундом, с потолком:
 * настоящее зависание (узел никогда не остановится) обязано упасть с понятной
 * причиной, а не висеть до общего таймаута сценария.
 */
export async function layoutSettled(node: Locator): Promise<void> {
  const ROUNDS = 20;
  const DELAY_MS = 100;
  let previous: { x: number; y: number; width: number; height: number } | null = null;

  for (let round = 0; round < ROUNDS; round += 1) {
    const box = await node.boundingBox();
    if (
      box !== null &&
      previous !== null &&
      box.x === previous.x &&
      box.y === previous.y &&
      box.width === previous.width &&
      box.height === previous.height
    ) {
      return;
    }
    previous = box;
    await node.page().waitForTimeout(DELAY_MS);
  }
  throw new Error(`раскладка узла не улеглась за ${ROUNDS} раундов ожидания`);
}
