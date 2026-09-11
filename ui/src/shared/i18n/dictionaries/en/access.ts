/**
 * Экран «Доступы»: список токенов установки, заведение агента, выпуск и отзыв.
 *
 * Подписи самой строки доступа живут в `ui.token`: строку рисует представление
 * сущности (`entities/token`), а не экран. Фрагменты подключения подписаны там же,
 * где у экрана «Подключить агента», — `ui.snippets`.
 */
export const access = {
  intro:
    'Every access to this installation: whose key it is, what it opens, who issued it and when it was last used. Tokens are never deleted — an access is taken away by revoking it, and the revoked one stays here as history.',
  close: 'Close',
  cancel: 'Cancel',

  actions: {
    title: 'New access',
    intro:
      'An agent of its own gets a participant and a token: then its entries in cases are signed with its name rather than with the shared agent of this machine. A token issued without a participant is a shared agent token — every request with it signs itself with a label instead.',
    newAgent: 'Register an agent',
    issue: 'Issue a token',
  },

  closed: {
    loading: 'Asking the installation what this session’s key opens…',
    text: 'Writing is closed: this session runs on a key of the {{scope}} scope, and registering participants, issuing and revoking tokens take a key of the main scope. A local installation hands the interface such a key by itself; a key entered on the sign-in screen is whatever it was issued as.',
  },

  tokens: {
    title: 'Tokens of the installation',
    intro: 'The list is visible with any key: reading tokens is open to the task scope as well.',
    loading: 'Reading the accesses…',
    empty:
      'The installation has no tokens at all — that happens only before the first one is issued.',
    more: 'Show more',
    loadingMore: 'Loading…',
  },

  agent: {
    title: 'Register an agent',
    intro:
      'A participant of the registry: its name is the signature under its entries in cases, and it cannot be changed afterwards.',
    nameLabel: 'Name',
    namePlaceholder: 'nightly_agent',
    nameHint:
      'Latin snake_case. Names are unique regardless of case, and a participant cannot be deleted.',
    nameRule:
      'The name is checked by the tracker: it starts with a latin letter, and goes on with letters, digits and underscores.',
    descriptionLabel: 'Who this is (optional)',
    descriptionPlaceholder: 'The agent that runs the nightly checks',
    submit: 'Register',
    pending: 'Registering…',
    doneIntro: 'The participant is in the registry, and it has no access yet.',
    done: 'The participant {{name}} is registered. Without a token it cannot connect: the token is issued separately, and its secret is shown once.',
    issueNow: 'Issue a token to it',
  },

  issue: {
    title: 'Issue a token',
    intro:
      'The secret is shown once, right here, together with the fragments for connecting a client.',
    whomLabel: 'Who the token speaks for',
    whomUnset: '— not chosen —',
    whomShared: 'Shared agent token, with no participant',
    whomHint: 'Entries made with this token are signed with the name of that participant.',
    sharedHint:
      'A shared token names nobody by itself: every request with it carries the X-Actor-Label header with the label of a temporary agent, and the label becomes the signature.',
    whomEmpty:
      'It is not chosen whom the token speaks for, and that choice decides how its entries are signed.',
    loadingParticipants: 'Reading the participants…',
    scopeLabel: 'Scope: the only right there is in the tracker',
    scopeTaskHint:
      '— the working cycle of an agent: tasks, case entries, questions and answers, and reading everything, this list included.',
    scopeMainHint:
      '— the same plus writing to the registries: registering participants, issuing and revoking tokens, creating and editing queues. Such a key opens the installation whole.',
    nameLabel: 'Name of the token',
    namePlaceholder: 'nightly_agent on the laptop',
    nameHint:
      'Free-form: this is what tells the token from its neighbours when one of them is being revoked.',
    nameEmpty: 'A token with no name cannot be told from its neighbours in the list.',
    nameRule:
      'The name is a line of free-form text, and the tracker takes it up to 255 characters.',
    submit: 'Issue',
    pending: 'Issuing…',
    retrySafe:
      'Sending it again will not issue a second token: the attempt keeps the same idempotency key.',
  },

  secret: {
    title: 'The token {{name}} is issued',
    intro: 'This is the only time the secret is visible.',
    onlyOnce:
      'Copy the secret now: there is no second showing. The tracker keeps only its hash, and no request — neither here nor through the API — reads it back.',
    forParticipant:
      'The token speaks for {{participant}}: entries made with it are signed with that name.',
    forShared:
      'The token has no participant: every request with it carries the X-Actor-Label header, and that label signs the entries.',
    tokenLabel: 'Token secret',
    tokenCaption: 'Token secret, shown once',
    loadingAddress: 'Reading the MCP address…',
    done: 'I have saved the secret',
  },

  revoke: {
    action: 'Revoke',
    title: 'Revoke the token {{name}}?',
    intro:
      'A revoked token stops letting any request through, and it cannot be brought back: an agent that worked with it needs a new one. The record stays in the list as history.',
    ownKey:
      'This is the key the interface itself works with. Its next request will be refused and the session will end. A key handed out by the installation is reissued only when the installation is brought up again, and the tab has to be reloaded after that; a key entered on the sign-in screen cannot be entered again — it takes a different one.',
    confirm: 'Revoke',
    pending: 'Revoking…',
  },
} as const;
