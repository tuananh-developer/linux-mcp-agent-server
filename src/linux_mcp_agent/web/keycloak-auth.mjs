/** Browser-side Keycloak Authorization Code flow with PKCE (S256).
 * Access and refresh tokens live only in this module's memory. sessionStorage is
 * used only for the one-time state/verifier transaction needed across redirect.
 */
const ISSUER = 'https://auth.home.arpa/realms/linux-agent';
const AUTH_ORIGIN = 'https://auth.home.arpa';
const CLIENT_ID = 'linux-observatory-browser';
const RESOURCE = 'https://mcp.home.arpa/mcp';
const REQUESTED_SCOPE = 'openid mcp.read mcp.logs.read';
const TRANSACTION_KEY = 'linux-observatory.oauth-transaction';
const TRANSACTION_TTL_MS = 10 * 60 * 1000;
const REFRESH_EARLY_MS = 45 * 1000;

let metadataPromise;
let tokens = null;
let refreshPromise = null;

function randomBase64Url(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  let binary = '';
  for (const byte of new Uint8Array(digest)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function redirectUri() {
  const allowedPaths = new Set(['/', '/dashboard', '/assistant']);
  if (location.origin !== 'https://mcp.home.arpa' || !allowedPaths.has(location.pathname)) {
    throw new Error('Địa chỉ callback OAuth không hợp lệ. Hãy mở Dashboard qua https://mcp.home.arpa.');
  }
  return location.origin + location.pathname;
}

async function discover() {
  if (!metadataPromise) {
    metadataPromise = (async () => {
      const response = await fetch(ISSUER + '/.well-known/openid-configuration', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
      });
      if (!response.ok) throw new Error('Không tải được cấu hình Keycloak (HTTP ' + response.status + ').');
      const metadata = await response.json();
      if (metadata.issuer !== ISSUER) throw new Error('Issuer Keycloak không khớp cấu hình.');
      for (const endpoint of [metadata.authorization_endpoint, metadata.token_endpoint]) {
        const parsed = new URL(endpoint);
        if (parsed.protocol !== 'https:' || parsed.origin !== AUTH_ORIGIN) {
          throw new Error('Keycloak trả về endpoint OAuth không đáng tin cậy.');
        }
      }
      return metadata;
    })().catch(error => {
      metadataPromise = null;
      throw error;
    });
  }
  return metadataPromise;
}

function saveTokens(payload, previousRefreshToken = '') {
  if (!payload || typeof payload.access_token !== 'string' || !payload.access_token) {
    throw new Error('Keycloak không trả về access token.');
  }
  const expiresIn = Number(payload.expires_in);
  if (!Number.isFinite(expiresIn) || expiresIn <= 0) {
    throw new Error('Keycloak trả về thời hạn access token không hợp lệ.');
  }
  if (typeof payload.scope === 'string' && !payload.scope.split(/\s+/).includes('mcp.read')) {
    throw new Error('Tài khoản Keycloak chưa được cấp scope mcp.read.');
  }
  tokens = {
    accessToken: payload.access_token,
    refreshToken: typeof payload.refresh_token === 'string' && payload.refresh_token
      ? payload.refresh_token
      : previousRefreshToken,
    expiresAt: Date.now() + expiresIn * 1000,
  };
}

async function tokenRequest(form) {
  const metadata = await discover();
  const response = await fetch(metadata.token_endpoint, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams(form),
    cache: 'no-store',
    credentials: 'omit',
    redirect: 'error',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.error_description === 'string'
      ? payload.error_description
      : typeof payload.error === 'string' ? payload.error : 'HTTP ' + response.status;
    throw new Error('Keycloak token request thất bại: ' + detail);
  }
  return payload;
}

export async function beginLogin() {
  const metadata = await discover();
  const callback = redirectUri();
  const state = randomBase64Url(32);
  const verifier = randomBase64Url(48);
  const challenge = await pkceChallenge(verifier);
  const transaction = {
    state,
    verifier,
    redirectUri: callback,
    createdAt: Date.now(),
  };
  try {
    sessionStorage.setItem(TRANSACTION_KEY, JSON.stringify(transaction));
  } catch {
    throw new Error('Trình duyệt không cho phép sessionStorage; không thể khởi tạo đăng nhập an toàn.');
  }

  const authorization = new URL(metadata.authorization_endpoint);
  authorization.search = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: 'code',
    response_mode: 'query',
    redirect_uri: callback,
    scope: REQUESTED_SCOPE,
    resource: RESOURCE,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  }).toString();
  location.assign(authorization.toString());
}

export async function completeLoginRedirect() {
  const current = new URL(location.href);
  const code = current.searchParams.get('code');
  const oauthError = current.searchParams.get('error');
  if (!code && !oauthError) return false;

  let transaction = null;
  try {
    const raw = sessionStorage.getItem(TRANSACTION_KEY);
    if (raw) transaction = JSON.parse(raw);
  } catch {
    transaction = null;
  } finally {
    sessionStorage.removeItem(TRANSACTION_KEY);
  }

  // Remove authorization codes and error details from the visible URL/history.
  history.replaceState(null, document.title, current.pathname + current.hash);

  if (oauthError) {
    const description = current.searchParams.get('error_description');
    throw new Error(description ? 'Đăng nhập Keycloak thất bại: ' + description : 'Đăng nhập Keycloak thất bại: ' + oauthError);
  }
  if (
    !transaction ||
    typeof transaction.state !== 'string' ||
    typeof transaction.verifier !== 'string' ||
    transaction.state !== current.searchParams.get('state') ||
    transaction.redirectUri !== redirectUri() ||
    !Number.isFinite(transaction.createdAt) ||
    Date.now() - transaction.createdAt > TRANSACTION_TTL_MS
  ) {
    throw new Error('Phiên đăng nhập OAuth không hợp lệ hoặc đã hết hạn. Hãy đăng nhập lại.');
  }

  const payload = await tokenRequest({
    grant_type: 'authorization_code',
    client_id: CLIENT_ID,
    code,
    redirect_uri: transaction.redirectUri,
    code_verifier: transaction.verifier,
    resource: RESOURCE,
  });
  saveTokens(payload);
  return true;
}

async function refreshTokens() {
  if (!tokens?.refreshToken) {
    tokens = null;
    return null;
  }
  if (!refreshPromise) {
    const previous = tokens;
    refreshPromise = (async () => {
      try {
        const payload = await tokenRequest({
          grant_type: 'refresh_token',
          client_id: CLIENT_ID,
          refresh_token: previous.refreshToken,
          resource: RESOURCE,
        });
        saveTokens(payload, previous.refreshToken);
        return tokens.accessToken;
      } catch {
        // An invalid/expired refresh token requires a new Keycloak authorization.
        tokens = null;
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

export async function getAccessToken() {
  if (!tokens) return null;
  if (tokens.expiresAt - Date.now() > REFRESH_EARLY_MS) return tokens.accessToken;
  return refreshTokens();
}

export function clearAuthSession() {
  tokens = null;
  refreshPromise = null;
  try {
    sessionStorage.removeItem(TRANSACTION_KEY);
  } catch {
    // The in-memory credentials are still cleared if storage is unavailable.
  }
}
