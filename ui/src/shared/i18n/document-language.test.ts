import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { syncDocumentLanguage } from './document-language';
import { en, ru } from './dictionaries';
import { i18n } from './i18n';
import { DEFAULT_LANGUAGE, LANGUAGES } from './languages';

const SHELL = readFileSync(resolve(__dirname, '../../../index.html'), 'utf8');

/**
 * Умолчания оболочки сверяются с языком по умолчанию, а не вычитываются глазами.
 *
 * `index.html` — единственное место, куда язык попадает раньше кода: выбор человека
 * лежит в `localStorage`, и до запуска кода его не прочесть. Значит написанное там —
 * это язык по умолчанию и ничто другое, а разъехаться с ним оно может молча: файл
 * лежит в стороне от `src`, и ни типы, ни линт в него не смотрят.
 */
describe('оболочка страницы', () => {
  it('объявляет язык по умолчанию, а не какой-нибудь', () => {
    expect(SHELL).toMatch(new RegExp(`<html lang="${DEFAULT_LANGUAGE}">`, 'u'));
  });

  it('несёт заголовок вкладки из словаря языка по умолчанию', () => {
    const title = /<title>(?<title>[^<]*)<\/title>/u.exec(SHELL)?.groups?.title;
    expect(title).toBe({ en, ru }[DEFAULT_LANGUAGE].ui.app.name);
  });
});

describe('язык документа', () => {
  const restore: (() => void)[] = [];

  afterEach(async () => {
    while (restore.length > 0) restore.pop()?.();
    await i18n.changeLanguage(DEFAULT_LANGUAGE);
  });

  function sync(): void {
    restore.push(syncDocumentLanguage());
  }

  it.each(LANGUAGES)('на языке %s ставит его же в `lang` и заголовок вкладки', async (language) => {
    await i18n.changeLanguage(language);
    sync();

    expect(document.documentElement.lang).toBe(language);
    expect(document.title).toBe({ en, ru }[language].ui.app.name);
  });

  it('идёт за сменой языка, а не читается один раз при запуске', async () => {
    await i18n.changeLanguage('en');
    sync();
    expect(document.documentElement.lang).toBe('en');

    await i18n.changeLanguage('ru');
    expect(document.documentElement.lang).toBe('ru');
    expect(document.title).toBe(ru.ui.app.name);

    await i18n.changeLanguage('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.title).toBe(en.ui.app.name);
  });

  it('отписка снимает слежение целиком', async () => {
    await i18n.changeLanguage('en');
    const stop = syncDocumentLanguage();
    stop();

    await i18n.changeLanguage('ru');
    expect(document.documentElement.lang).toBe('en');
    expect(document.title).toBe(en.ui.app.name);
  });
});
