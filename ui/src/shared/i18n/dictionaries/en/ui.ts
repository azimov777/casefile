import type { components } from '@/shared/api';

type EntryType = components['schemas']['EntryType'];
type RemarkOutcome = components['schemas']['RemarkOutcome'];

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
    nav: {
      label: 'Navigation for task {{key}}',
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
} as const;
