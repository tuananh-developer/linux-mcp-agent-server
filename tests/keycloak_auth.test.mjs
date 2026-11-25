import test from 'node:test';
import assert from 'node:assert/strict';
import { beginLogin, clearAuthSession, completeLoginRedirect, getAccessToken } from '../src/linux_mcp_agent/web/keycloak-auth.mjs';

test('Keycloak login uses PKCE, exchanges the code, and refreshes tokens in memory', async t => {
  const storage = new Map();
  let assignedUrl = '';
  const fakeLocation = {
    origin: 'https://mcp.home.arpa',
    pathname: '/dashboard',
    href: 'https://mcp.home.arpa/dashboard',
    assign(url) { assignedUrl = url; },
  };
  const previous = {
    location: globalThis.location,
    sessionStorage: globalThis.sessionStorage,
    history: globalThis.history,
    document: globalThis.document,
  };
  Object.defineProperty(globalThis, 'location', { configurable: true, value: fakeLocation });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: {
    setItem(key, value) { storage.set(key, value); },
    getItem(key) { return storage.get(key) ?? null; },
    removeItem(key) { storage.delete(key); },
  } });
  Object.defineProperty(globalThis, 'history', { configurable: true, value: {
    replaceState(_state, _title, path) { fakeLocation.href = fakeLocation.origin + path; },
  } });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: 'Linux Observatory' } });

  t.after(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key];
      else Object.defineProperty(globalThis, key, { configurable: true, value });
    }
  });

  let authorizationExchange;
  let refreshCalls = 0;
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    if (String(url).endsWith('/.well-known/openid-configuration')) {
      return Response.json({
        issuer: 'https://auth.home.arpa/realms/linux-agent',
        authorization_endpoint: 'https://auth.home.arpa/realms/linux-agent/protocol/openid-connect/auth',
        token_endpoint: 'https://auth.home.arpa/realms/linux-agent/protocol/openid-connect/token',
      });
    }
    assert.equal(String(url), 'https://auth.home.arpa/realms/linux-agent/protocol/openid-connect/token');
    const form = new URLSearchParams(options.body);
    assert.equal(form.get('client_id'), 'linux-observatory-browser');
    assert.equal(form.get('resource'), 'https://mcp.home.arpa/mcp');
    if (form.get('grant_type') === 'authorization_code') {
      authorizationExchange = Object.fromEntries(form.entries());
      return Response.json({
        access_token: 'first-access-token',
        refresh_token: 'first-refresh-token',
        expires_in: 1,
        scope: 'openid mcp.read mcp.logs.read',
      });
    }
    assert.equal(form.get('grant_type'), 'refresh_token');
    assert.equal(form.get('refresh_token'), 'first-refresh-token');
    refreshCalls += 1;
    return Response.json({
      access_token: 'refreshed-access-token',
      refresh_token: 'rotated-refresh-token',
      expires_in: 300,
      scope: 'openid mcp.read mcp.logs.read',
    });
  });

  await beginLogin();
  const authorization = new URL(assignedUrl);
  assert.equal(authorization.origin, 'https://auth.home.arpa');
  assert.equal(authorization.searchParams.get('response_type'), 'code');
  assert.equal(authorization.searchParams.get('client_id'), 'linux-observatory-browser');
  assert.equal(authorization.searchParams.get('code_challenge_method'), 'S256');
  assert.equal(authorization.searchParams.get('resource'), 'https://mcp.home.arpa/mcp');
  assert.ok(authorization.searchParams.get('code_challenge'));

  const transaction = JSON.parse(storage.values().next().value);
  fakeLocation.href = 'https://mcp.home.arpa/dashboard?code=one-time-code&state=' + encodeURIComponent(transaction.state);
  await completeLoginRedirect();

  assert.equal(authorizationExchange.code, 'one-time-code');
  assert.equal(authorizationExchange.redirect_uri, 'https://mcp.home.arpa/dashboard');
  assert.equal(authorizationExchange.code_verifier, transaction.verifier);
  assert.equal(storage.size, 0, 'the PKCE transaction is removed after the callback');
  assert.equal(fakeLocation.href, 'https://mcp.home.arpa/dashboard', 'the authorization code is removed from the URL');

  assert.equal(await getAccessToken(), 'refreshed-access-token');
  assert.equal(refreshCalls, 1);
  assert.equal(storage.size, 0, 'access and refresh tokens are not persisted in sessionStorage');
  clearAuthSession();
  assert.equal(await getAccessToken(), null);
});
