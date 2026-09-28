import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Button } from '@/shared/ui';
import { useOnboardingHints } from '../model/use-onboarding-hints';
import { useWalkPlan } from '../model/use-walk';
import { walkHref } from '../model/walk-steps';

/**
 * «Пройти по экранам» на экране «Начало» (TRK-364): ведёт на первый шаг прохода.
 *
 * Человеку без учётной записи кнопки нет: пояснений у него нет (`TRK-360#17`), а
 * проход состоит из них. Пока план не прочитан — ни кнопки, ни заглушки: счётчик на
 * первом шаге должен назвать верное число шагов.
 */
export function StartWalkAction() {
  const account = useOnboardingHints();
  const plan = useWalkPlan();
  const { t } = useTranslation('ui');

  const first = plan.steps[0];
  if (account === null || !plan.ready || first === undefined) return null;

  return (
    <Button asChild>
      <Link to={walkHref(first, 1)} className="no-underline">
        {t('walk.start')}
      </Link>
    </Button>
  );
}
