import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { useOnboardingHints } from '../model/use-onboarding-hints';
import { useUpdateOnboarding } from '../model/use-update-onboarding';

/**
 * «Показать пояснения снова» на экране «Начало» (`TRK-362`): возвращает пояснения
 * экранов, скрытые целиком (`hidden_all`) или по одному (`hidden`), к пустому
 * состоянию — тому же, с которым знакомство начинается у новой учётной записи.
 *
 * Видно, только когда есть что возвращать: `hidden_all` истинно или `hidden` не
 * пуст. Ничего не скрыто — действия на экране нет вовсе, а не запрещённая кнопка.
 */
export function RestoreHintsAction() {
  const account = useOnboardingHints();
  const update = useUpdateOnboarding();
  const { t } = useTranslation('ui');

  if (account === null) return null;

  const { hidden_all, hidden } = account.onboarding.hints;
  if (!hidden_all && hidden.length === 0) return null;

  return (
    <Button
      tone="quiet"
      onClick={() =>
        update.mutate({
          accountId: account.id,
          update: { hints: { hidden_all: false, hidden: [] } },
        })
      }
      disabled={update.isPending}
    >
      {t('explanation.showAgain')}
    </Button>
  );
}
