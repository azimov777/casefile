/**
 * Направления проекта (TRK-557): раздел «Направления» экрана проекта
 * (`src/pages/project`), страница направления (`src/pages/direction`), окна направления
 * (`src/features/manage-project`), направление в карточке задачи
 * (`src/features/change-task-direction`) и знак направления (`src/entities/direction`).
 */
export const direction = {
  /** Знак направления ссылкой (`DirectionLink`). */
  mark: {
    label: 'Direction',
    archived: 'archived',
  },

  cancel: 'Cancel',
  close: 'Close',
  retrySafe: 'Sending again will not create a second direction: the attempt keeps its retry key.',
  descriptionHint:
    'In short, what this direction is: the description rides in the card of every task of the direction.',

  /** Раздел «Направления» экрана проекта. */
  section: {
    title: 'Directions',
    hint: 'Parts of the project work that have no end. A task joins at most one; its tasks are listed by the direction filter.',
    showArchived: 'Show archived directions',
    loading: 'Reading the directions…',
    none: 'The project has no directions yet.',
    noneAtAll: 'The project has no directions, archived ones included.',
    more: 'Only the first page of directions is shown.',
    tasks: 'Tasks of the direction',
  },

  create: {
    open: 'New direction',
    title: 'New direction in {{key}}',
    intro:
      'The direction key becomes part of its address and cannot be changed later; tasks and entries refer to it.',
    keyLabel: 'Key',
    keyHint:
      'Lower-case Latin letters, digits and inner hyphens, up to 32: promotion, commerce. The address is {{key}}/key.',
    keyEmpty: 'The direction needs a key.',
    titleLabel: 'Title',
    titleEmpty: 'The direction needs a title.',
    submit: 'Create direction',
    pending: 'Creating…',
  },

  edit: {
    open: 'Edit',
    label: 'Edit direction {{address}}',
    title: 'Direction {{address}}',
    intro: 'Title and description. The key does not change: it is part of the direction address.',
    titleLabel: 'Title',
    titleEmpty: 'The direction needs a title.',
    submit: 'Save',
    pending: 'Saving…',
  },

  archive: {
    open: 'Archive',
    label: 'Archive direction {{address}}',
    title: 'Archive {{address}}?',
    intro:
      'The card, attributes and case of the direction freeze, and no new task can join it. Tasks already in it go on as usual and can still leave it.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the direction is archived. It will be read in the direction case.',
    reasonEmpty:
      'A direction is not archived without a reason: its case must explain why it was frozen.',
    submit: 'Archive the direction',
    pending: 'Archiving…',
  },

  restore: {
    open: 'Restore',
    label: 'Restore direction {{address}}',
    title: 'Restore {{address}}',
    intro: 'The direction returns to work: tasks can join it again, and its case accepts entries.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the direction returns to work. It will be read in the direction case.',
    reasonEmpty:
      'A direction is not restored without a reason: its case must explain why it came back.',
    submit: 'Restore the direction',
    pending: 'Restoring…',
  },

  /** Страница направления. */
  page: {
    missingTitle: 'There is no direction {{address}}',
    missingText:
      'There is no direction at this address: the key may be mistyped, or the project has no such direction.',
    backToProject: 'Back to project {{key}}',
    loading: 'Loading direction {{address}}…',
    kicker: 'Direction',
    noDescription: 'The direction has no description.',
    project: 'Project {{key}}',
    tasks: 'Tasks of the direction',
    archived:
      'The direction has been archived since {{when}}: its card, attributes and case are read-only. To bring it back to work, restore it.',
    archivedReadOnly:
      'The direction has been archived since {{when}}: its card, attributes and case are read-only.',
    projectArchived:
      'Project {{key}} has been archived since {{when}}: its directions are read-only. Restore the project first.',
  },

  attributes: {
    none: 'The direction has no attributes.',
    historyEmpty: 'The direction case holds no entries about this attribute.',
  },

  case: {
    title: 'Direction case',
    loading: 'Reading the direction case…',
  },

  /** Запись человека в дело направления: заметка или решение (TRK#16, ч. 4). */
  entry: {
    open: 'Write an entry',
    formLabel: 'Entry to the case of {{address}}',
    typeLegend: 'Entry type',
    type: {
      note: 'Note',
      decision: 'Decision',
    },
    fieldLabel: {
      note: 'Note',
      decision: 'Decision',
    },
    submit: {
      note: 'File the note',
      decision: 'File the decision',
    },
    empty: {
      note: 'An empty note cannot be filed.',
      decision: 'An empty decision cannot be filed.',
    },
    placeholder: {
      note: 'What is worth knowing about the direction. Markdown; TRK-2 and TRK/promotion#3 become links.',
      decision:
        'The decision in its first line, then why. Tasks of the direction follow it. Markdown; TRK-2 and TRK#7 become links.',
    },
    receipt: {
      note: 'Note filed',
      decision: 'Decision filed',
    },
    receiptLabel: {
      note: 'Note to the case of {{address}} filed',
      decision: 'Decision to the case of {{address}} filed',
    },
  },

  /** Направление в карточке задачи: окно выбора. */
  task: {
    open: 'Change',
    label: 'Change the direction of {{key}}',
    title: 'Direction of {{key}}',
    intro:
      'A direction of the task’s own project, or none. The change is filed in the task case; agents see it in the task card.',
    legend: 'Direction',
    loading: 'Reading the directions of the project…',
    none: 'No direction',
    noneHint: 'The task belongs to no endless part of the project work.',
    archivedOption: '{{title}} (archived)',
    archivedHint:
      'The current direction is archived: the task can stay in it or leave it, but cannot come back once it leaves.',
    noDirections: 'The project has no active directions.',
    submit: 'Save',
    pending: 'Saving…',
  },
} as const;
