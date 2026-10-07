/** Экран карточки задачи: шапка, блоки задания и опись дела (`src/pages/task`). */
export const task = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    body: "This is the assignment for the agent and what has been done on it: the latest summary, open questions and the case index. Here you answer the agent's question and leave a remark when the result came out wrong. Only the agent edits the assignment itself.",
  },
  missingTitle: 'There is no task {{key}}',
  missingText:
    'There is no task with this key: the key may be mistyped, or the task belongs to another installation.',
  backToList: 'Back to the task list',
  loading: 'Loading task {{key}}…',
  /** Задача архивного проекта (`UI-176`): читается, но ни ответа, ни замечания. */
  archived: {
    notice:
      'Project {{key}} is archived: the task is read-only. Answering a question or leaving a remark becomes possible once the project is restored.',
    project: 'Open project {{key}}',
  },

  summary: 'Latest summary',
  noSummary: 'There is no summary yet: nobody has reported on this task.',
  questions: 'Open questions',
  noQuestions: 'There are no questions without an answer.',
  remarks: 'Remarks',
  noRemarks: 'There are no unresolved remarks.',
  case: 'Case',
  openCase: 'Open the whole case as a feed',
  assignment: 'Assignment',
  links: 'Links',
  noLinks: 'There are no links.',
  linkGroup: {
    count_one: '{{count, number}} task',
    count_other: '{{count, number}} tasks',
  },

  /** Блок «Сейчас» под шапкой карточки (TRK-579): считается бэкендом при чтении, не редактируется. */
  state: {
    title: 'Right now',
    filed: 'Filed',
    lastMove: 'Last move',
    noMove: 'The status has not changed yet.',
    by: 'by',
    blockedBy: 'Blocked by',
    children: 'Child tasks by status',
    recentAfterSummary_one: 'After summary #{{no}}: {{count, number}} entry',
    recentAfterSummary_other: 'After summary #{{no}}: {{count, number}} entries',
    recentNoSummary_one: 'No summary: {{count, number}} entry in all',
    recentNoSummary_other: 'No summary: {{count, number}} entries in all',
    decisionsAfterCard: 'Decided after the assignment was edited',
  },

  header: {
    // Подписи полосы свойств карточки (UI-143): род значения назван видимо, а не только
    // диктору, — владелец выбрал полосу с подписями (UI-143#10).
    status: 'Status',
    priority: 'Priority',
    /** Область задачи в проекте (TRK-557): адрес или «без области». */
    area: 'Area',
    noArea: 'no area',
    assignee: 'Assignee',
    /** Prior keys of a moved task (TRK-173): the cell shows up only when there are any. */
    previousKeys: 'Previous keys',
    flags: 'Flags',
    /** Решения проекта, на которые опирается задача (TRK-554): строка видна, только когда они есть. */
    decisions: 'Decisions',
    supersededBy: 'superseded by',
    unassigned: 'not assigned',
    updated: 'Updated',
    created: 'Created',
    /** Момент «можно взять с …» (TRK-593): ячейка видна, когда он задан или его можно поставить. */
    notBefore: 'Take into work',
  },

  sections: {
    description: 'Description',
    goal: 'Goal',
    context: 'Context',
    constraints: 'Constraints',
    output: 'Output',
    checks: 'Review checks',
    noChecks: 'There are no checks.',
    empty: 'The section is empty.',
  },

  index: {
    toLatest: 'To the latest entry',
    toTop: 'To the top of the index',
  },

  /** Момент «можно взять с …» на странице задачи (`features/change-task-not-before`, TRK-593). */
  notBefore: {
    line: 'Can be taken into work from {{moment}}',
    none: 'no restriction',
    defer: 'Defer…',
    deferLabel: 'Defer task {{key}}',
    change: 'Change',
    changeLabel: 'Change the moment of task {{key}}',
    clear: 'Clear',
    clearLabel: 'Clear the moment of task {{key}}',
    title: 'When {{key}} can be taken',
    intro:
      'Until this moment an agent cannot take the task into work. It is not a deadline: the tracker reminds no one.',
    inputLabel: 'Can be taken from',
    inputHint: 'Date and time by the clock of this device.',
    empty: 'Enter a date and time.',
    submit: 'Save',
    pending: 'Saving…',
    cancel: 'Cancel',
    close: 'Close',
  },
} as const;
