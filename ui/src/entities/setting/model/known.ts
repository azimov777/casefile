/** Имена семи настроек реестра: от них зависят ключи подписей. */
const KNOWN = [
  'session_hours',
  'oauth_access_ttl',
  'mcp_page_size',
  'mcp_text_limit',
  'release_check',
  'file_max_bytes',
  'file_unopened_days',
] as const;

export type KnownSettingName = (typeof KNOWN)[number];

export function isKnownSetting(name: string): name is KnownSettingName {
  return (KNOWN as readonly string[]).includes(name);
}
