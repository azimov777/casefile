/** Экран входящей: вопросы ко мне и мои замечания без разбора (`src/pages/questions`). */
export const questions = {
  intro: 'The questions agents are waiting on from you, and your remarks you are waiting on.',
  filterLabel: 'Inbox selection',
  queue: 'Queue',
  allQueues: 'every queue',
  queueNote: 'The queue selects both halves of the inbox.',

  questionsTitle: 'Questions for me',
  blockingOnly: 'blocking only',
  loadingQuestions: 'Reading the inbox…',
  noQuestions: 'There are no questions without an answer: no agent is waiting on you.',
  questionLabel: 'Question {{reference}}',
  blockingQuestionLabel: 'Blocking question {{reference}}',

  remarksTitle: 'My remarks without a resolution',
  loadingRemarks: 'Reading the remarks…',
  noRemarks: 'There are no unresolved remarks.',
  awaitingResolution: 'awaiting a resolution',

  more: 'More',
  loadingMore: 'Reading…',

  emptyByFilter: 'Nothing matched this selection ({{conditions}}).',
  resetFilter: 'Reset the selection',
  condition: {
    queue: 'queue {{queue}}',
    blocking: 'blocking only',
  },
} as const;
