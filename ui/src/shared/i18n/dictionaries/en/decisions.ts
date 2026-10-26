/**
 * A person reviews decisions (TRK-755, TRK-758): the «Unconfirmed decisions» line, the
 * filter, the marks and the four actions — Confirm, Fix, Reject, Delete. Used by the
 * project and area screens (`features/decisions/review`); the Inbox takes it too.
 */
export const decisions = {
  loading: 'Reading the decisions…',
  none: 'There are no decisions yet.',
  close: 'Close',
  cancel: 'Cancel',
  retrySafe: 'Sending again will not create a second entry: the attempt keeps its retry key.',

  /** The line under the task counters: how many decisions in force nobody has reviewed. */
  unconfirmed: {
    some: 'Unconfirmed decisions: {{count, number}}',
    none: 'All decisions are confirmed',
  },

  filter: {
    label: 'Decision filter',
    inForce: 'In force',
    unconfirmed: 'Unconfirmed',
    removed: 'Show removed',
  },
  empty: {
    inForce: 'No decisions are in force.',
    unconfirmed: 'No unconfirmed decisions: a person has reviewed every decision in force.',
    removed: 'No decisions were taken out of force: none superseded, rejected or deleted.',
    noMatch: 'Nothing matches the search.',
  },
  list: 'Decisions',

  mark: {
    unconfirmed: 'unconfirmed',
    confirmed: 'confirmed',
  },
  row: {
    projectOf: 'Project',
    project: 'project',
    area: 'Area',
    from: 'Source',
    noTasks: 'no tasks under it',
    tasks_one: '{{count, number}} task under it',
    tasks_other: '{{count, number}} tasks under it',
    supersededBy: 'Replaced by',
    bodyLoading: 'Reading the text…',
    bodyEmpty: 'The decision has no text.',
    actions: 'Review of decision {{ref}}',
    reviewed: 'The review is recorded.',
  },

  action: {
    confirm: 'Confirm',
    confirmLabel: 'Confirm decision {{ref}}',
    revise: 'Fix',
    reviseLabel: 'Fix decision {{ref}}',
    reject: 'Reject',
    rejectLabel: 'Reject decision {{ref}}',
    remove: 'Delete',
    removeLabel: 'Delete decision {{ref}}',
    pending: 'Sending…',
  },

  /** The «Reject» and «Delete» windows: the reason is optional, the entry stays in the case. */
  take: {
    reject: {
      title: 'Reject decision {{ref}}?',
      intro:
        'The decision stops applying to agents: you disagree with it. The entry stays in the case, nothing replaces it.',
      submit: 'Reject',
    },
    remove: {
      title: 'Delete decision {{ref}}?',
      intro:
        'The decision stops applying to agents: it is out of date. The entry stays in the case, nothing replaces it.',
      submit: 'Delete',
    },
    replacedOne:
      'Decision {{refs}}, which this one replaced, will not apply again. To bring its meaning back, fix the decision instead of rejecting it.',
    replacedMany:
      'Decisions {{refs}}, which this one replaced, will not apply again. To bring their meaning back, fix the decision instead of rejecting it.',
    tasks_one: '{{count, number}} task stands on this decision: its own decision does not change.',
    tasks_other:
      '{{count, number}} tasks stand on this decision: their own decisions do not change.',
    reasonLabel: 'Reason (optional)',
    reasonHint: 'It is read in the case, in the review entry.',
  },

  revise: {
    title: 'Fix decision {{ref}}',
    intro:
      'The new decision replaces this one and is confirmed at once. The old one stays in the case as superseded.',
    titleLabel: 'Title',
    titleEmpty: 'The decision needs a title.',
    bodyLabel: 'Decision text',
    bodyLoading: 'Reading the decision text…',
    submit: 'Replace with this decision',
    pending: 'Replacing…',
  },
} as const;
