/**
 * Экран проекта: карточка, атрибуты с историей, дело проекта (`src/pages/project`), и
 * действия с проектом (`src/features/manage-project`).
 */
export const project = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    body: "A project answers “what are the tasks about”. Here you edit its description, keep its attributes — where the work lives, what to read before starting — and write notes to the project's case. The agent receives the description with every task of the project.",
  },
  missingTitle: 'There is no project {{key}}',
  missingText:
    'There is no project with this key: the key may be mistyped, or the project belongs to another installation.',
  backToList: 'Back to the task list',
  loading: 'Loading project {{key}}…',

  kicker: 'Project',
  noDescription: 'The project has no description.',
  tasks: 'Tasks of the project',

  attributes: 'Attributes',
  noAttributes: 'The project has no attributes.',
  attributesHint: 'Select a name to see how the value changed and why.',
  history: 'History of {{name}}',
  historyLoading: 'Reading the history…',
  historyEmpty: 'The project case holds no entries about this attribute.',

  /** Решения проекта (TRK-554): записи `decision` дела проекта со статусом от бэкенда. */
  decisions: {
    title: 'Decisions',
    hint: 'Project decisions in force set the work of agents together with the project description. Superseded ones are folded below with what replaced them; the text of a decision is in the project case.',
    none: 'The project has no decisions yet.',
    noneInForce: 'No decision is in force: all of them were superseded.',
    inForce: 'Decisions in force',
    superseded_one: '{{count, number}} superseded decision',
    superseded_other: '{{count, number}} superseded decisions',
    supersededList: 'Superseded decisions',
    supersededBy: 'Superseded by',
    replaces: 'Replaced',
    noTasks: 'no tasks under it',
    tasks_one: '{{count, number}} task under it',
    tasks_other: '{{count, number}} tasks under it',
  },

  case: 'Project case',
  caseLoading: 'Reading the project case…',
  more: 'Show more entries',
  loadingMore: 'Reading more entries…',
  /** Действия с проектом (`features/manage-project`, UI-175). */
  cancel: 'Cancel',
  close: 'Close',
  retrySafe: 'Sending again will not file a second entry: the attempt keeps its retry key.',

  description: {
    label: 'Description',
    hint: 'In short, what this project is: the description rides in the card of every task of the project.',
    left: 'Characters left: {{count}} of {{limit}}',
    over: 'Characters over: {{count}}. The description will not be sent until it is at most {{limit}}.',
  },

  create: {
    open: 'New project',
    title: 'New project',
    intro: 'The project key becomes part of every task key and cannot be changed later.',
    keyLabel: 'Key',
    keyHint:
      'A Latin letter, then Latin letters and digits, 2 to 16 in all: TRK, UI, WEB2. Stored in capitals.',
    keyEmpty: 'The project needs a key.',
    titleLabel: 'Title',
    titleEmpty: 'The project needs a title.',
    submit: 'Create project',
    pending: 'Creating…',
  },

  edit: {
    open: 'Edit',
    title: 'Project {{key}}',
    intro:
      'Title and description. The key does not change: it is part of every task key of the project.',
    titleLabel: 'Title',
    titleEmpty: 'The project needs a title.',
    submit: 'Save',
    pending: 'Saving…',
  },

  attribute: {
    add: 'Add attribute',
    addTitle: 'New attribute',
    addIntro:
      'A reference fact about the project: a name and a value. It is set without a reason; changing or removing it takes one.',
    addIntroDirection:
      'A reference fact about the direction: a name and a value. It is set without a reason; changing or removing it takes one.',
    nameLabel: 'Name',
    nameHint: 'Latin letters, digits, “_” and “-”, up to 64: workspace, read-first.',
    nameEmpty: 'The attribute needs a name.',
    valueLabel: 'Value',
    valueHint: 'Plain text up to 1000 characters, stored as written.',
    addSubmit: 'Add',
    change: 'Change',
    changeLabel: 'Change attribute {{name}}',
    changeTitle: 'Attribute {{name}}',
    changeIntro: 'The previous value stays in the attribute history together with the reason.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the previous value stopped being true. It is read in the attribute history.',
    reasonEmpty:
      'A change without a reason is not sent: the attribute history has to explain why the value changed.',
    changeSubmit: 'Save',
    pending: 'Saving…',
    remove: 'Remove',
    removeLabel: 'Remove attribute {{name}}',
    removeTitle: 'Remove attribute {{name}}?',
    removeIntro:
      'The attribute leaves the project card; its last value and the reason stay in the project case.',
    removeIntroDirection:
      'The attribute leaves the direction card; its last value and the reason stay in the direction case.',
    removeReasonHint: 'Why the attribute is no longer true. It is read in the attribute history.',
    removeReasonEmpty:
      'An attribute is not removed without a reason: the history has to explain why the fact stopped being true.',
    removeSubmit: 'Remove attribute',
    removePending: 'Removing…',
  },

  note: {
    open: 'Write a note',
    formLabel: 'Note to the case of {{key}}',
    fieldLabel: 'Note',
    submit: 'File the note',
    pending: 'Sending…',
    empty: 'An empty note cannot be filed.',
    placeholder: 'What is worth knowing about the project. Markdown; TRK-2 and TRK#7 become links.',
    receiptLabel: 'Note to the case of {{key}} filed',
    receiptHeadline: 'Note filed',
  },

  /** Архив проекта (`UI-176`). */
  archived: {
    notice:
      'The project has been archived since {{when}}: its card, attributes, case and tasks are read-only. To bring it back to work, restore it.',
    noticeReadOnly:
      'The project has been archived since {{when}}: its card, attributes, case and tasks are read-only.',
  },

  archive: {
    open: 'Archive',
    title: 'Archive {{key}}?',
    intro:
      'The project and all its tasks freeze as they are: agents get a refusal on any change until the project is restored. They can still be read; the project leaves the side panel.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the project is archived. It will be read in the project case.',
    reasonEmpty:
      'A project is not archived without a reason: the project case must explain why it was frozen.',
    submit: 'Archive the project',
    pending: 'Archiving…',
  },

  restore: {
    open: 'Restore',
    title: 'Restore {{key}}',
    intro:
      'The project returns to the side panel, and its tasks continue from where the archive left them.',
    reasonLabel: 'Reason',
    reasonHint: 'Why the project returns to work. It will be read in the project case.',
    reasonEmpty:
      'A project is not restored without a reason: the project case must explain why it came back.',
    submit: 'Restore the project',
    pending: 'Restoring…',
  },
} as const;
