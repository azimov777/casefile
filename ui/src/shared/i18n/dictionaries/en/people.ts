/**
 * Экран «Люди» (`TRK-113`): учётные записи установки и управление ими администратором.
 *
 * Подписи самой карточки учётной записи живут в `ui.account`: её рисует представление
 * сущности (`entities/account`), а не экран.
 */
export const people = {
  intro:
    'Who can sign in to this installation. Everyone signed in sees every task; the administrator flag opens only this screen. Nobody is ever deleted: an account is disabled, and the entries the person made stay signed with their name.',
  loadingMe: 'Asking the installation who you are…',
  notAdmin:
    'People are managed by an administrator of the installation. Your account has no administrator flag.',
  close: 'Close',
  cancel: 'Cancel',

  list: {
    title: 'Accounts',
    intro:
      'Disabled accounts stay in the list: the entries of these people are still signed with their names.',
    loading: 'Reading the accounts…',
    empty: 'The installation has no accounts yet.',
    more: 'Show more',
    loadingMore: 'Loading…',
  },

  create: {
    open: 'Add a person',
    title: 'Add a person',
    intro:
      'The person will sign in with this email and password. The tracker sends no mail: hand the password over yourself.',
    emailLabel: 'Email',
    emailEmpty: 'Enter the email the person will sign in with.',
    nameLabel: 'Name',
    namePlaceholder: 'alice',
    nameHint:
      'Signs every entry the person makes and cannot be changed later. Latin letters, digits and underscores, starting with a letter.',
    nameEmpty: 'Enter the name that will sign the person’s entries.',
    nameRule:
      'The name is Latin letters, digits and underscores, from 2 to 64 characters, starting with a letter.',
    admin: 'Administrator: can add, disable and reset passwords of other people',
    submit: 'Add',
    pending: 'Adding…',
  },

  password: {
    legend: 'Password',
    generate: 'Generate — the tracker makes one up and shows it once',
    type: 'Type it in myself',
    label: 'New password',
    hint: 'At least 12 characters.',
    empty: 'Type the password, or let the tracker generate one.',
  },

  once: {
    createdTitle: 'Account {{email}} is ready',
    resetTitle: 'New password for {{email}}',
    intro: 'Hand these over to the person: they sign in with them on this installation.',
    onlyOnce:
      'The password is shown only now. The installation keeps only its hash — once this window is closed, nobody can see it again; only another reset helps.',
    emailLabel: 'Email',
    emailCaption: 'The sign-in name.',
    passwordLabel: 'Password',
    passwordCaption: 'The person can change it on the “My account” screen.',
    done: 'I have saved it',
  },

  reset: {
    action: 'Reset password',
    title: 'Reset the password of {{email}}?',
    intro:
      'Every session of this person ends at their next request: they will sign in again with the new password.',
    confirm: 'Reset',
    pending: 'Resetting…',
  },

  disable: {
    action: 'Disable',
    title: 'Disable {{email}}?',
    intro:
      'The person will no longer sign in, and every token of theirs is revoked — sessions and the tokens issued to their agents alike. Their entries stay signed with their name. Enabling the account later lets them sign in again, but revoked tokens stay revoked.',
    confirm: 'Disable',
    pending: 'Saving…',
  },

  enable: {
    action: 'Enable',
    title: 'Enable {{email}}?',
    intro:
      'The person will sign in again with their password. Tokens revoked when the account was disabled stay revoked.',
    confirm: 'Enable',
  },
} as const;
