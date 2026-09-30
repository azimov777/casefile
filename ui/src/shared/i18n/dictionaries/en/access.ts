/**
 * Экран «Доступы»: подключения агентов, ключи агентов, сеансы входа; заведение агента,
 * выпуск и отзыв.
 *
 * Подписи самой строки доступа живут в `ui.token`: строку рисует представление
 * сущности (`entities/token`), а не экран. Фрагменты подключения подписаны там же,
 * где у экрана «Подключить агента», — `ui.snippets`.
 */
export const access = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    body: 'Everything that gets into the installation is here: agents that signed in by themselves (Claude Code and Codex), agent keys and the sign-in sessions of people. What is no longer needed is disconnected or revoked right here.',
  },
  intro:
    'Every access to this installation in three sections: agent connections, their keys and sign-in sessions. Accesses are never deleted — an access is taken away by disconnecting or revoking it, and the one taken away stays here as history.',
  close: 'Close',
  introMine:
    'Your accesses: agents you connected or issued a key to, and your sign-in sessions. Nobody else’s are here — an administrator sees every access of the installation. Accesses are never deleted: they are taken away, and the one taken away stays here as history.',

  view: {
    label: 'Whose accesses are shown',
    all: 'All accesses of the installation',
    mine: 'Mine',
  },
  cancel: 'Cancel',

  actions: {
    intro:
      'A key is for an agent that does not sign in by itself: a harness without OAuth and the journal watcher between sessions. Claude Code and Codex sign in by themselves — they need no key. A key is issued to an agent or a shared one: people get no keys, a person signs in to the interface.',
    newAgent: 'Register an agent',
    issue: 'Issue a key',
  },

  closed: {
    loading: 'Asking the installation who is behind this session…',
    noAccount:
      'Issuing is closed: this session runs on an agent’s key, and only a person with an account of their own issues keys and registers agents — otherwise a key issued by an agent would belong to nobody and outlive the disabling of whoever gave it. This session can still revoke its own keys.',
  },

  loading: 'Reading the accesses…',
  loadingMore: 'Reading the rest of the accesses…',

  connections: {
    title: 'Connections',
    count_one: '{{count, number}} connection',
    count_other: '{{count, number}} connections',
    intro:
      'Agents that signed in by themselves through OAuth: the client, the participant, who connected it, when it signed in and when it last called. You have not seen and will not see a secret. “Disconnect” closes the access at once and cuts its renewal — the client has to sign in again.',
    empty:
      'No agent has signed in by itself yet. Claude Code and Codex sign in through OAuth: adding the MCP address to the client is enough — the details are on the “Connect an agent” screen.',
    emptyMine:
      'You have not connected an agent yet. Claude Code and Codex sign in by themselves when you add the MCP address to the client.',
  },

  keys: {
    title: 'Agent keys',
    count_one: '{{count, number}} key',
    count_other: '{{count, number}} keys',
    intro:
      'Static secrets for harnesses without OAuth and for the journal watcher. Each one shows which agent it speaks for and who issued it. Revoking closes a key at once.',
    empty: 'There are no active agent keys. Issue one if an agent does not sign in by itself.',
    emptyMine:
      'You have no agent keys yet. Issue one here — and get a ready connection line right away.',
  },

  history: {
    count_one: 'History: {{count, number}} access taken away',
    count_other: 'History: {{count, number}} accesses taken away',
    intro:
      'A disconnected connection and a revoked key let no request in anymore. Their records are not deleted: they show who used them and when.',
  },

  sessions: {
    title: 'Sign-in sessions',
    count_one: '{{count, number}} session',
    count_other: '{{count, number}} sessions',
    intro:
      'Sign-ins of a person to the interface: with email and password, and the “this computer” key that the installation hands to the interface on its own machine. A session lives until it ends or is revoked — revoking signs that device out of the interface. Sessions that have ended are not shown here.',
  },

  denied: {
    account_required:
      'Only a person with an account of their own can issue keys: this session runs on an agent’s key.',
    foreign_human:
      'Only an administrator issues a key on behalf of another person. Issue a key to your agent, or a shared agent one.',
    not_own_token:
      'This is not your access: only an administrator of the installation revokes someone else’s.',
  },

  agent: {
    title: 'Register an agent',
    intro:
      'A participant of the registry: its name is the signature under its entries in cases, and it cannot be changed afterwards. The agent stays yours: you issue its keys.',
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
    done: 'The participant {{name}} is registered. Unless it signs in by itself, it cannot connect without a key: the key is issued separately, and its secret is shown once.',
    issueNow: 'Issue a key to it',
  },

  issue: {
    title: 'Issue a key',
    intro:
      'The secret is shown once, right here, together with the fragments for connecting a client.',
    whomLabel: 'Who the key speaks for',
    whomUnset: '— not chosen —',
    whomShared: 'Shared key, with no participant',
    whomHint:
      'Entries made with this key are signed with the name of that agent. People get no keys.',
    ownerOf: 'owner {{owner}}',
    sharedHint:
      'A shared key names nobody by itself: every request with it carries the X-Actor-Label header with the label of a temporary agent, and the label becomes the signature.',
    whomEmpty:
      'It is not chosen whom the key speaks for, and that choice decides how its entries are signed.',
    loadingParticipants: 'Reading the participants…',
    nameLabel: 'Name of the key',
    namePlaceholder: 'nightly_agent on the laptop',
    nameHint:
      'Free-form: this is what tells the key from its neighbours when one of them is being revoked.',
    nameEmpty: 'A key with no name cannot be told from its neighbours in the list.',
    nameRule:
      'The name is a line of free-form text, and the tracker takes it up to 255 characters.',
    submit: 'Issue',
    pending: 'Issuing…',
    retrySafe:
      'Sending it again will not issue a second key: the attempt keeps the same idempotency key.',
  },

  secret: {
    title: 'The key {{name}} is issued',
    intro: 'This is the only time the secret is visible.',
    onlyOnce:
      'Copy the secret now: there is no second showing. The tracker keeps only its hash, and no request — neither here nor through the API — reads it back.',
    forParticipant:
      'The key speaks for {{participant}}: entries made with it are signed with that name.',
    forShared:
      'The key has no participant: every request with it carries the X-Actor-Label header, and that label signs the entries.',
    tokenLabel: 'Key secret',
    tokenCaption: 'Token secret, shown once',
    loadingAddress: 'Reading the MCP address…',
    done: 'I have saved the secret',
  },

  revoke: {
    action: 'Revoke',
    title: 'Revoke the access {{name}}?',
    intro:
      'A revoked access stops letting any request through, and it cannot be brought back: an agent that worked with it needs a new one. The record stays in the list as history.',
    ownKey:
      'This is the key the interface itself works with. Its next request will be refused and the session will end. A key handed out by the installation is reissued only when the installation is brought up again, and the tab has to be reloaded after that.',
    confirm: 'Revoke',
    pending: 'Revoking…',
  },

  disconnect: {
    action: 'Disconnect',
    title: 'Disconnect {{name}}?',
    intro:
      'The client stops getting into the installation at once, and cannot renew its sign-in: it has to sign in again. The record of the connection stays in the list as history.',
    confirm: 'Disconnect',
    pending: 'Disconnecting…',
  },
} as const;
