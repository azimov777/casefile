/** Экран входа: заголовок, поле токена или почта с паролем учётной записи, кнопка и объяснение просроченного сеанса. */
export const login = {
  title: 'Casefile',
  intro: 'Watching over the tasks that agents run, and answering their questions.',
  // «Этот», а не «сохранённый»: сюда приводит и отказ по ключу, который отдала сама
  // установка, а его никто не сохранял и не вводил.
  expired: 'The session is over: the server no longer accepts this token. Enter the token again.',
  tokenLabel: 'Participant token',
  // Подсказка формата, а не перевод: `trk_` — начало настоящего токена на любом языке.
  tokenPlaceholder: 'trk_...',
  // Команда стоит внутри фразы, поэтому она размечена, а не приклеена по краям:
  // порядок слов у языков разный, и склейка `t('a') + <code/> + t('b')` переставится
  // неверно (`<Trans>`, см. `docs/notes/ui.md`).
  tokenHint:
    'The token is printed by <cmd>docker compose run --rm init</cmd> in the backend repository. It is kept in this browser only and goes to the server in a header.',
  submit: 'Sign in',
  submitting: 'Checking…',
  // Режим входа по учётным записям (`TRK-113`): у каждого своя почта и свой пароль.
  signInIntro: 'Sign in with your email and password.',
  emailLabel: 'Email',
  passwordLabel: 'Password',
  passwordHint:
    'An administrator of this installation creates accounts. Forgot the password — ask them to reset it.',
  // `details.reason: wrong_credentials` — wrong email and wrong password are
  // indistinguishable on purpose: the answer must not tell which addresses exist.
  credentialsWrong: 'The email or the password did not match.',
  // `details.reason: account_disabled` — told only after the right password.
  accountDisabled: 'This account is disabled. Ask an administrator of the installation.',
  // General text: `details.scope` is unknown to the interface, or absent (`UI-121`).
  throttled: 'Too many failed attempts. Try again in {{seconds}} s.',
  // `details.scope: "address"` — the window is spent on attempts from this device.
  throttledAddress: 'Too many failed attempts from this device. Try again in {{seconds}} s.',
  // `details.scope: "account"` — failures on this email from every address: someone is
  // trying to guess this account's password, not necessarily from here.
  throttledAccount:
    'Too many failed attempts for this email. Sign-in for it opens again in {{seconds}} s.',
  // `details.scope: "installation"` — the installation-wide ceiling is spent: passwords are
  // being tried from many addresses at once, and this is not your mistake.
  throttledInstallation:
    'The installation is being brute-forced from many addresses at once — this is not your mistake. Sign-in opens again in {{seconds}} s.',
  signInExpired: 'The session is over. Sign in again.',
} as const;
