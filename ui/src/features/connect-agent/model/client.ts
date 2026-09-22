/**
 * Клиент, под который показаны фрагменты подключения. Выбор — вид экрана, а не форма:
 * он живёт в адресе (`?client=codex`), как любой вид (`docs/CONVENTIONS.md`,
 * «Состояние»), и переключается ссылками `SegmentedNav`.
 *
 * Порядок — порядок дорожки: первым тот клиент, которым подключаются чаще всего, и он же
 * умолчание, поэтому адрес без параметра показывает его и лишнего параметра не несёт.
 */
export const CLIENTS = ['claude-code', 'codex', 'json', 'any'] as const;

export type Client = (typeof CLIENTS)[number];

/** Параметр адреса, в котором живёт выбранный клиент. */
export const CLIENT_PARAM = 'client';

export const DEFAULT_CLIENT: Client = 'claude-code';

/** Клиент из значения параметра: незнакомое и пустое значение — умолчание. */
export function parseClient(value: string | null): Client {
  return CLIENTS.find((client) => client === value) ?? DEFAULT_CLIENT;
}

/**
 * Параметры адреса с выбранным клиентом: прочие параметры (`shared`) остаются как были,
 * а умолчание параметра не пишет вовсе — у одного вида не бывает двух адресов.
 */
export function withClient(params: URLSearchParams, client: Client): URLSearchParams {
  const updated = new URLSearchParams(params);
  if (client === DEFAULT_CLIENT) updated.delete(CLIENT_PARAM);
  else updated.set(CLIENT_PARAM, client);
  return updated;
}
