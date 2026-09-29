/**
 * Экран «Перенос установки» (`docs/moving.md`, TRK-100, UI-135): download this
 * installation's archive, and import one into a fresh installation.
 *
 * Both actions require the administrator flag; a person without it sees `notAdmin`
 * instead of the buttons, the same way the «People» screen explains a closed record.
 */
export const moving = {
  intro:
    'Take every task, case file, person and agent token from this installation and bring them up in another one — a new laptop, or your own server — with two clicks, no shell and no database commands.',
  loadingMe: 'Asking the installation who you are…',
  notAdmin:
    'Moving an installation is done by an administrator of the installation. Your account has no administrator flag.',
  close: 'Close',
  cancel: 'Cancel',

  export: {
    title: 'Export',
    intro:
      'One JSON file with every table of this installation: tasks, cases, projects, people and the hashes of their passwords and tokens. Keep it private — anyone holding it can bring it up as this installation, on another machine.',
    tutorialLeftOut:
      'The tutorial project START stays out of the archive: the other installation seeds its own.',
    action: 'Download archive',
    pending: 'Preparing the archive…',
  },

  import: {
    title: 'Import',
    intro:
      'Brings up here an archive exported from another installation and replaces all data of this one with it. It works while this installation has no projects of its own. The tutorial project START, which the installation seeds for itself, does not count.',
    fileLabel: 'Archive file',
    // Своя кнопка выбора файла вместо подписи браузера (UI-140): та говорит на языке
    // браузера, а не интерфейса.
    choose: 'Choose a file',
    noFile: 'No file chosen',
    action: 'Import',
    confirmTitle: 'Replace this installation with the archive?',
    confirmIntro: 'Every table this installation has is about to be replaced.',
    warning:
      'This cannot be undone: the data this installation has now — if it has any — is gone the moment the import succeeds.',
    confirm: 'Import, replacing everything',
    pending: 'Importing…',

    result: {
      label: 'Import result',
      done: 'Archive imported.',
      revisionFrom: 'Archive taken at revision',
      revisionTo: 'Brought up to',
      machineKeys: "This machine's own keys that survived",
      noMachineKeys: 'none',
      revokedSourceKeys: 'Keys of the same names from the source, revoked here',
      replaced: 'Lost to the archive from before the import',
      replacedCounts: '{{participants}} participants, {{tokens}} tokens, {{accounts}} accounts',
      tables: 'Rows per table, now in this installation',
    },
  },
} as const;
