import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, RelativeTime, type BadgeTone } from '@/shared/ui';
import type { Setting } from '../api/settings';
import { isKnownSetting } from '../model/known';
import { useFormatAmount } from '../model/use-format-amount';

const SOURCE_TONE: Record<Setting['source'], BadgeTone> = {
  database: 'attention',
  environment: 'progress',
  default: 'neutral',
};

/**
 * Одна настройка карточкой: название, что она меняет и когда вступает в силу, значение
 * и откуда оно взято, умолчание, кто и когда менял. Правку рисует тот, кому она
 * разрешена, — слотом `actions`: у остальных поля ввода нет вовсе.
 */
export function SettingItem({ setting, actions }: { setting: Setting; actions?: ReactNode }) {
  const { t } = useTranslation('settings');
  const format = useFormatAmount();
  const known = isKnownSetting(setting.name) ? setting.name : null;
  const author = setting.updated_by?.signature ?? null;

  return (
    <article
      aria-label={known === null ? setting.name : t(`items.${known}.title`)}
      data-setting={setting.name}
      className="flex min-w-0 flex-col gap-3 rounded-control border border-line bg-surface p-3"
    >
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="text-screen">{known === null ? setting.name : t(`items.${known}.title`)}</h2>
        {known !== null ? (
          <p className="max-w-(--ui-text-max) text-meta text-muted">{t(`items.${known}.hint`)}</p>
        ) : null}
      </div>

      <dl className="grid min-w-0 gap-x-4 gap-y-1 text-body sm:grid-cols-[max-content_1fr]">
        <dt className="text-meta text-muted">{t('row.value')}</dt>
        <dd className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-medium" data-role="value">
            {format(setting, setting.effective_value)}
          </span>
          <Badge tone={SOURCE_TONE[setting.source]}>
            <span data-role="source">{t(`sources.${setting.source}`)}</span>
          </Badge>
        </dd>

        <dt className="text-meta text-muted">{t('row.default')}</dt>
        <dd className="min-w-0 wrap-anywhere text-meta text-muted" data-role="default">
          {format(setting, setting.default_value)} —{' '}
          {setting.default_source === 'environment'
            ? t('row.defaultFromEnv', { name: setting.env_var })
            : t('row.defaultFromCode')}
        </dd>

        <dt className="text-meta text-muted">{t('row.changed')}</dt>
        <dd className="min-w-0 text-meta text-muted" data-role="changed">
          {setting.updated_at === null ? (
            t('row.neverChanged')
          ) : (
            <>
              {author === null ? t('row.changedByTracker') : t('row.changedBy', { author })}{' '}
              <RelativeTime value={setting.updated_at} />
            </>
          )}
        </dd>
      </dl>

      {actions}
    </article>
  );
}
