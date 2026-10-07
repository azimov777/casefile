import type { components } from '@/shared/api';

type AnswerOutcome = components['schemas']['AnswerOutcome'];

/** Экран входящей: обсуждения, задачи, закрытые не целиком, мои замечания без разбора и история вопросов (`src/pages/questions`). */
export const questions = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-362`). */
  explanation: {
    body: 'Discussions where an agent waits for your answer arrive here: the whole conversation about one narrow question, with a conclusion on top. You answer on the discussion screen and the agent reads the answer from there; while a discussion has an unanswered question, the tasks attached to it stand still. If the agent has already stopped, tell it in its chat that you have answered.',
  },
  intro:
    'The discussions where agents wait for your answer, tasks closed not in full, and your remarks you are waiting on.',
  filterLabel: 'Inbox selection',
  project: 'Project',
  allProjects: 'every project',
  projectNote: 'The project filters every part of the inbox.',

  questionLabel: 'Question {{reference}}',

  attentionTitle: 'Need attention',
  attentionIntro:
    'Tasks the agent closed not in full: a check passed in part or could not be run. Open the task and accept the gap, or return it for rework.',
  loadingAttention: 'Reading tasks closed not in full…',
  noAttention: 'No task closed not in full is waiting for a decision.',
  attentionLabel: 'Task {{key}} closed not in full',
  awaitingDecision: 'awaits a decision',

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
    'Every discussion and every question from task cases with its answers, newest first. You cannot answer from here: whatever waits for an answer is in the inbox.',
  historyFilterLabel: 'History selection',
  onlyMine: 'addressed to me only',
  historyTitle: 'Questions and answers',
  loadingHistory: 'Reading the question history…',
  noHistory: 'Nobody has asked you a question yet.',
  noHistoryAnyone: 'Nobody has asked a question yet.',
  addressees: 'To: {{names}}',
  closedAs: {
    answered: 'answered',
    withdrawn: 'withdrawn',
    replaced: 'replaced',
  } satisfies Record<AnswerOutcome, string>,
  awaitingAnswer: 'awaiting an answer',
  noAnswerYet: 'There is no answer yet.',
  answersLabel: 'Answers to {{reference}}',
  answerLabel: 'Answer {{reference}}',

  more: 'More',
  loadingMore: 'Reading…',

  emptyByFilter: 'Nothing matched this selection ({{conditions}}).',
  resetFilter: 'Reset the selection',
  condition: {
    project: 'project {{project}}',
  },
} as const;
