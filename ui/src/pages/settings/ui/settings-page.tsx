import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { SettingForm } from '@/features/manage-settings';
import { SettingItem, settingsQueryOptions } from '@/entities/setting';
import { bootstrapQueryOptions } from '@/entities/session';
import { Callout, QueryState } from '@/shared/ui';

/**
 * Экран «Настройки»: семь параметров установки со значением, откуда оно взято, умолчанием
 * и тем, кто и когда менял (TRK-749, слово владельца TRK~31#4).
 *
 * Видят все вошедшие; правит и сбрасывает только администратор — решает флаг из первого
 * кадра (`bootstrap.account.is_admin`), а не отказ `403`: остальным поля ввода и кнопок
 * не показываются вовсе (TRK/ui-screens#2). На своей машине владелец — администратор
 * (`owner@localhost`), поэтому правка ему доступна без ввода; экран не закрыт режимом
 * входа (TRK/ui-screens#47).
 */
export function SettingsPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const admin = bootstrap.data?.account?.is_admin === true;
  const settings = useQuery(settingsQueryOptions());
  const { t } = useTranslation('settings');
  const { t: brick } = useTranslation('ui');

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-title">{brick('app.settings')}</h1>
        <p className="max-w-(--ui-text-max) text-body text-muted">{t('intro')}</p>
      </div>

      <QueryState query={bootstrap} loading={t('loadingMe')} compact />

      {/* Пока флаг неизвестен, не говорится ничего: «менять нельзя» о неизвестном — выдумка. */}
      {bootstrap.data === undefined || admin ? null : <Callout>{t('readOnly')}</Callout>}

      <QueryState query={settings} loading={t('loading')} />

      {settings.data === undefined ? null : (
        <div className="flex min-w-0 flex-col gap-3">
          {settings.data.map((setting) => (
            <SettingItem
              key={setting.name}
              setting={setting}
              actions={
                admin ? (
                  <SettingForm
                    // Новое значение с сервера пересобирает форму: черновик берётся заново.
                    key={`${setting.effective_value}|${setting.value ?? ''}|${setting.updated_at ?? ''}`}
                    setting={setting}
                  />
                ) : null
              }
            />
          ))}
        </div>
      )}
    </main>
  );
}
