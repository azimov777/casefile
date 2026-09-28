import { http } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  projectDetail,
  taskDetails,
  taskPackage,
  taskPage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { setToken } from '@/shared/api';
import { HINT_KEYS } from '@/features/manage-onboarding';
import { dictionaries } from '@/shared/i18n';

/**
 * Пояснения семи экранов (TRK-363): тексты дословно из задания, ключи из общего
 * перечня, скрытие по одному и все разом. Приложение поднимается целиком, поэтому тест
 * лежит в `app`, а не в одной из страниц: он сверяет их разом.
 *
 * Страницы читаются по обычному адресу, без лишних параметров, — так их открывает
 * новый человек (учётная запись с `hidden_all: false` и пустым `hidden`).
 */

interface Screen {
  name: string;
  path: string;
  key: string;
  ru: string;
  en: string;
}

const SCREENS: Screen[] = [
  {
    name: 'список задач',
    path: '/tasks',
    key: HINT_KEYS.tasks,
    ru: 'Здесь все задачи, которые ведут агенты. Заводят и двигают их агенты, вы смотрите, где что стоит. Значки в строке показывают открытые вопросы, замечания и блокировки.',
    en: 'All tasks that agents carry are here. Agents create and move them; you watch where things stand. Marks in a row show open questions, remarks and blockers.',
  },
  {
    name: 'доска',
    path: '/tasks?view=board',
    key: HINT_KEYS.board,
    ru: 'Те же задачи одного проекта по шести столбцам статусов. Карточки двигают агенты; перетащить карточку нельзя. В столбце waiting стоят задачи, где следующий ход за вами или за внешним событием.',
    en: 'The same tasks of one project in six status columns. Agents move the cards; a card cannot be dragged. The waiting column holds tasks where the next move is yours or depends on an outside event.',
  },
  {
    name: 'карточка задачи',
    path: '/tasks/DEMO-7',
    key: HINT_KEYS.task,
    ru: 'Это задание агенту и то, что по нему сделано: последняя сводка, открытые вопросы и опись дела. Здесь вы отвечаете на вопрос агента и оставляете замечание, если вышло не то. Само задание правит только агент.',
    en: "This is the assignment for the agent and what has been done on it: the latest summary, open questions and the case index. Here you answer the agent's question and leave a remark when the result came out wrong. Only the agent edits the assignment itself.",
  },
  {
    name: 'дело',
    path: '/tasks/DEMO-7/case',
    key: HINT_KEYS.case,
    ru: 'Дело — журнал задачи: решения, попытки, находки, вопросы и ответы. Записи не правятся и не удаляются; ошибку исправляет следующая запись. По делу следующий агент продолжает работу, не начиная заново.',
    en: "The case is the task's log: decisions, attempts, findings, questions and answers. Entries are never edited or deleted; a mistake is corrected by the next entry. The next agent continues from the case instead of starting over.",
  },
  {
    name: 'проект',
    path: '/projects/DEMO',
    key: HINT_KEYS.project,
    ru: 'Проект отвечает на вопрос «про что задачи». Здесь вы правите его описание, ведёте атрибуты — где лежит код, какая ветка главная — и пишете заметки в дело проекта. Описание агент получает вместе с каждой задачей проекта.',
    en: "A project answers “what are the tasks about”. Here you edit its description, keep its attributes — where the code lives, which branch is the main one — and write notes to the project's case. The agent receives the description with every task of the project.",
  },
  {
    name: 'подключить агента',
    path: '/connect',
    key: HINT_KEYS.connect,
    ru: 'Агент работает с Casefile через MCP: ему нужны адрес этой установки и токен. После подключения скажите агенту, с чего начать, — фразы есть на экране «Начало».',
    en: "An agent works with Casefile over MCP: it needs this installation's address and a token. Once connected, tell the agent where to start — the phrases are on the Start screen.",
  },
  {
    name: 'доступы',
    path: '/access',
    key: HINT_KEYS.access,
    ru: 'Здесь все токены установки: кому выданы и когда ими ходили в последний раз. Отдельному агенту стоит выпустить свой токен — тогда его записи подписаны его именем. Лишний токен отзывается здесь же.',
    en: 'All tokens of the installation are here: who holds them and when they were last used. A separate agent deserves its own token — then its entries are signed with its name. A token you no longer need is revoked here.',
  },
];

type Hints = { hidden_all: boolean; hidden: string[] };

function account(hints: Hints) {
  return {
    id: '55555555-5555-5555-5555-555555555555',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin: true,
    has_password: false,
    disabled_at: null,
    onboarding: { status: 'completed' as const, hints },
    created_by: { kind: 'tracker' as const, signature: null },
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
  };
}

/** Установка с пустыми списками на всех экранах и своим состоянием пояснений. */
function installation(hints: Hints, archived: string | null = null) {
  const base = taskPackage('DEMO-7');
  const details = taskDetails('DEMO-7');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(hints) }))),
    http.get(`${API}/api/v1/tasks`, () => taskPage([])),
    http.get(`${API}/api/v1/tasks/DEMO-7`, () =>
      data({
        ...base,
        task: { ...details, project: { ...details.project, archived_at: archived } },
      }),
    ),
    http.get(`${API}/api/v1/tasks/DEMO-7/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO`, () =>
      data(projectDetail('DEMO', { archived_at: archived })),
    ),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/tokens`, () => collection([])),
    http.get(`${API}/api/v1/participants`, () => collection([])),
    http.get(`${API}/api/v1/installation`, () => data({ mcp_url: 'http://localhost:8100/mcp' })),
  );
}

/** Абзац пояснения в области содержимого: его полный текст, ссылки внутри не мешают. */
function explanation(text: string) {
  const main = screen.getByRole('main');
  return within(main).queryByText(
    (_, element) => element?.tagName === 'P' && element.textContent === text,
  );
}

async function shown(text: string) {
  await waitFor(() => expect(explanation(text)).toBeInTheDocument());
}

/** Экран дорисован до конца, чтобы «нет пояснения» не было «ещё не пришло». */
const READY: Record<string, string | RegExp> = {
  '/tasks': 'Tasks',
  '/tasks?view=board': 'Tasks',
  '/tasks/DEMO-7': taskDetails('DEMO-7').title,
  '/tasks/DEMO-7/case': 'DEMO-7',
  '/projects/DEMO': 'DEMO',
  '/connect': 'Connect an agent',
  '/access': 'Access',
};

async function drawn(path: string) {
  await screen.findByRole('heading', { level: 1, name: new RegExp(String(READY[path])) });
  // Дать первому кадру и запросам экрана дойти до конца.
  await waitFor(() => expect(screen.queryByText(/Loading|Загружаем/)).not.toBeInTheDocument());
}

beforeEach(() => {
  setToken('trk_test');
});

describe('пояснения экранов: путь нового человека', () => {
  it.each(SCREENS)('$name: пояснение видно по обычному адресу, ru', async ({ path, ru }) => {
    installation({ hidden_all: false, hidden: [] });
    renderApp(path, { language: 'ru' });
    await shown(ru);
  });

  it.each(SCREENS)('$name: пояснение видно по обычному адресу, en', async ({ path, en }) => {
    installation({ hidden_all: false, hidden: [] });
    renderApp(path, { language: 'en' });
    await shown(en);
  });

  it.each(SCREENS)('$name: пояснение — первый блок области содержимого', async ({ path, en }) => {
    installation({ hidden_all: false, hidden: [] });
    renderApp(path, { language: 'en' });
    await shown(en);
    const main = screen.getByRole('main');
    expect(main.firstElementChild).toBe(explanation(en)?.closest('div'));
  });

  it('ссылка «Начало» в пояснении подключения ведёт на /start', async () => {
    installation({ hidden_all: false, hidden: [] });
    renderApp('/connect', { language: 'ru' });
    await shown(SCREENS[5]!.ru);
    const link = within(explanation(SCREENS[5]!.ru)!).getByRole('link', { name: 'Начало' });
    expect(link).toHaveAttribute('href', '/start');
  });
});

describe('пояснения экранов: скрыто', () => {
  it.each(SCREENS)('$name: при hidden_all пояснения в содержимом нет', async ({ path, en }) => {
    installation({ hidden_all: true, hidden: [] });
    renderApp(path, { language: 'en' });
    await drawn(path);
    expect(explanation(en)).not.toBeInTheDocument();
  });

  it.each(SCREENS)('$name: со своим ключом в hidden пояснения в содержимом нет', async (item) => {
    installation({ hidden_all: false, hidden: [item.key] });
    renderApp(item.path, { language: 'en' });
    await drawn(item.path);
    expect(explanation(item.en)).not.toBeInTheDocument();
  });
});

describe('список и доска — два пояснения', () => {
  const [list, board] = SCREENS as [Screen, Screen];

  it('ключ tasks в hidden убирает пояснение списка и оставляет пояснение доски', async () => {
    installation({ hidden_all: false, hidden: [HINT_KEYS.tasks] });
    renderApp(list.path, { language: 'en' });
    await drawn(list.path);
    expect(explanation(list.en)).not.toBeInTheDocument();
    expect(explanation(board.en)).not.toBeInTheDocument();
  });

  it('то же состояние на доске: пояснение доски видно', async () => {
    installation({ hidden_all: false, hidden: [HINT_KEYS.tasks] });
    renderApp(board.path, { language: 'en' });
    await shown(board.en);
    expect(explanation(list.en)).not.toBeInTheDocument();
  });

  it('ключ board в hidden убирает пояснение доски и оставляет пояснение списка', async () => {
    installation({ hidden_all: false, hidden: [HINT_KEYS.board] });
    renderApp(list.path, { language: 'en' });
    await shown(list.en);
  });
});

describe('архивный проект: пояснений карточки, дела и проекта нет', () => {
  it.each(SCREENS.filter((item) => ['task', 'case', 'project'].includes(item.key)))(
    '$name',
    async ({ path, en }) => {
      installation({ hidden_all: false, hidden: [] }, '2026-09-20T10:00:00Z');
      renderApp(path, { language: 'en' });
      await drawn(path);
      expect(explanation(en)).not.toBeInTheDocument();
    },
  );
});

describe('словари пояснений', () => {
  function sentences(text: string): number {
    return text
      .replace(/<[^>]+>/g, '')
      .split(/(?<=[.!?])\s+(?=[A-ZА-ЯЁ«"])/u)
      .filter((part) => part.trim() !== '').length;
  }

  const texts = (lang: 'en' | 'ru') => {
    const d = dictionaries[lang] as Record<string, { explanation?: Record<string, string> }>;
    return {
      tasks: d.tasks?.explanation,
      task: d.task?.explanation,
      case: d.case?.explanation,
      project: d.project?.explanation,
      connect: d.connect?.explanation,
      access: d.access?.explanation,
      questions: d.questions?.explanation,
    };
  };

  it.each(['en', 'ru'] as const)(
    'на каждый ключ перечня есть текст, не длиннее трёх предложений (%s)',
    (lang) => {
      const found = texts(lang);
      const bodies = [
        found.questions?.body,
        found.tasks?.list,
        found.tasks?.board,
        found.task?.body,
        found.case?.body,
        found.project?.body,
        found.connect?.body,
        found.access?.body,
      ];
      // Ключей в перечне столько же, сколько текстов: новый ключ без текста роняет тест.
      expect(bodies).toHaveLength(Object.keys(HINT_KEYS).length);
      for (const body of bodies) {
        expect(typeof body).toBe('string');
        expect(sentences(body as string)).toBeLessThanOrEqual(3);
      }
    },
  );
});
