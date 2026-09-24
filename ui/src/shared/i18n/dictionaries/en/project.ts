/** Экран проекта: карточка, атрибуты с историей, дело проекта (`src/pages/project`). */
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
} as const;
