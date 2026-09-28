import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import type { HintKey } from '../model/hint-keys';
import { useOnboardingHints } from '../model/use-onboarding-hints';
import { useUpdateOnboarding } from '../model/use-update-onboarding';
import { useWalk } from '../model/use-walk';
import { WalkBar } from './walk-bar';

interface ExplanationPanelProps {
  /** Ключ этого пояснения (`model/hint-keys.ts`), из `hidden` и в него же при закрытии. */
  hintKey: HintKey;
  /** Текст пояснения: приходит от экрана из его собственного словаря (constraints задачи). */
  children: ReactNode;
}

/**
 * Пояснение экрана — короткий блок «что здесь и что вы тут делаете» при первом
 * открытии (решение владельца `TRK-360#16`, механизм — `TRK-362`).
 *
 * Рисуется, только когда все четыре условия выполнены разом: `bootstrap` уже
 * прочитан, у вошедшего есть учётная запись, `hidden_all` ложно и этот `hintKey` не
 * входит в `hidden`. Первые два условия проверяет `useOnboardingHints` (`null` до
 * этого момента), остальные два — сама панель.
 *
 * Состояние скрытия живёт только на сервере (`TRK-360#17`): в браузере не хранится
 * ничего, и после успешной правки `useUpdateOnboarding` перечитывает `bootstrap`,
 * из-за чего панель сама пропадает без локального состояния «уже закрыто».
 */
export function ExplanationPanel({ hintKey, children }: ExplanationPanelProps) {
  const account = useOnboardingHints();
  const update = useUpdateOnboarding();
  const walk = useWalk();
  const { t } = useTranslation('ui');

  if (account === null) return null;

  // Проход (TRK-364): пояснение шага показано и скрытым, над ним стоит полоса прохода.
  // Скрытие проход не меняет и сам его не предлагает: кнопок закрытия на шаге нет.
  const walking = walk.step !== null && walk.steps[walk.step - 1]?.hintKey === hintKey;

  const { hidden_all, hidden } = account.onboarding.hints;
  if (!walking && (hidden_all || hidden.includes(hintKey))) return null;

  const accountId = account.id;

  function close() {
    // Список скрытых по одному передаётся целиком: прежние ключи плюс новый
    // (constraints задачи) — непереданное бэкенд не трогает, но `hidden` не поле
    // «добавить», а поле «вот так теперь».
    update.mutate({ accountId, update: { hints: { hidden: [...hidden, hintKey] } } });
  }

  function hideAll() {
    update.mutate({ accountId, update: { hints: { hidden_all: true } } });
  }

  const panel = (
    <div className="flex flex-col gap-3 rounded-mark border border-line bg-sunken px-4 py-3 text-body text-text">
      <p>{children}</p>
      {walking ? null : (
        <div className="flex flex-wrap gap-3">
          <Button tone="quiet" size="sm" onClick={hideAll} disabled={update.isPending}>
            {t('explanation.hideAll')}
          </Button>
          <Button tone="quiet" size="sm" onClick={close} disabled={update.isPending}>
            {t('explanation.close')}
          </Button>
        </div>
      )}
    </div>
  );

  if (!walking || walk.step === null) return panel;

  return (
    <div className="flex flex-col gap-2">
      <WalkBar step={walk.step} steps={walk.steps} />
      {panel}
    </div>
  );
}
