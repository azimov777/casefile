/** Экран карточки задачи: шапка, блоки задания и опись дела (`src/pages/task`). */
export const task = {
  missingTitle: 'There is no task {{key}}',
  missingText:
    'There is no task with this key: the key may be mistyped, or the task belongs to another installation.',
  backToList: 'Back to the task list',
  loading: 'Loading task {{key}}…',

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
    assignee: 'Assignee',
    flags: 'Flags',
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
    empty: 'The case is empty: there are no entries yet.',
    toLatest: 'To the latest entry',
    toTop: 'To the top of the index',
    count_one: '{{count, number}} entry in the case',
    count_other: '{{count, number}} entries in the case',
    loadingEntry: 'Reading the entry…',
    columns: {
      no: 'No.',
      type: 'Type',
      author: 'Author',
      when: 'When',
      headline: 'Headline',
    },
  },
} as const;
