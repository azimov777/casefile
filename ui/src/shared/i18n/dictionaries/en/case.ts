/** Экран дела: лента записей и отбор по типам (`src/pages/case`). */
export const caseScreen = {
  missingTitle: 'There is no case {{key}}',
  missingText: 'There is no task with this key, so there is no case either.',
  backToList: 'Back to the task list',
  title: 'Case {{key}}',
  toLatest: 'To the latest entry',
  loading: 'Reading the case…',
  emptyByTypes: 'There are no entries of these types in the case.',
  noAnswerYet: 'There is no answer yet.',
  noResolutionYet: 'There is no resolution yet.',
  more: 'More',
  loadingMore: 'Reading…',
  fromStart: 'Read the case from the start',

  window: {
    shown: 'The entries after {{reference}} are shown.',
    hiddenByType: 'Entry {{reference}} is not visible: it does not match the type selection.',
    showAllTypes: 'Show every type',
    missing:
      'There is no entry {{reference}} in the case: the number may be mistyped, or the link points at another task.',
  },

  end_one: 'That is the whole case, {{count, number}} entry.',
  end_other: 'That is the whole case, {{count, number}} entries.',
  endOfWindow_one: 'That is the end of the case, {{count, number}} entry shown.',
  endOfWindow_other: 'That is the end of the case, {{count, number}} entries shown.',

  filters: {
    label: 'Entry selection',
    menu: 'Filter',
    menuLabel: 'Entry types',
    agentEntries: 'Agent entries',
    serviceEntries: 'Service entries',
    chosen: 'Chosen entry types',
    allShown: 'all entries are shown',
    remove: 'Remove the type: {{type}}',
    reset: 'Reset',
  },
} as const;
