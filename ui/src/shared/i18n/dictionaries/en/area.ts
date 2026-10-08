/**
 * Области проекта (TRK-557): раздел «Области» экрана проекта
 * (`src/pages/project`), страница области (`src/pages/area`), окна области
 * (`src/features/manage-project`), область в карточке задачи
 * (`src/features/change-task-area`) и знак области (`src/entities/area`).
 */
export const area = {
  /** Знак области ссылкой (`AreaLink`). */
  mark: {
    label: 'Area',
    archived: 'archived',
  },

  cancel: 'Cancel',
  close: 'Close',
  retrySafe: 'Sending again will not create a second area: the attempt keeps its retry key.',
  descriptionHint:
    'In short, what this area is: the description rides in the card of every task of the area.',

  /** Раздел «Области» экрана проекта. */
  section: {
    title: 'Areas',
    hint: 'Parts of the project work that have no end. A task joins at most one; its tasks are listed by the area filter.',
    showArchived: 'Show archived areas',
    loading: 'Reading the areas…',
    none: 'The project has no areas yet.',
    noneAtAll: 'The project has no areas, archived ones included.',
    more: 'Only the first page of areas is shown.',
    tasks: 'Tasks of the area',
  },

  create: {
    open: 'New area',
    title: 'New area in {{key}}',
    intro:
      'The area key becomes part of its address and cannot be changed later; tasks and entries refer to it.',
    keyLabel: 'Key',
    keyHint:
      'Lower-case Latin letters, digits and inner hyphens, up to 32: promotion, commerce. The address is {{key}}/key.',
    keyEmpty: 'The area needs a key.',
    titleLabel: 'Title',
    titleEmpty: 'The area needs a title.',
    submit: 'Create area',
    pending: 'Creating…',
  },

  edit: {
    open: 'Edit',
    label: 'Edit area {{address}}',
    title: 'Area {{address}}',
    intro: 'Title and description. The key does not change: it is part of the area address.',
    titleLabel: 'Title',
    titleEmpty: 'The area needs a title.',
    submit: 'Save',
    pending: 'Saving…',
  },

  archive: {
    open: 'Archive',
    label: 'Archive area {{address}}',
    title: 'Archive {{address}}?',
    intro:
      'The card, attributes and case of the area freeze, and no new task can join it. Tasks already in it go on as usual and can still leave it.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the area is archived. It will be read in the area case.',
    reasonEmpty:
      'An area is not archived without a reason: its case must explain why it was frozen.',
    submit: 'Archive the area',
    pending: 'Archiving…',
  },

  restore: {
    open: 'Restore',
    label: 'Restore area {{address}}',
    title: 'Restore {{address}}',
    intro: 'The area returns to work: tasks can join it again, and its case accepts entries.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the area returns to work. It will be read in the area case.',
    reasonEmpty:
      'An area is not restored without a reason: its case must explain why it came back.',
    submit: 'Restore the area',
    pending: 'Restoring…',
  },

  /** Страница области. */
  page: {
    missingTitle: 'There is no area {{address}}',
    missingText:
      'There is no area at this address: the key may be mistyped, or the project has no such area.',
    backToProject: 'Back to project {{key}}',
    loading: 'Loading area {{address}}…',
    kicker: 'Area',
    noDescription: 'The area has no description.',
    project: 'Project {{key}}',
    tasks: 'Tasks of the area',
    archived:
      'The area has been archived since {{when}}: its card, attributes and case are read-only. To bring it back to work, restore it.',
    archivedReadOnly:
      'The area has been archived since {{when}}: its card, attributes and case are read-only.',
    projectArchived:
      'Project {{key}} has been archived since {{when}}: its areas are read-only. Restore the project first.',
  },

  attributes: {
    none: 'The area has no attributes.',
    historyEmpty: 'The area case holds no entries about this attribute.',
  },

  case: {
    title: 'Area case',
    loading: 'Reading the area case…',
  },

  /** Запись человека в дело области: заметка или решение (TRK#16, ч. 4). */
  entry: {
    open: 'Write an entry',
    formLabel: 'Entry to the case of {{address}}',
    typeLegend: 'Entry type',
    type: {
      finding: 'Note',
      decision: 'Decision',
    },
    fieldLabel: {
      finding: 'Note',
      decision: 'Decision',
    },
    submit: {
      finding: 'File the note',
      decision: 'File the decision',
    },
    empty: {
      finding: 'An empty note cannot be filed.',
      decision: 'An empty decision cannot be filed.',
    },
    placeholder: {
      finding:
        'What is worth knowing about the area. Markdown; TRK-2 and TRK/promotion#3 become links.',
      decision:
        'The decision in its first line, then why. Tasks of the area follow it. Markdown; TRK-2 and TRK#7 become links.',
    },
    receipt: {
      finding: 'Note filed',
      decision: 'Decision filed',
    },
    receiptLabel: {
      finding: 'Note to the case of {{address}} filed',
      decision: 'Decision to the case of {{address}} filed',
    },
  },

  /** Область в карточке задачи: окно выбора. */
  task: {
    open: 'Change',
    label: 'Change the area of {{key}}',
    title: 'Area of {{key}}',
    intro:
      'An area of the task’s own project. It can be changed but not taken off. The change is filed in the task case; agents see it in the task card.',
    legend: 'Area',
    loading: 'Reading the areas of the project…',
    none: 'No area',
    noneHint: 'The task has no area: it was filed before areas became required.',
    archivedOption: '{{title}} (archived)',
    archivedHint:
      'The current area is archived: the task can stay in it or leave it, but cannot come back once it leaves.',
    noAreas: 'The project has no active areas.',
    submit: 'Save',
    pending: 'Saving…',
  },

  /** The «⋯» menu in the area page header (TRK-618). */
  menu: {
    label: 'Actions with area {{address}}',
  },

  /** Area page tabs (TRK-618, TRK-660): without a parameter the Decisions tab opens. */
  tabs: {
    label: 'Area sections',
    decisions: 'Decisions',
    notes: 'Notes',
    attributes: 'Attributes',
    case: 'Case',
  },

  /**
   * Знание области (TRK-660, TRK#59): вкладки «Решения» и «Заметки» — действующие записи,
   * заменённые по переключателю, поиск по тексту, «Решение» и «Заметка».
   */
  knowledge: {
    searchLabel: 'Search decisions and notes',
    searchPlaceholder: 'A word from the title or the text',
    searchClear: 'Clear the search',
    loading: 'Reading the knowledge of the area…',
    showSuperseded: 'Show superseded',
    supersededCount_one: '{{count, number}} entry superseded',
    supersededCount_other: '{{count, number}} entries superseded',
    openDecision: 'Decision',
    openNote: 'Note',
    decisions: {
      title: 'Decisions of the area',
      hint: 'Rules of this part of the project: tasks of the area follow the ones in force.',
      none: 'The area has no decisions yet.',
      noneInForce: 'No decision is in force: all of them were superseded.',
      noMatch: 'No decision matches the search.',
      list: 'Decisions of the area',
    },
    notes: {
      title: 'Notes of the area',
      hint: 'What is worth knowing about this part of the project. A note explains; it does not set the work.',
      none: 'The area has no notes yet.',
      noneInForce: 'No note is in force: all of them were superseded.',
      noMatch: 'No note matches the search.',
      list: 'Notes of the area',
    },
  },
} as const;
