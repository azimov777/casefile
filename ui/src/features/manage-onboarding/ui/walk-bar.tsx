import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Button } from '@/shared/ui';
import { walkHref, type WalkStep } from '../model/walk-steps';

interface WalkBarProps {
  /** Номер текущего шага с 1. */
  step: number;
  steps: WalkStep[];
}

/**
 * Полоса прохода над пояснением (TRK-364): счётчик «Шаг N из total» и три ссылки —
 * «Назад», «Далее», «Закончить». Ссылки, а не кнопки с обработчиком: шаг — обычный
 * переход, номер живёт в адресе. «Назад» на первом шаге не запрещена, а отсутствует:
 * назад некуда. «Далее» и «Закончить» на последнем шаге ведут на `/start`.
 * Ничего не пишет на сервер: ни скрытие пояснений, ни состояние знакомства проход не меняет.
 */
export function WalkBar({ step, steps }: WalkBarProps) {
  const { t } = useTranslation('ui');
  const total = steps.length;
  const previous = steps[step - 2];
  const next = steps[step];

  return (
    <div
      role="group"
      aria-label={t('walk.label')}
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-mark border border-accent bg-accent-soft px-4 py-2 text-body text-text"
    >
      <span className="font-semibold">{t('walk.counter', { n: step, total })}</span>
      <div className="flex flex-wrap gap-2">
        {previous === undefined ? null : (
          <Button asChild tone="quiet" size="sm">
            <Link to={walkHref(previous, step - 1)}>{t('walk.back')}</Link>
          </Button>
        )}
        <Button asChild tone="quiet" size="sm">
          <Link to={next === undefined ? '/start' : walkHref(next, step + 1)}>
            {t('walk.next')}
          </Link>
        </Button>
        <Button asChild size="sm">
          <Link to="/start">{t('walk.finish')}</Link>
        </Button>
      </div>
    </div>
  );
}
