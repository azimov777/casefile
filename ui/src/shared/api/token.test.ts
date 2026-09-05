import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearToken, getToken, setToken, subscribeToken } from './token';

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
