/**
 * Экран проекта: карточка, атрибуты с историей, дело проекта (`src/pages/project`), и
 * действия с проектом (`src/features/manage-project`).
 */
export const project = {
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
    nameLabel: 'Name',
    nameHint: 'Latin letters, digits, “_” and “-”, up to 64: repo, main-branch.',
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
} as const;
