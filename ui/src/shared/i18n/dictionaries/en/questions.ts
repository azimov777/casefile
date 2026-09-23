/** Экран входящей: вопросы ко мне, мои замечания без разбора и история вопросов (`src/pages/questions`). */
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

  view: {
    label: 'Inbox view',
    inbox: 'Awaiting an answer',
    history: 'Question history',
  },
  historyIntro:
    'Every question with its answers, newest first. You cannot answer from here: open questions wait in the inbox.',
  historyFilterLabel: 'History selection',
  onlyMine: 'addressed to me only',
  historyTitle: 'Questions and answers',
  loadingHistory: 'Reading the question history…',
  noHistory: 'Nobody has asked you a question yet.',
  noHistoryAnyone: 'Nobody has asked a question yet.',
  addressees: 'To: {{names}}',
  answered: 'answered',
  awaitingAnswer: 'awaiting an answer',
  noAnswerYet: 'There is no answer yet.',
  answersLabel: 'Answers to {{reference}}',
  answerLabel: 'Answer {{reference}}',

  more: 'More',
  loadingMore: 'Reading…',

  emptyByFilter: 'Nothing matched this selection ({{conditions}}).',
  resetFilter: 'Reset the selection',
  condition: {
    queue: 'queue {{queue}}',
    blocking: 'blocking only',
  },
} as const;
