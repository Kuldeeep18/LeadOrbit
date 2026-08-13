const storedApiBase = localStorage.getItem('api_base_url');
const isLocalhost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const defaultApiBase = isLocalhost
    ? 'http://127.0.0.1:8000/api/v1'
    : 'https://leadorbit.onrender.com/api/v1';
const API_BASE = (storedApiBase || defaultApiBase).replace(/\/$/, '');

export const setTokens = (access, refresh) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
};

export const getAccessToken = () => localStorage.getItem('access_token');
export const getRefreshToken = () => localStorage.getItem('refresh_token');
export const clearTokens = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
};

let refreshPromise = null;

const redirectToLogin = () => {
    localStorage.clear();
    window.location.href = '/login.html';
};

export const showGlobalError = (msg) => {
    let errorDiv = document.getElementById('global-api-error');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.id = 'global-api-error';
        errorDiv.style.position = 'fixed';
        errorDiv.style.top = '20px';
        errorDiv.style.right = '20px';
        errorDiv.style.backgroundColor = '#ef4444';
        errorDiv.style.color = 'white';
        errorDiv.style.padding = '12px 24px';
        errorDiv.style.borderRadius = '8px';
        errorDiv.style.zIndex = '9999';
        errorDiv.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
        document.body.appendChild(errorDiv);
    }
    errorDiv.innerText = msg;
    setTimeout(() => {
        if (errorDiv && errorDiv.parentNode) {
            errorDiv.parentNode.removeChild(errorDiv);
        }
    }, 5000);
};

export const refreshAccessToken = async () => {
    const refresh = getRefreshToken();
    if (!refresh) {
        throw new Error('Missing refresh token');
    }

    if (!refreshPromise) {
        refreshPromise = fetch(`${API_BASE}/token/refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh }),
        })
            .then(async (res) => {
                if (!res.ok) {
                    throw new Error('Refresh failed');
                }

                const data = await res.json();
                if (!data.access) {
                    throw new Error('Refresh response missing access token');
                }

                localStorage.setItem('access_token', data.access);
                if (data.refresh) {
                    localStorage.setItem('refresh_token', data.refresh);
                }
                return data.access;
            })
            .finally(() => {
                refreshPromise = null;
            });
    }

    return refreshPromise;
};

const buildRequestHeaders = (options, token = getAccessToken()) => {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    } else {
        delete headers['Authorization'];
    }

    // Don't set content-type for FormData (like CSV uploads)
    if (options.body instanceof FormData) {
        delete headers['Content-Type'];
    }

    return headers;
};

const sendApiRequest = async (endpoint, options = {}, token = getAccessToken()) => {
    const headers = buildRequestHeaders(options, token);
    const timeoutMs = Number(options.timeoutMs) > 0 ? Number(options.timeoutMs) : 20000;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
        return await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
            signal: options.signal || controller.signal,
        });
    } catch (error) {
        if (error.name === 'AbortError') {
            showGlobalError('Network error: Request timed out.');
            throw new Error('Request timed out. Check if the backend is running on port 8000.');
        }
        if (error instanceof TypeError) {
            showGlobalError('Network error: Backend unreachable.');
            throw new Error(`Cannot reach backend API at ${API_BASE}. Check that the backend server is running.`);
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }
};

export const fetchWithAuth = async (endpoint, options = {}) => {
    const token = getAccessToken();
    let response = await sendApiRequest(endpoint, options, token);

    if (response.status === 401) {
        try {
            const refreshedToken = await refreshAccessToken();
            response = await sendApiRequest(endpoint, options, refreshedToken);
        } catch {
            redirectToLogin();
            throw new Error("Unauthorized");
        }

        if (response.status === 401) {
            redirectToLogin();
            throw new Error("Unauthorized");
        }
    }

    return response;
};

export const login = async (email, password) => {
    const res = await fetch(`${API_BASE}/token/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
    });
    if (!res.ok) throw new Error("Login failed");
    const data = await res.json();
    setTokens(data.access, data.refresh);
    return data;
};

export const register = async (userData) => {
    const res = await fetch(`${API_BASE}/auth/register/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(userData)
    });
    if (!res.ok) throw new Error("Registration failed");
    const data = await res.json();
    setTokens(data.access, data.refresh);
    return data;
};
