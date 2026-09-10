import { http } from 'msw';
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { setToken } from '@/shared/api';
import { API, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';

describe('просроченный сеанс', () => {
  it('на 401 сбрасывает токен, уводит на вход и объясняет причину', async () => {
    setToken('trk_stale');
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        failure('unauthorized', 401, 'Authentication required'),
      ),
    );

    renderApp('/tasks');

    expect(await screen.findByText(say.login('expired'))).toBeInTheDocument();
    expect(screen.getByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('токен уходит только заголовком, не параметром запроса', async () => {
    setToken('trk_stale');
    const requested: string[] = [];
    server.events.on('request:start', ({ request }) => requested.push(request.url));
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        failure('unauthorized', 401, 'Authentication required'),
      ),
    );

    renderApp('/tasks');
    await screen.findByText(say.login('expired'));

    expect(requested.length).toBeGreaterThan(0);
    expect(requested.filter((url) => url.includes('trk_stale'))).toEqual([]);
  });
});
