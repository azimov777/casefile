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
      note: 'What is worth knowing about the area. Markdown; TRK-2 and TRK/promotion#3 become links.',
      decision:
        'The decision in its first line, then why. Tasks of the area follow it. Markdown; TRK-2 and TRK#7 become links.',
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

  /** Область в карточке задачи: окно выбора. */
  task: {
    open: 'Change',
    label: 'Change the area of {{key}}',
    title: 'Area of {{key}}',
    intro:
      'An area of the task’s own project, or none. The change is filed in the task case; agents see it in the task card.',
    legend: 'Area',
    loading: 'Reading the areas of the project…',
    none: 'No area',
    noneHint: 'The task belongs to no endless part of the project work.',
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

  /** Area page tabs (TRK-618): without a parameter the Case tab opens. */
  tabs: {
    label: 'Area sections',
    attributes: 'Attributes',
    case: 'Case',
  },
} as const;
