import type { components } from '@/shared/api';

type EntryType = components['schemas']['EntryType'];
type RemarkOutcome = components['schemas']['RemarkOutcome'];
type LinkKind = components['schemas']['LinkKind'];

/**
 * Подписи кирпичей интерфейса: то, что говорит не экран, а сам механизм, — и потому
 * не принадлежит ни одному экрану.
 *
 * Здесь оболочка (`app/layouts`, `app/providers`), кирпичи `shared/ui`, представление
 * задачи и записи (`entities`) и те действия, что живут не на одном экране: ответ
 * на вопрос, замечание, живой поток. Подписи, принадлежащие одному экрану, лежат
 * в его пространстве — `tasks`, `task`, `case`, `questions`.
 *
 * Наборы значений контракта перечислены `satisfies Record<…>`: значение, добавленное
 * на бэкенде, роняет сборку здесь, а не остаётся на экране без подписи.
 */
export const ui = {
  language: 'Interface language',
  error: {
    unknown: 'Unknown error.',
    unknownCode: 'Unknown error ({{code}}).',
    // Фраза бэкенда, которую нечем заменить: код называется рядом, чтобы человеку
    // было что процитировать в задаче.
    withCode: '{{message}} ({{code}})',
  },

  /**
   * Время для человека. Обо всём остальном во времени говорит `Intl` на языке
   * интерфейса (`shared/lib/locale/time.ts`); словами сказана одна ступень — та, которой
   * в `Intl.RelativeTimeFormat` нет вовсе.
   */
  time: {
    justNow: 'just now',
  },

  /** Оболочка: боковая панель, верхняя полоса, границы ошибок и несуществующий адрес. */
  app: {
    // Буква значка — первая буква названия, а не сокращение слова: рядом с ней стоит само
    // название, и разойтись они не должны. Название — имя продукта и не переводится.
    mark: 'C',
    name: 'Casefile',
    sections: 'Sections',
    trackerSections: 'Casefile sections',
    closeSections: 'Close sections',
    // Нулевая форма — обычная подпись кнопки: спрашивать не о чем, и говорить не о чем.
    showSections_zero: 'Show sections',
    showSections_one: 'Show sections, {{count, number}} question waiting',
    showSections_other: 'Show sections, {{count, number}} questions waiting',
    queues: 'Queues',
    allTasks: 'All tasks',
    mine: 'Mine',
    inbox: 'Inbox',
    // Группа панели про саму установку, а не про работу в очередях: подключение
    // агента и доступы касаются установки целиком.
    installation: 'Installation',
    connect: 'Connect an agent',
    access: 'Access',
    openQuestions_zero: 'No open questions',
    openQuestions_one: '{{count, number}} open question',
    openQuestions_other: '{{count, number}} open questions',
    loadingParticipant: 'Loading the participant…',
    noParticipant: 'no participant',
    signOut: 'Sign out',
    whereAmI: 'Where I am',
    crumbTasks: 'Tasks',
    crumbCase: 'Case',
    broken: {
      title: 'The interface broke right here',
      text: 'The screen did not render because of a bug in the interface itself — the data has nothing to do with it. The details are in the browser console.',
      reload: 'Reload',
    },
    notFound: {
      title: 'Page not found',
      text: 'There is no such address in the interface.',
    },
  },

  /** Состояние запроса вместо данных (`shared/ui`, `QueryState`). */
  query: {
    retry: 'Try again',
    retrying: 'Trying…',
  },

  /** Форма записи в дело и подтверждение под ней (`shared/ui`). */
  composer: {
    preview: 'Preview',
    hidePreview: 'Hide preview',
    agentView: 'This is what the agent will see',
  },
  receipt: {
    close: 'Close',
  },

  /**
   * Текст для копирования (`shared/ui`, `CopyBlock`). Имя кнопки содержит её видимую
   * подпись целиком: голосовое управление находит кнопку по тому, что на ней написано.
   */
  copyBlock: {
    action: 'Copy',
    copied: 'Copied',
    label: 'Copy: {{label}}',
    copiedLabel: 'Copied: {{label}}',
    done: '{{label}} is in the clipboard',
    failed:
      'The browser did not give access to the clipboard: select the text and copy it by hand.',
  },

  /**
   * Представление доступа: строка списка на экране «Доступы» (`entities/token`).
   * Подписи самого экрана — в пространстве `access`, здесь только то, чем строка
   * называет себя и свои поля.
   */
  token: {
    label: 'Access {{name}}',
    scopeKind: 'scope',
    scopeTask: 'The working cycle of an agent: tasks, case entries, and reading everything.',
    scopeMain: 'The working cycle plus writing to the registries: participants, tokens and queues.',
    thisSession: 'key of this session',
    revoked: 'revoked',
    shared: 'shared agent token',
    issuedBy: 'issued by {{author}}',
    issuedByTracker: 'issued by the installation itself',
    lastUsed: 'last used',
    neverUsed: 'never used yet',
    revokedAt: 'revocation:',
  },

  /** Представление задачи: строка списка, карточка доски, знаки и навигация. */
  task: {
    columns: {
      key: 'Key',
      title: 'Title',
      status: 'Status',
      assignee: 'Assignee',
      priority: 'Priority',
      features: 'Features',
      activity: 'Activity',
    },
    // Знак называет себя программе чтения с экрана: без этого она читает голое
    // `in_progress`, не сказав, что это статус.
    statusLabel: 'status',
    priorityLabel: 'priority',
    emptyCase: 'case is empty',
    cardUnassigned: 'not assigned',
    features: {
      blocked: 'blocked: there is a blocked_by link to an unclosed task',
      questions_one: '{{count, number}} question without an answer',
      questions_other: '{{count, number}} questions without an answer',
      // Два числа в одной фразе: второе приходит уже собранной фразой (`blockingOf`),
      // потому что склонять его надо отдельно от первого.
      questionsBlocking_one: '{{count, number}} question without an answer, {{blocking}}',
      questionsBlocking_other: '{{count, number}} questions without an answer, {{blocking}}',
      blockingOf_one: '{{count, number}} of them blocking',
      blockingOf_other: '{{count, number}} of them blocking',
      remarks_one: '{{count, number}} remark not yet resolved',
      remarks_other: '{{count, number}} remarks not yet resolved',
    },
    // Родитель задачи подписью на карточке доски и в строке списка (UI-119).
    parents: {
      label: 'parent',
      caption: '<key>{{key}}</key> · {{title}}',
      item: '{{key}} · {{title}}',
      more: '+{{count, number}}',
      others_one: 'and {{count, number}} more parent: {{parents, list}}',
      others_other: 'and {{count, number}} more parents: {{parents, list}}',
    },
    // Заголовок группы связей одного вида (UI-125): подпись рядом с идентификатором
    // контракта, а не вместо него — сам идентификатор `LinkKindMark` не переводит.
    links: {
      kind: {
        blocked_by: 'Blocked by',
        blocks: 'Blocks',
        parent: 'Parent',
        child: 'Children',
        relates: 'Related',
      } satisfies Record<LinkKind, string>,
    },
    nav: {
      label: 'Navigation for task {{key}}',
      view: 'Task view',
      backAll: '← To all tasks',
      backFiltered: '← To the filtered list',
      card: 'Card',
      case: 'Case',
    },
  },

  /** Представление записи дела: род, заголовок по фактам и тело. */
  entry: {
    // Подпись самого трекера: у человека и агента здесь стоит имя участника.
    tracker: 'tracker',
    type: {
      summary: 'summary',
      decision: 'decision',
      attempt: 'attempt',
      finding: 'finding',
      artifact: 'artifact',
      question: 'question',
      answer: 'answer',
      verdict: 'verdict',
      remark: 'remark',
      resolution: 'resolution',
      note: 'note',
      created: 'created',
      status_changed: 'status change',
      section_changed: 'section edit',
      field_changed: 'field edit',
      assignee_changed: 'assignee change',
      link_added: 'link added',
      link_removed: 'link removed',
    } satisfies Record<EntryType, string>,
    // Исход разбора замечания — словами, а не идентификатором контракта: замечание
    // оставляет человек, и это единственный ответ, которого он ждал.
    remarkOutcome: {
      fixed: 'fixed',
      accepted: 'taken into work',
      needs_detail: 'needs detail',
      declined: 'will not change',
    } satisfies Record<RemarkOutcome, string>,
    headline: {
      created: 'Task created',
      status: 'Status',
      withReason: '· with a reason',
      sectionEdited: 'Section edit',
      fieldEdited: 'Field edit',
      assignee: 'Assignee',
      linkAdded: 'Link',
      linkRemoved: 'Link removed',
      answerTo: 'Answer to',
      check: 'Review check {{no}}',
      resolution: 'Resolution of',
      resolutionOutcome: '· {{outcome}}',
      /** Пара «было → стало»: отсутствие значения называется словом, а не пустотой. */
      none: 'not set',
      cleared: 'cleared',
    },
    summary: {
      done: 'Done',
      remaining: 'Remaining',
      blockers: 'Blockers',
      nextStep: 'Next step',
      unmeasured: 'What the checks did not measure',
    },
    addressees: 'Asked of:',
    blocking: 'blocking',
    was: 'Before',
    now: 'After',
    noBody: 'This entry has no body.',
    refs: 'Pointers:',
    emptyValue: 'empty',
    copy: 'Copy {{reference}}',
    copied: 'copied',
    clipboardUnavailable: 'clipboard unavailable',
  },

  /** Живой поток: состояние связи, полоса обновлений и уведомление о вопросе. */
  live: {
    connecting: 'connecting',
    connectingTitle: 'Opening the live journal stream',
    online: 'live',
    onlineTitle: 'The live journal stream is open: the screen updates itself',
    offline: 'no connection',
    offlineTitle: 'The connection to the journal stream is lost, reconnecting',
    updates: 'List updates',
    changed_one: '{{count, number}} task changed',
    changed_other: '{{count, number}} tasks changed',
    changedUnknown: 'There was no connection for a while, the list may have changed',
    show: 'Show',
    questionsToMe: 'Questions for me',
    blockingBadge: 'blocking',
    blockingTitle: 'Work on the task is stalled without an answer',
    dismiss: 'Dismiss the notice about question {{reference}}',
  },

  /** Ответ на вопрос: форма живёт и на карточке задачи, и во входящей. */
  answer: {
    formLabel: 'Answer to {{reference}}',
    fieldLabel: 'Answer',
    submit: 'Answer',
    pending: 'Sending…',
    open: 'Answer',
    empty: 'An empty answer cannot be sent: the agent needs text, not the fact of a click.',
    placeholder: 'Markdown. References such as DEMO-2 and DEMO-2#7 turn into links.',
    retrySafe:
      'Sending it again will not file a second answer: the attempt keeps the same idempotency key.',
    receiptLabel: 'The answer to {{reference}} is filed',
    receiptHeadline: 'Answer filed',
  },

  /** Замечание к задаче: «вышло не то» о задаче целиком. */
  remark: {
    formLabel: 'Remark on {{key}}',
    fieldLabel: 'Remark',
    submit: 'Leave a remark',
    pending: 'Sending…',
    empty: 'An empty remark cannot be sent: the agent needs to know what exactly went wrong.',
    placeholder:
      'What came out wrong. Markdown; references such as DEMO-2 and DEMO-2#7 turn into links.',
    retrySafe:
      'Sending it again will not file a second remark: the attempt keeps the same idempotency key.',
    receiptLabel: 'The remark on {{key}} is filed',
    receiptHeadline: 'Remark filed',
  },

  /**
   * Фрагменты подключения агента к MCP (`features/connect-agent`): их показывают два
   * экрана — «Подключить агента» и «Доступы», поэтому подписи живут здесь, а не в
   * пространстве одного из них.
   *
   * Имена из кода — заголовок метки, подстановки, имя сервера, переменная окружения —
   * приходят значениями (`{{header}}`, `{{placeholder}}`, `{{server}}`, `{{env}}`) из
   * констант среза: перевод их не повторяет, и расходиться имени во фразе с именем во
   * фрагменте негде. Названия клиентов — имена продуктов и не переводятся.
   */
  snippets: {
    clients: {
      any: 'Any MCP client',
      claudeCode: 'Claude Code',
      codex: 'Codex',
      json: 'JSON mcpServers',
    },
    labelHint:
      'A shared agent token names nobody, so every request with it carries the <code>{{header}}</code> header: the signature of a temporary agent in case entries. Replace <code>{{placeholder}}</code> with a label in latin snake_case, for example <code>nightly_agent</code>.',
    anyHint:
      'Transport: streamable HTTP. The address is set by the installation; the headers go with every request.',
    addressLabel: 'MCP address',
    addressCaption: 'URL',
    headersLabel: 'Request headers',
    headersCaption: 'HTTP headers',
    claudeHint:
      'Registers the <code>{{server}}</code> server for all your projects (<code>--scope user</code>). A running session does not pick up a new server by itself: run <code>/mcp</code> or restart it. <code>claude mcp list</code> shows whether it is connected.',
    claudeLabel: 'Claude Code command',
    terminalCaption: 'Terminal',
    codexHint:
      'The token goes through the <code>{{env}}</code> environment variable, so the secret does not land in the configuration file. Codex reads the variable from its own environment: set it where Codex is started from, and restart the Codex app after changing it.',
    codexFileLabel: 'Codex configuration section',
    codexEnvBashLabel: 'Codex token variable (bash/zsh)',
    codexEnvBashCaption: 'Terminal, before starting Codex',
    codexEnvPowerShellLabel: 'Codex token variable (PowerShell)',
    codexEnvPowerShellCaption: 'PowerShell, before starting Codex',
    codexFormHint:
      'Or the same values in the form of the Codex app (MCP servers in the settings, a Streamable HTTP server):',
    codexField: {
      url: 'URL',
      bearer_token_env_var: 'Bearer token environment variable',
      http_headers: 'Headers',
    },
    jsonHint:
      'The shape of the Claude Code <code>.mcp.json</code> file. Cursor reads <code>url</code> and <code>headers</code> under the same names; Windsurf, Gemini CLI and VS Code name the fields differently — check the documentation of your client.',
    jsonLabel: 'mcpServers configuration',
    jsonCaption: 'JSON',
  },
} as const;
