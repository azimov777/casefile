import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  authorizationHeader,
  clearToken,
  getToken,
  isHeaderSafe,
  setToken,
  subscribeToken,
} from './token';

describe('хранилище токена', () => {
  beforeEach(() => {
    clearToken();
  });

  it('сохраняет токен и отдаёт его снимком', () => {
    setToken('trk_secret');
    expect(getToken()).toBe('trk_secret');
    expect(window.localStorage.getItem('tracker.token')).toBe('trk_secret');
  });

  it('сброс убирает токен и из памяти, и из хранилища', () => {
    setToken('trk_secret');
    clearToken();
    expect(getToken()).toBeNull();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('будит подписчиков на каждой смене', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToken(listener);

    setToken('trk_one');
    clearToken();
    unsubscribe();
    setToken('trk_two');

    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe('пригодность токена для заголовка', () => {
  /**
   * Проверяется ровно одно: соберётся ли заголовок. Формат токена не угадывается —
   * ни префикс, ни длина, ни набор символов. Годен ли он по существу, решает сервер.
   */
  it('пропускает всё, из чего заголовок собирается', () => {
    expect(isHeaderSafe('trk_abc-123_XYZ')).toBe(true);
    // Не похоже на токен установки — и всё равно уходит на сервер.
    expect(isHeaderSafe('not-a-tracker-token')).toBe(true);
    // Пробел и табуляция в значении заголовка допустимы.
    expect(isHeaderSafe('trk_a b')).toBe(true);
    expect(isHeaderSafe(`trk_a${String.fromCharCode(9)}b`)).toBe(true);
  });

  it('отвергает то, из чего заголовок не собрать', () => {
    // Вне latin-1: не превращается в `ByteString`.
    expect(isHeaderSafe(`trk_${String.fromCharCode(1087)}`)).toBe(false);
    // Управляющий символ: браузер такой заголовок не поставит.
    expect(isHeaderSafe(`trk_a${String.fromCharCode(1)}b`)).toBe(false);
    expect(isHeaderSafe(`trk_a${String.fromCharCode(10)}b`)).toBe(false);
    expect(isHeaderSafe(`trk_a${String.fromCharCode(127)}b`)).toBe(false);
  });

  it('заголовок собирается одной функцией, а негодное значение даёт `null`', () => {
    expect(authorizationHeader('trk_ok')).toBe('Bearer trk_ok');
    expect(authorizationHeader(`trk_${String.fromCharCode(1087)}`)).toBeNull();
  });
});
