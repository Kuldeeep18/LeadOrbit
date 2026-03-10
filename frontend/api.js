const API_BASE = 'http://localhost:8000/api/v1';

export const setTokens = (access, refresh) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
};

export const getAccessToken = () => localStorage.getItem('access_token');
export const clearTokens = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
};

export const fetchWithAuth = async (endpoint, options = {}) => {
    const token = getAccessToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    // Don't set content-type for FormData (like CSV uploads)
    if (options.body instanceof FormData) {
        delete headers['Content-Type'];
    }

    const timeoutMs = Number(options.timeoutMs) > 0 ? Number(options.timeoutMs) : 10000;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    let response;
    try {
        response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
            signal: options.signal || controller.signal,
        });
    } catch (error) {
        if (error.name === 'AbortError') {
            throw new Error('Request timed out. Check if the backend is running on port 8000.');
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }

    if (response.status === 401) {
        // Handle token refresh logic here in production
        clearTokens();
        window.location.href = '/login.html';
        throw new Error("Unauthorized");
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
