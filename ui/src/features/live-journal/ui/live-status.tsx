import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import type { LiveStatus as LiveStatusValue } from '../model/use-live-journal';

/**
 * Чем называется каждое состояние потока в словаре и тревожное ли оно.
 *
 * Перечислено ключами объекта: состояние, добавленное в `LiveStatus`, роняет сборку,
 * а не остаётся без подписи (тот же приём, что у тонов и списков контракта). Сами
 * подписи живут в словаре языков — здесь только имя ключа.
 */
const STATES = {
  connecting: { key: 'connecting', alarming: false },
  live: { key: 'online', alarming: false },
  reconnecting: { key: 'offline', alarming: true },
} satisfies Record<
  LiveStatusValue,
  { key: 'connecting' | 'online' | 'offline'; alarming: boolean }
>;

/**
 * Точка соединения — псевдоэлемент, а не узел разметки: она не содержание, а знак при
 * подписи, и диктору читать в ней нечего. Заливка берётся от текста (`bg-current`),
 * поэтому тревога красит подпись и точку разом.
 *
 * `rounded-pill` — то же «скруглить целиком», что у точки счётчика в верхней полосе:
 * на квадрате 8×8 999px обрезаются до 4px, то есть до той же окружности, что давали 50%.
 */
const INDICATOR =
  "inline-flex items-center gap-1 text-label before:size-2 before:rounded-pill before:bg-current before:content-['']";

/**
 * Состояние живого потока в шапке: свежесть того, на что человек смотрит
 * (`CONCEPT.md`, 5).
 *
 * Первое открытие не красное. Красный означает «показанному больше нельзя верить»,
 * и вспыхивать им на каждой загрузке страницы значит обесценить его к третьему разу.
 */
export function LiveStatus({ status }: { status: LiveStatusValue }) {
  const state = STATES[status];
  const { t } = useTranslation('ui');

  return (
    <span
      className={cn(INDICATOR, state.alarming ? 'text-danger' : 'text-muted')}
      role="status"
      title={t(`live.${state.key}Title`)}
    >
      {t(`live.${state.key}`)}
    </span>
  );
}
