import type { Setting } from '../api/settings';

/** Единица, в которой человеку удобно читать и вписывать значение. */
export interface Unit {
  /** Ключ подписи в `settings:units`. */
  id: UnitId;
  /** Во сколько единиц канонического значения она укладывается. */
  factor: number;
}

export type UnitId =
  | 'bytes'
  | 'chars'
  | 'count'
  | 'days'
  | 'hours'
  | 'kilobytes'
  | 'megabytes'
  | 'minutes'
  | 'seconds';

const DURATION: readonly Unit[] = [
  { id: 'seconds', factor: 1 },
  { id: 'minutes', factor: 60 },
  { id: 'hours', factor: 3600 },
  { id: 'days', factor: 86_400 },
];

const COUNT: readonly Unit[] = [{ id: 'count', factor: 1 }];

/**
 * Единицы по имени настройки. Каноническое значение — число в единицах реестра
 * (`app/domain/installation_settings.py`): у срока сеанса это часы, у срока подключения
 * — секунды, у предела файла — байты. Настройки, которой здесь нет, показывается числом.
 */
const UNITS: Record<string, readonly Unit[]> = {
  session_hours: [
    { id: 'hours', factor: 1 },
    { id: 'days', factor: 24 },
  ],
  oauth_access_ttl: DURATION,
  mcp_page_size: COUNT,
  mcp_text_limit: [{ id: 'chars', factor: 1 }],
  file_max_bytes: [
    { id: 'bytes', factor: 1 },
    { id: 'kilobytes', factor: 1024 },
    { id: 'megabytes', factor: 1024 * 1024 },
  ],
  file_unopened_days: [{ id: 'days', factor: 1 }],
};

export function unitsOf(name: string): readonly Unit[] {
  return UNITS[name] ?? COUNT;
}

const DURATION_SECONDS = /^PT(\d+)S$/;

/**
 * Каноническая строка в число единиц реестра: `168` → 168, `PT2592000S` → 2592000.
 * `null`, если вид незнакомый: тогда экран показывает строку как есть, а не выдумывает.
 */
export function parseCanonical(setting: Pick<Setting, 'kind'>, text: string): number | null {
  if (setting.kind === 'boolean') return null;
  const match = setting.kind === 'duration' ? DURATION_SECONDS.exec(text) : /^\d+$/.exec(text);
  if (match === null) return null;
  const number = Number(setting.kind === 'duration' ? match[1] : match[0]);
  return Number.isSafeInteger(number) ? number : null;
}

/**
 * Самая крупная единица, в которую число укладывается без остатка: 25 МБ, а не
 * 26 214 400 Б; 30 дн., а не 43 200 мин.
 */
export function splitAmount(name: string, value: number): { amount: number; unit: Unit } {
  const units = unitsOf(name);
  const fit = [...units].reverse().find((unit) => value % unit.factor === 0);
  const unit = fit ?? units[0] ?? { id: 'count' as const, factor: 1 };
  return { amount: value / unit.factor, unit };
}

/**
 * Сколько единиц и какая выбрана в окне правки, когда ввод пуст — по действующему
 * значению. `null`, если значение не число (логическое или незнакомое).
 */
export function amountOf(setting: Setting, canonical: string = setting.effective_value) {
  const value = parseCanonical(setting, canonical);
  return value === null ? null : splitAmount(setting.name, value);
}

/**
 * Введённое число в единицах `unit` — в каноническую строку для `PATCH`. `null`, если
 * введено не целое неотрицательное число: такое значение до сервера не доходит.
 */
export function toCanonical(
  setting: Pick<Setting, 'kind'>,
  amount: string,
  unit: Unit,
): string | null {
  const text = amount.trim();
  if (!/^\d{1,15}$/.test(text)) return null;
  const value = Number(text) * unit.factor;
  if (!Number.isSafeInteger(value)) return null;
  return setting.kind === 'duration' ? `PT${value}S` : String(value);
}
