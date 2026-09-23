import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLanguage } from '../i18n';
import { exactTime, relativeTime } from '../lib';

interface RelativeTimeProps {
  /** Метка времени из контракта; `null` бывает у полей, которых у объекта ещё нет. */
  value: string | null | undefined;
  /** Чем заменить отсутствующее время: у каждого столбца свой знак пустоты. */
  fallback?: string;
  /**
   * Время стоит внутри мишени, которая сама куда-то ведёт: строка таблицы, карточка
   * доски. Там нажатие обязано открыть задачу, а не панель со временем, поэтому своей
   * кнопки у времени нет, и точное остаётся подсказкой для мыши. Без наведения его видно
   * в самой задаче: время последней записи — это время записи в её деле, и там оно
   * нажимается (UI-153).
   */
  plain?: boolean;
}

/**
 * «3 мин. назад» с точным временем. Тег `time` с машинным `dateTime`: относительная
 * подпись читается глазами, а точная доступна наведением (`title`) и **нажатием**: время
 * — кнопка, и нажатие меняет подпись на точное время, повторное — обратно (UI-153).
 * Одного `title` мало: на телефоне наведения нет, и точное время было бы недостижимо
 * вовсе.
 *
 * Подпись меняется на месте, а не всплывающей панелью (Radix Popover, `./popover`):
 * времени в интерфейсе много, у каждого была бы своя панель поверх соседей, а в jsdom
 * панель Radix открывается десятками секунд (`docs/notes/testing.md`, «Панель `Popover`
 * в jsdom открывается десятки секунд») — страничный тест на неё мигал бы. Точное время
 * длиннее относительного, и строка раздвигается ровно тогда, когда человек сам попросил.
 *
 * Кнопка намеренно не похожа на кнопку: время остаётся подписью в строке, а нажимаемость
 * выдают курсор и пунктир под ним при наведении. Рамку кнопка снимает явно, с цветом
 * (`docs/notes/ui.md`, «Кнопка без объявленного фона получает `ButtonFace` браузера»);
 * шрифт и цвет наследует по сбросу. `aria-pressed` говорит диктору, какая подпись сейчас.
 *
 * Язык берётся здесь, а не внутри `relativeTime`: функции там чистые и принимают его
 * параметром. `useLanguage` заодно подписывает компонент на смену языка — без подписки
 * подпись времени осталась бы русской посреди английского экрана до следующей
 * отрисовки (`docs/notes/ui.md`, «Текст ошибки берёт язык у экземпляра»).
 */
export function RelativeTime({ value, fallback = '—', plain = false }: RelativeTimeProps) {
  const { t } = useTranslation('ui');
  const { language } = useLanguage();
  const [exactShown, setExactShown] = useState(false);

  const relative = relativeTime(value, { language, justNow: t('time.justNow') });
  if (relative === '') return <span aria-hidden="true">{fallback}</span>;

  const exact = exactTime(value, language);
  if (plain) {
    return (
      <time dateTime={value ?? undefined} title={exact}>
        {relative}
      </time>
    );
  }

  return (
    <button
      type="button"
      /*
       * `inline-flex items-center` и минимум высоты только на телефоне (`max-fold:`,
       * `--ui-tap`, UI-154): голая строка текста была мишенью 71×18, мельче обязательных
       * 24 px (WCAG 2.5.8). На столе плотность важнее, и там кнопка остаётся строкой.
       */
      className="inline-flex cursor-pointer items-center border-none border-current bg-transparent p-0 text-left decoration-dotted underline-offset-2 max-fold:min-h-(--ui-tap) hover:underline"
      aria-pressed={exactShown}
      onClick={() => setExactShown((shown) => !shown)}
    >
      {/* Подсказка стоит на `time`, как и без кнопки: её читают по `time[title]`
          (`e2e/language-formats.spec.ts`), а для мыши разницы нет — `time` занимает
          кнопку целиком. Подсказка называет ту подпись, которой сейчас не видно. */}
      <time dateTime={value ?? undefined} title={exactShown ? relative : exact}>
        {exactShown ? exact : relative}
      </time>
    </button>
  );
}
