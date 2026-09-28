/**
 * Экран «Подключить агента»: откуда взять токен, фрагменты под клиенты, третий шаг —
 * что сказать агенту дальше, фраза о дисциплине.
 *
 * Подписи самих фрагментов живут в `ui.snippets`: их показывает и экран «Доступы». Сами
 * фразы третьего шага (`tellAgent`) читаются из словаря `start` теми же ключами, что
 * экран «Начало» (`TRK-367`); здесь своей копии у них нет — только заголовок шага.
 * Имена из кода (`{{placeholder}}`, `{{header}}`) приходят значениями из констант
 * `features/connect-agent`: перевод их не повторяет.
 */
export const connect = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    body: "An agent works with Casefile over MCP: it needs this installation's address and a token. Once connected, tell the agent where to start — the phrases are on the <start>Start</start> screen.",
  },
  intro:
    'An agent works with Casefile over MCP: the address of this installation and a token in the <code>Authorization</code> header. Two steps, and the agent keeps its tasks in the tracker.',
  steps: 'Connection steps',
  token: {
    title: 'Get a token',
    thisMachine:
      'The agent of this machine connects with the token of the <code>agent</code> participant: the installation issues it by itself and keeps it in a file. Run the command in the installation directory, next to its <code>docker-compose.yml</code>.',
    commandLabel: 'Command that reads the agent token',
    commandCaption: 'Terminal, in the installation directory',
    terminalOnly:
      'The command prints the token to your terminal only. Do not paste the token into a chat.',
    otherTitle: 'Need a different token?',
    ownToken:
      'A separate agent gets a token of its own: then its entries in cases are signed with its name rather than the shared <code>agent</code>. Such a token is issued by the <access>Access</access> screen — on a local installation there is nothing to enter for that.',
    sharedToken:
      'A token issued without a participant is a shared agent token: every action taken with it is signed by the <code>{{header}}</code> header. For such a token, tick the box in the next step.',
  },
  snippets: {
    title: 'Paste the fragment into your client',
    intro:
      'Pick your client and copy the fragment. Put the token from the first step in place of <code>{{placeholder}}</code>.',
    shared: 'Shared agent token: add <code>{{header}}</code>',
    loading: 'Reading the MCP address…',
  },
  tellAgent: {
    title: 'Tell the agent where to start',
    more: 'These same phrases, with copy buttons, are also on the <start>Start</start> page.',
  },
  discipline:
    'The agent gets the tracker rules from the server itself when it connects — there is nothing to install for them.',
} as const;
