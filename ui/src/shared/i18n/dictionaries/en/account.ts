/** Экран «Моя учётная запись» (`TRK-113`): кто я на установке и смена своего пароля. */
export const account = {
  intro: 'The account you are signed in with on this installation.',
  loading: 'Asking the installation who you are…',
  none: 'This session runs on a token without an account: there is no password to change here.',
  email: 'Email',
  signs: 'Signs entries as',
  role: 'Role',
  member: 'member',
  password: {
    title: 'Password',
    intro: 'Changing the password ends your sessions in other browsers; this one keeps working.',
    currentLabel: 'Current password',
    newLabel: 'New password',
    newHint: 'At least 12 characters.',
    repeatLabel: 'New password again',
    mismatch: 'The two new passwords differ.',
    submit: 'Change password',
    pending: 'Changing…',
    changed: 'The password is changed. Sessions in other browsers are over.',
  },
} as const;
