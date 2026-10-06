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

  header: {
    // Подписи полосы свойств карточки (UI-143): род значения назван видимо, а не только
    // диктору, — владелец выбрал полосу с подписями (UI-143#10).
    status: 'Status',
    priority: 'Priority',
    /** Направление задачи в проекте (TRK-557): адрес или «без направления». */
    direction: 'Direction',
    noDirection: 'no direction',
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
} as const;
