import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/ui';
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
 *
 * Подробность состояния — во всплывающей панели по нажатию (UI-163), а не только
 * в подсказке `title`: на телефоне наведения нет. Раскрыть её на месте, как время
 * (`RelativeTime`), нельзя: фраза подробности длинная, а верхняя полоса на узком
 * экране и так делит строку с крошками и переключателями. Сообщает о смене состояния
 * (`role="status"`) подпись внутри кнопки, а не кнопка: роль живой области у кнопки
 * заменила бы роль кнопки. Панель Radix в jsdom открывается десятки секунд
 * (`docs/notes/testing.md`), поэтому её открытие проверяет сквозной тест.
 */
export function LiveStatus({ status }: { status: LiveStatusValue }) {
  const state = STATES[status];
  const { t } = useTranslation('ui');
  const detail = t(`live.${state.key}Title`);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-live-status={status}
          className={cn(
            INDICATOR,
            // Кнопка остаётся подписью: рамку и фон снимает явно (`docs/notes/ui.md`,
            // «Кнопка без объявленного фона получает `ButtonFace` браузера»), на
            // телефоне мишень не ниже `--ui-tap` (UI-154).
            'cursor-pointer border-none border-current bg-transparent p-0 max-fold:min-h-(--ui-tap)',
            state.alarming ? 'text-danger' : 'text-muted',
          )}
          aria-label={t('live.explain', { state: t(`live.${state.key}`) })}
          title={detail}
        >
          <span role="status">{t(`live.${state.key}`)}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="max-w-xs text-meta">
        {detail}
      </PopoverContent>
    </Popover>
  );
}
