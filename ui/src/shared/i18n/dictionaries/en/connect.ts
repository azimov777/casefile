/**
 * Экран «Подключить агента»: откуда взять токен, фрагменты под клиенты, скил дисциплины.
 *
 * Подписи самих фрагментов живут в `ui.snippets`: их показывает и экран «Доступы».
 * Имена из кода (`{{placeholder}}`, `{{header}}`) приходят значениями из констант
 * `features/connect-agent`: перевод их не повторяет.
 */
export const connect = {
  intro:
    'An agent works with Casefile over MCP: the address of this installation and a token in the <code>Authorization</code> header. Three steps, and the agent keeps its tasks in the tracker.',
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
  skill: {
    title: 'Install the discipline skill',
    optional: 'optional',
    fromServer:
      'The server hands the gist of the discipline to the client by itself when it connects, in the MCP instructions, and the full text as the <code>tracker-discipline</code> prompt. To keep the skill in the harness for good, put it in as a file. Claude Code: run this command in the installation directory.',
    commandBashLabel: 'Command that installs the skill for Claude Code (bash/zsh)',
    commandBashCaption: 'Terminal, in the installation directory',
    commandPowerShellLabel: 'Command that installs the skill for Claude Code (PowerShell)',
    commandPowerShellCaption: 'PowerShell, in the installation directory',
    otherAgents:
      'Other agents: the same file goes wherever their harness keeps skills or instructions.',
  },
} as const;
