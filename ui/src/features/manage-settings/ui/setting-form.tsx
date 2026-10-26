import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Input } from '@/shared/ui';
import {
  amountOf,
  isKnownSetting,
  toCanonical,
  unitsOf,
  useFormatAmount,
  type Setting,
} from '@/entities/setting';
import { useUpdateSetting } from '../model/use-update-setting';

/** Те же рамка и фокус, что у `Input`: выпадающий список единицы — родной, а не Radix. */
const SELECT_CLASS =
  'rounded-mark border border-line-strong bg-surface px-3 py-2 text-body text-text ' +
  'enabled:hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 ' +
  'focus-visible:outline-focus';

/**
 * Правка одной настройки: число с единицей или выбор «включена / выключена», «Сохранить»
 * и, пока в базе что-то лежит, «Брать из окружения». Рисуется только администратору —
 * решает флаг из первого кадра, а не отказ `403` (TRK/ui-screens#2).
 *
 * Отказ сервера показывается рядом с полем, а черновик остаётся: человек поправляет
 * число, а не вписывает его заново. Прежнее значение карточка не теряет — кэш меняется
 * только удачным ответом.
 */
export function SettingForm({ setting }: { setting: Setting }) {
  const { t } = useTranslation('settings');
  const format = useFormatAmount();
  const update = useUpdateSetting(setting.name);
  const units = unitsOf(setting.name);
  const initial = amountOf(setting);

  const [amount, setAmount] = useState(initial === null ? '' : String(initial.amount));
  const [unitId, setUnitId] = useState(initial?.unit.id ?? units[0]?.id ?? 'count');
  const [flag, setFlag] = useState(setting.effective_value === 'true' ? 'true' : 'false');
  const [local, setLocal] = useState<'notInteger' | null>(null);
  const inputId = useId();
  const errorId = useId();

  const boolean = setting.kind === 'boolean';
  const unit = units.find((candidate) => candidate.id === unitId) ?? units[0];
  const reason = update.error instanceof ApiError ? update.error.details.reason : undefined;
  const complaint = local !== null || (update.error !== null && update.error !== undefined);

  function rejection(): string | null {
    if (local === 'notInteger') return t('errors.not_an_integer');
    if (update.error === null || update.error === undefined) return null;
    if (
      update.error instanceof ApiError &&
      update.error.code === 'installation_setting_invalid' &&
      (reason === 'too_small' || reason === 'too_large') &&
      setting.minimum !== null &&
      setting.maximum !== null
    ) {
      return t('errors.out_of_range', {
        min: format(setting, setting.minimum),
        max: format(setting, setting.maximum),
      });
    }
    if (
      update.error instanceof ApiError &&
      update.error.code === 'installation_setting_invalid' &&
      (reason === 'not_an_integer' || reason === 'not_a_boolean' || reason === 'not_a_duration')
    ) {
      return t(`errors.${reason}`);
    }
    return errorMessage(update.error);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocal(null);
    update.reset();
    if (boolean) {
      await update.mutateAsync(flag).catch(() => undefined);
      return;
    }
    if (unit === undefined) return;
    const canonical = toCanonical(setting, amount, unit);
    if (canonical === null) {
      setLocal('notInteger');
      return;
    }
    await update.mutateAsync(canonical).catch(() => undefined);
  }

  async function reset() {
    setLocal(null);
    update.reset();
    await update.mutateAsync(null).catch(() => undefined);
  }

  const message = rejection();
  const known = isKnownSetting(setting.name) ? setting.name : null;
  const name = known === null ? setting.name : t(`items.${known}.title`);

  return (
    <form
      className="flex flex-col gap-2 border-t border-line pt-3"
      onSubmit={(event) => void save(event)}
      noValidate
      aria-label={t('form.label', { name })}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <label className="text-meta text-muted" htmlFor={inputId}>
            {t('form.newValue')}
          </label>
          {boolean ? (
            <select
              id={inputId}
              value={flag}
              onChange={(event) => setFlag(event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="true">{t('boolean.on')}</option>
              <option value="false">{t('boolean.off')}</option>
            </select>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={inputId}
                type="text"
                inputMode="numeric"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                className="w-32"
                aria-invalid={complaint}
                aria-describedby={message === null ? undefined : errorId}
              />
              {units.length > 1 ? (
                <select
                  aria-label={t('form.unit')}
                  value={unitId}
                  onChange={(event) => {
                    const next = units.find((candidate) => candidate.id === event.target.value);
                    setUnitId(next?.id ?? unitId);
                  }}
                  className={SELECT_CLASS}
                >
                  {units.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {t(`units.${candidate.id}`)}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-meta text-muted">
                  {t(`units.${units[0]?.id ?? 'count'}`)}
                </span>
              )}
            </div>
          )}
        </div>

        <Button type="submit" disabled={update.isPending}>
          {t('form.save')}
        </Button>
        {setting.value === null ? null : (
          <Button
            type="button"
            tone="quiet"
            disabled={update.isPending}
            onClick={() => void reset()}
          >
            {t('form.reset')}
          </Button>
        )}
      </div>

      {message === null ? null : (
        <span id={errorId} className="text-meta text-danger" role="alert">
          {message}
        </span>
      )}
    </form>
  );
}
