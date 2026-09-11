import { describe, expect, it, vi } from 'vitest';
import { LANGUAGES, type Language } from '../../i18n';
import { exactTime, relativeTime } from './time';

const NOW = Date.parse('2026-09-05T12:00:00Z');

/**
 * Подпись ступени ниже минуты приходит параметром из словаря. В тесте она нарочно
 * не похожа на настоящую: так видно, что функция отдаёт присланное, а не свою строку.
 */
const JUST_NOW = '⟨только что⟩';

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function ago(milliseconds: number): string {
  return new Date(NOW - milliseconds).toISOString();
}

function said(value: string, language: Language): string {
  return relativeTime(value, { language, justNow: JUST_NOW, now: NOW });
}

/**
 * Чего ждём от ступени: слова считает `Intl`, а тест сторожит арифметику — какую
 * единицу выбрали и с каким знаком. Своей таблицы склонений и сокращений в тесте нет
 * по той же причине, по какой её нет в `time.ts`.
 */
function step(value: number, unit: Intl.RelativeTimeFormatUnit, language: Language): string {
  return new Intl.RelativeTimeFormat(language, { numeric: 'always', style: 'short' }).format(
    value,
    unit,
  );
}

describe.each(LANGUAGES)('относительное время, язык %s', (language) => {
  it('59 секунд в обе стороны — ступень ниже минуты, и она из словаря', () => {
    expect(said(ago(59 * SECOND), language)).toBe(JUST_NOW);
    expect(said(ago(-59 * SECOND), language)).toBe(JUST_NOW);
  });

  it('61 секунда — уже минута', () => {
    expect(said(ago(61 * SECOND), language)).toBe(step(-1, 'minute', language));
  });

  it('25 часов — уже день, а не двадцать пять часов', () => {
    expect(said(ago(25 * HOUR), language)).toBe(step(-1, 'day', language));
  });

  it('40 дней — уже месяц', () => {
    expect(said(ago(40 * DAY), language)).toBe(step(-1, 'month', language));
  });

  it('400 дней — уже год', () => {
    expect(said(ago(400 * DAY), language)).toBe(step(-1, 'year', language));
  });

  it('часы и дни внутри своих границ считаются своими единицами', () => {
    expect(said(ago(5 * HOUR), language)).toBe(step(-5, 'hour', language));
    expect(said(ago(3 * DAY), language)).toBe(step(-3, 'day', language));
  });

  it('пустое и неразбираемое значение не выдумывает', () => {
    expect(said('', language)).toBe('');
    expect(relativeTime(null, { language, justNow: JUST_NOW, now: NOW })).toBe('');
    expect(relativeTime(undefined, { language, justNow: JUST_NOW, now: NOW })).toBe('');
    expect(said('позавчера', language)).toBe('');
  });
});

describe('относительное время говорит на присланном языке', () => {
  it('одна и та же метка звучит по-разному на разных языках', () => {
    expect(said(ago(3 * MINUTE), 'en')).not.toBe(said(ago(3 * MINUTE), 'ru'));
    expect(said(ago(3 * MINUTE), 'en')).toMatch(/ago/);
    expect(said(ago(3 * MINUTE), 'ru')).toMatch(/назад/);
  });

  it('каждый язык интерфейса звучит по-своему: подставить один на всех неоткуда', () => {
    const spoken = LANGUAGES.map((language) => said(ago(3 * MINUTE), language));
    expect(new Set(spoken).size).toBe(LANGUAGES.length);
  });
});

describe('точное время', () => {
  const AT = '2026-09-05T12:00:00Z';

  it('называет месяц на языке интерфейса', () => {
    expect(exactTime(AT, 'en')).toMatch(/September/);
    expect(exactTime(AT, 'ru')).toMatch(/сентября/);
    expect(exactTime(AT, 'en')).not.toBe(exactTime(AT, 'ru'));
  });

  it('пояс остаётся местным и от языка не зависит', () => {
    /*
     * Метка выбрана так, чтобы у поясов западнее Гринвича местная дата отличалась
     * от календарной по UTC: в Нью-Йорке это ещё 4 сентября. День в подписи обязан
     * совпасть с местным — иначе подсказка показывает лондонское время человеку,
     * сидящему в своём поясе.
     */
    const early = '2026-09-05T02:00:00Z';
    const localDay = String(new Date(early).getDate());

    for (const language of LANGUAGES) {
      expect(exactTime(early, language)).toContain(localDay);
    }
  });

  it('пустое значение оставляет пустым', () => {
    expect(exactTime(null, 'en')).toBe('');
    expect(exactTime(undefined, 'ru')).toBe('');
    expect(exactTime('', 'en')).toBe('');
  });
});

describe('цена подписи', () => {
  it('форматтер создаётся один раз на язык, а не на вызов', async () => {
    /*
     * В списке из сотни строк подпись рисуется сотни раз за отрисовку, и создание
     * `Intl.DateTimeFormat` на месте съедало бы кадр целиком. Сторож считает
     * настоящие построения: модуль поднимается заново, потому что разбор форматтеров
     * живёт на модуле и в этом прогоне уже заполнен.
     */
    vi.resetModules();
    const built = vi.spyOn(Intl, 'DateTimeFormat');
    const { exactTime: fresh } = await import('./time');

    for (let call = 0; call < 200; call += 1) {
      for (const language of LANGUAGES) fresh('2026-09-05T12:00:00Z', language);
    }

    expect(built).toHaveBeenCalledTimes(LANGUAGES.length);
  });
});
