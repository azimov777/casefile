/** Экран входа: заголовок, поле токена или пароля установки, кнопка и объяснение просроченного сеанса. */
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
  // Установка, закрытая паролем владельца (`TRK-90`): имени нет, пароль у неё один.
  passwordIntro: 'This installation is locked with the owner password.',
  passwordLabel: 'Installation password',
  passwordHint:
    'The owner of the installation knows the password. After signing in, the installation hands the key to the browser itself — no token to enter.',
  passwordWrong: 'The password did not match.',
  // General text: `details.scope` is unknown to the interface, or absent (`UI-121`).
  passwordThrottled: 'Too many failed attempts. Try again in {{seconds}} s.',
  // `details.scope: "address"` (`TRK-98`) — the window is spent on attempts from this
  // device; every other address still gets its password checked.
  passwordThrottledAddress:
    'Too many failed attempts from this device. Try again in {{seconds}} s.',
  // `details.scope: "installation"` — the installation-wide ceiling is spent: the
  // password is being tried from many addresses at once, and this is not the owner's
  // mistake.
  passwordThrottledInstallation:
    'The installation is being brute-forced from many addresses at once — this is not your mistake. Sign-in opens again in {{seconds}} s.',
  passwordExpired: 'The session is over. Sign in with the password again.',
} as const;
