import { describe, expect, it } from 'vitest';
import { accessToken } from '@testing/msw/responses';
import { belongsTo, isConnection, isKey, isLive, isSession, isThisComputer } from './tokens';

const NOW = Date.parse('2026-09-22T12:00:00Z');

describe('чей токен', () => {
  it('свой — говорит от моего имени или выпущен мной-человеком', () => {
    expect(belongsTo(accessToken({ participant: 'alice' }), 'alice')).toBe(true);
    expect(
      belongsTo(
        accessToken({ participant: 'bot', created_by: { kind: 'human', signature: 'alice' } }),
        'alice',
      ),
    ).toBe(true);
    // Временный агент с той же меткой своим токен не делает (TRK-114#12).
    expect(
      belongsTo(
        accessToken({ participant: 'bot', created_by: { kind: 'agent', signature: 'alice' } }),
        'alice',
      ),
    ).toBe(false);
    expect(belongsTo(accessToken({ participant: null }), 'alice')).toBe(false);
    expect(belongsTo(accessToken({ participant: 'alice' }), null)).toBe(false);
  });
});

describe('вид строки доступа и жив ли он', () => {
  it('вид задаёт `kind`, а не срок: у подключения срок есть, и оно не сеанс', () => {
    const connection = accessToken({ kind: 'oauth', expires_at: '2026-10-22T12:00:00Z' });
    expect(isConnection(connection)).toBe(true);
    expect(isSession(connection)).toBe(false);
    expect(isKey(connection)).toBe(false);

    expect(isKey(accessToken({ kind: 'key' }))).toBe(true);
    expect(isSession(accessToken({ kind: 'session', expires_at: null }))).toBe(true);
  });

  it('ключ этого компьютера — сеанс без срока с именем `local-ui`', () => {
    expect(isThisComputer(accessToken({ kind: 'session', name: 'local-ui' }))).toBe(true);
    expect(isThisComputer(accessToken({ kind: 'key', name: 'local-ui' }))).toBe(false);
    expect(isThisComputer(accessToken({ kind: 'session', name: 'вход с ноутбука' }))).toBe(false);
  });

  it('сеанс жив, пока не отозван и срок не прошёл; ключ — до отзыва', () => {
    const key = accessToken({ kind: 'key', expires_at: null });
    expect(isLive(key, NOW)).toBe(true);
    expect(isLive(accessToken({ revoked_at: '2026-09-22T11:00:00Z' }), NOW)).toBe(false);

    const session = accessToken({ kind: 'session', expires_at: '2026-09-23T12:00:00Z' });
    expect(isLive(session, NOW)).toBe(true);
    expect(isLive(accessToken({ kind: 'session', expires_at: '2026-09-22T11:59:00Z' }), NOW)).toBe(
      false,
    );
    // Локальный ключ интерфейса срока не имеет.
    expect(isLive(accessToken({ kind: 'session', expires_at: null }), NOW)).toBe(true);
  });

  it('подключение OAuth живо до отзыва, хотя срок его токена вышел: клиент продлит его сам', () => {
    const lapsed = accessToken({ kind: 'oauth', expires_at: '2026-09-22T11:59:00Z' });
    expect(isLive(lapsed, NOW)).toBe(true);
    expect(isLive({ ...lapsed, revoked_at: '2026-09-22T11:59:30Z' }, NOW)).toBe(false);
  });
});
