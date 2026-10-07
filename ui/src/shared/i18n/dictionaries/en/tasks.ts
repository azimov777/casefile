/**
 * Экран списка задач: таблица, доска и отбор над ними (`src/pages/tasks`,
 * `src/features/task-filters`).
 */
export const tasks = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    list: 'All tasks that agents carry are here. Agents create and move them; you watch where things stand. Marks in a row show open questions, remarks and blockers.',
    board:
      'The same tasks in six status columns — of one project or of all, depending on what is selected. Agents move the cards; a card cannot be dragged. The “Waiting for an answer” column holds tasks with an open blocking question, the move is yours; once answered, a task returns to its status column, and a task waiting on another task stays in its own column with a lock.',
  },
  title: 'Tasks',
  loading: 'Loading the tasks…',
  // Сколько нашлось по отбору — и у таблицы, и у доски: числа по статусам стоят
  // в заголовках столбцов, а это про всю выдачу.
  found_zero: 'Nothing found',
  found_one: '{{count, number}} task found',
  found_other: '{{count, number}} tasks found',
  empty: 'No tasks match these conditions',
  // Пустой проект без единого условия отбора — другая беда, чем пустая выдача по
  // условиям: здесь сказано, откуда возьмутся задачи, а не предложен сброс, снимать
  // который нечего (TRK-365).
  noneYet:
    'There are no tasks yet: an agent creates and carries them. See the <start>Start</start> screen for what to do.',
  // Пустота при скрытом архиве: сказать, что за ней может стоять архив, и дать его
  // показать — иначе «задач нет» читалось бы выводом обо всём проекте.
  archiveHidden: 'The archive is not shown.',
  showArchive: 'Show the archive',
  resetFilters: 'Reset the filters',
  beyond_one:
    'There are no tasks on this page: {{count, number}} task matches these conditions, and it is on an earlier page',
  beyond_other:
    'There are no tasks on this page: {{count, number}} tasks match these conditions, and they are all on earlier pages',

  table: {
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
    // The column is computed from open blocking questions, not from a stored status
    // (TRK-571, TRK-573); its key `waiting` is not shown to the person.
    waitingColumn: 'Waiting for an answer',
  },

  view: {
    label: 'List view',
    table: 'Table',
    board: 'Board',
  },

  filters: {
    label: 'Task selection',
    conditions: 'Selection conditions',
    allShown: 'all tasks are shown',
    // Без условий, но с умолчанием архива: «показаны все» было бы неправдой.
    allButArchive: 'all tasks but the archive are shown',
    remove: 'Remove the condition: {{condition}}',
    reset: 'Reset',
    menu: 'Filter',
    menuLabel: 'Task selection conditions',
    statusLegend: 'Status',
    priorityLegend: 'Priority',
    flagsLegend: 'Signals',
    directionLegend: 'Direction',
    directionAny: 'any direction',
    directionNone: 'no direction',
    directionOption: '{{title}} — {{address}}',
    directionArchived: '{{title}} — {{address}} (archived)',
    assignee: 'Assignee',
    assigneePlaceholder: 'the whole name',
    text: 'Text',
    textPlaceholder: 'Find in the title or the description',
    blocked: 'blocked',
    withQuestions: 'has open questions',
    withRemarks: 'has unresolved remarks',
    withWarnings: 'closed not in full, awaits a decision',
    withWaiting: 'awaiting an answer',
    pending: 'not applied, Enter applies it',
    pendingShort: '↵ apply',
    apply: 'Apply',

    archive: {
      label: 'show the archive',
      // Имя кнопки со знаком вопроса, раскрывающей пояснение (UI-153).
      explain: 'What the archive is',
      // Что такое архив — словами и числом из кода (`ARCHIVE_AFTER_DAYS`), а не
      // вписанным в строку: порог живёт в одном месте.
      hint_one:
        'The archive: closed tasks with no entries in the case for over {{count, number}} day',
      hint_other:
        'The archive: closed tasks with no entries in the case for over {{count, number}} days',
    },

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
      toggle: 'Query',
      label: 'Query in the backend language',
      note: 'The query replaces the simple selection; the archive is still up to the checkbox on the right.',
      // Пример на языке запросов бэкенда, а не фраза: он одинаков на любом языке
      // (освобождён в `dictionaries.test.ts`).
      placeholder: 'project: DEMO and status: open and blocked: false',
      errorAt: 'The error is at character {{position}}.',
      allowed: 'Allowed: {{list}}',
      stale: 'The rows of the previous selection are shown.',
    },

    condition: {
      query: 'query: {{query}}',
      status: 'status {{values}}',
      priority: 'priority {{values}}',
      direction: 'direction {{value}}',
      noDirection: 'no direction',
      assignee: 'assignee {{value}}',
      text: 'text “{{value}}”',
      blocked: 'blocked only',
      questions: 'has open questions',
      remarks: 'has unresolved remarks',
      warnings: 'closed not in full, awaits a decision',
      waiting: 'awaiting an answer',
    },
  },

  /** Task counters: in progress, open, awaiting an answer, closed with gaps (TRK-619). */
  counters: {
    label: 'Task counts',
    inProgress: 'In progress',
    open: 'Open',
    waiting: 'Awaiting an answer',
    warnings: 'Closed with gaps',
  },
} as const;
