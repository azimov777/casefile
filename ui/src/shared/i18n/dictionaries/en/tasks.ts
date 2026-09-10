/**
 * Экран списка задач: таблица, доска и отбор над ними (`src/pages/tasks`,
 * `src/features/task-filters`).
 */
export const tasks = {
  title: 'Tasks',
  loading: 'Loading the tasks…',
  // Сколько нашлось по отбору — и у таблицы, и у доски: числа по статусам стоят
  // в заголовках столбцов, а это про всю выдачу.
  found_zero: 'Nothing found',
  found_one: '{{count, number}} task found',
  found_other: '{{count, number}} tasks found',
  empty: 'No tasks match these conditions',
  resetFilters: 'Reset the filters',
  beyond_one:
    'There are no tasks on this page: {{count, number}} task matches these conditions, and it is on an earlier page',
  beyond_other:
    'There are no tasks on this page: {{count, number}} tasks match these conditions, and they are all on earlier pages',

  table: {
    label: 'Tasks, the table scrolls sideways',
    caption_one: '{{count, number}} task on this page',
    caption_other: '{{count, number}} tasks on this page',
  },

  paging: {
    label: 'Result pages',
    previous: 'Previous page',
    next: 'Next page',
    page: 'Page {{page}}',
    pageOf: 'Page {{page}} of {{pages, number}}',
    total_one: '{{count, number}} page',
    total_other: '{{count, number}} pages',
  },

  board: {
    reading: 'Reading the column…',
    readingMore: 'Reading more…',
    // «сколько-то из ?»: числа выдачи бэкенд не назвал, и точным его не заменить.
    ofUnknown: '{{count, number}} of ?',
    // Свёрнутый столбец не читал ничего: без числа от бэкенда сказать ему нечего.
    unknown: '?',
    empty: 'Empty',
  },

  view: {
    label: 'List view',
    table: 'Table',
    board: 'Board',
  },

  filters: {
    label: 'Task selection',
    expand: 'Change the selection',
    collapse: 'Collapse the selection',
    conditions: 'Selection conditions',
    allShown: 'all tasks are shown',
    remove: 'Remove the condition: {{condition}}',
    reset: 'Reset',
    formLabel: 'Task selection conditions',
    statusLegend: 'Status',
    priorityLegend: 'Priority',
    boardNote: 'The board shows every status: each in its own column.',
    assignee: 'Assignee',
    assigneePlaceholder: 'the whole name',
    text: 'Text',
    textPlaceholder: 'in the title or the description',
    blocked: 'blocked',
    withQuestions: 'has open questions',
    withRemarks: 'has unresolved remarks',
    pending: 'not applied, Enter applies it',
    apply: 'Apply',

    sort: {
      label: 'Order',
      '-last_entry_at': 'live cases first',
      last_entry_at: 'quiet cases first',
      '-updated_at': 'recently edited first',
      updated_at: 'long untouched first',
      '-priority': 'important first',
      priority: 'unimportant first',
      key: 'by key',
      '-key': 'by key, backwards',
    },

    query: {
      label: 'Query in the backend language',
      note: 'cancels the rest of the selection',
      // Пример на языке запросов бэкенда, а не фраза: он одинаков на любом языке
      // (освобождён в `dictionaries.test.ts`).
      placeholder: 'queue: DEMO and status: open and blocked: false',
      errorAt: 'The error is at character {{position}}.',
      allowed: 'Allowed: {{list}}',
      stale: 'The rows of the previous selection are shown.',
    },

    condition: {
      query: 'query: {{query}}',
      status: 'status {{values}}',
      priority: 'priority {{values}}',
      assignee: 'assignee {{value}}',
      text: 'text “{{value}}”',
      blocked: 'blocked only',
      questions: 'has open questions',
      remarks: 'has unresolved remarks',
    },
  },
} as const;
