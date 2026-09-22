import { describe, expect, it } from 'vitest';
import { accessToken } from '@testing/msw/responses';
import { belongsTo, isLive, isSession } from './tokens';

const NOW = Date.parse('2026-09-22T12:00:00Z');

describe('чей токен и жив ли он', () => {
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

  it('сеанс — токен со сроком; жив, пока не отозван и срок не прошёл', () => {
    const key = accessToken({ expires_at: null });
    expect(isSession(key)).toBe(false);
    expect(isLive(key, NOW)).toBe(true);
    expect(isLive(accessToken({ revoked_at: '2026-09-22T11:00:00Z' }), NOW)).toBe(false);

    const session = accessToken({ expires_at: '2026-09-23T12:00:00Z' });
    expect(isSession(session)).toBe(true);
    expect(isLive(session, NOW)).toBe(true);
    expect(isLive(accessToken({ expires_at: '2026-09-22T11:59:00Z' }), NOW)).toBe(false);
  });
});
