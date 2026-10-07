/**
 * Discussions (TRK-672, project decision `TRK#51`): the discussion screen
 * (`src/pages/discussion`), the inbox and history by discussions (`src/pages/questions`),
 * the block in the task card (`src/pages/task`), the person's forms
 * (`src/features/manage-discussion`) and the list row with the "whose move" mark
 * (`src/entities/discussion`).
 */
export const discussions = {
  retrySafe: 'Sending again will not file a second entry: the attempt keeps its repeat key.',

  turn: {
    human: 'waiting for you',
    agent: "agent's move",
    open: 'open',
    closed: 'closed',
  },

  row: {
    label: 'Discussion {{address}}',
    openQuestions_zero: 'no unanswered questions',
    openQuestions_one: '{{count, number}} unanswered question',
    openQuestions_other: '{{count, number}} unanswered questions',
  },

  page: {
    kicker: 'Discussion',
    loading: 'Reading discussion {{address}}…',
    missingTitle: 'There is no discussion {{address}}',
    missingText:
      'The address is not of the form "KEY~NUMBER", or the project has no discussion with that number. Discussions waiting for your answer are in the inbox.',
    backToInbox: '← Back to the inbox',
    openedBy: 'Opened by {{author}}',
    tracker: 'the tracker',
    closedNotice:
      'This discussion was closed {{when}}. An agent closes it; nothing in a closed one changes, neither entries nor attached tasks. To clarify something, open a new discussion that links to this one.',
  },

  conclusion: {
    title: 'Conclusion',
    none: 'No conclusion yet: an agent draws it after an answer.',
  },

  tasks: {
    title: 'Tasks waiting for the conclusion',
    intro:
      'An attached task depends on the conclusion: while the discussion has an unanswered question it cannot go into work, and it cannot be closed until the discussion is closed.',
    none: 'No tasks are attached to this discussion.',
  },

  thread: {
    title: 'Conversation',
    label: 'Discussion entries by time',
    loading: 'Reading the conversation…',
    empty: 'There are no entries in this discussion yet.',
    more: 'Show more',
    loadingMore: 'Reading…',
    answered: 'answered',
    waiting: 'waiting for an answer',
    addressees: 'To:',
    details: 'Details',
    conclusionActual: 'current conclusion',
    conclusionPrior: 'earlier conclusion',
  },

  reply: {
    open: 'Reply to #{{no}}',
    formLabel: 'Answer to {{reference}}',
    fieldLabel: 'Answer',
    submit: 'Answer',
    pending: 'Sending…',
    empty: 'An empty answer cannot be sent: the agent needs text, not the fact of a click.',
    placeholder: 'Markdown. References such as TRK-42, TRK~7 and TRK~7#3 become links.',
  },

  note: {
    open: 'Note',
    formLabel: 'Note in discussion {{address}}',
    fieldLabel: 'Note',
    submit: 'File the note',
    pending: 'Sending…',
    empty: 'An empty note cannot be filed.',
    placeholder:
      'A free entry without a question: a clarification, an objection, a link. The agent reads it like an answer.',
  },

  attach: {
    formLabel: 'Attach a task to {{address}}',
    fieldLabel: 'Attach a task by key',
    placeholder: 'TRK-42',
    submit: 'Attach',
    pending: 'Attaching…',
    empty: 'A task key is required.',
  },

  detach: {
    label: 'Detach task {{key}}',
    submit: 'Detach',
  },

  create: {
    open: 'New discussion',
    title: 'New discussion',
    intro:
      'A discussion is a conversation about one narrow question. Here you open it with a note, without a question: an agent answers in it. An agent closes the discussion.',
    close: 'Close',
    projectLabel: 'Project',
    projectChoose: 'choose a project',
    projectEmpty: 'Choose a project.',
    titleLabel: 'Title — the question itself',
    titleHint: 'One line: a narrow question whose answer the work depends on.',
    titleEmpty: 'A one-line title is required.',
    bodyLabel: 'Context',
    tasksLabel: 'Tasks that depend on the conclusion',
    tasksPlaceholder: 'TRK-42 TRK-43',
    tasksHint: 'Keys separated by spaces. You can attach later, on the discussion screen.',
    submit: 'Open the discussion',
    pending: 'Opening…',
    cancel: 'Cancel',
  },

  inbox: {
    title: 'Discussions waiting for you',
    intro:
      'Open discussions where an agent waits for your answer. You answer on the discussion screen: the whole conversation and the conclusion are there.',
    loading: 'Reading discussions…',
    none: 'No discussions are waiting for you.',
    noneByProject: 'Project {{project}} has no discussions waiting for you.',
  },

  history: {
    title: 'Discussions',
    loading: 'Reading the discussion history…',
    none: 'No discussions have been opened yet.',
    noneByProject: 'Project {{project}} has no discussions yet.',
  },

  taskBlock: {
    title: 'Discussions',
    loading: 'Reading the task discussions…',
    none: 'No discussions.',
  },
} as const;
