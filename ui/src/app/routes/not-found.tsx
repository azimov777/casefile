import { useTranslation } from 'react-i18next';
import { Callout } from '@/shared/ui';

export function NotFound() {
  const { t } = useTranslation('ui');

  return (
    <main>
      <h1>{t('app.notFound.title')}</h1>
      <Callout>{t('app.notFound.text')}</Callout>
    </main>
  );
}
