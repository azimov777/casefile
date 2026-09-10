/** Экран входа: заголовок, поле токена, кнопка и объяснение просроченного сеанса. */
export const login = {
  title: 'Tracker',
  intro: 'Watching over the tasks that agents run, and answering their questions.',
  expired:
    'The session is over: the server no longer accepts the saved token. Enter the token again.',
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
} as const;
