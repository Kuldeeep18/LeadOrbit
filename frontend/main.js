
import { fetchWithAuth, clearTokens } from './api.js';

const THEME_STORAGE_KEY = 'theme';

export function getTheme() {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light';
}

export function applyTheme(theme) {
    const value = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', value);
    document.documentElement.setAttribute('data-bs-theme', value);
    document.documentElement.style.colorScheme = value;
}

export function setTheme(theme) {
    const value = theme === 'dark' ? 'dark' : 'light';
    localStorage.setItem(THEME_STORAGE_KEY, value);
    document.documentElement.classList.add('theme-transition');
    applyTheme(value);
    window.setTimeout(() => {
        document.documentElement.classList.remove('theme-transition');
    }, 300);
}

const AVATAR_COLORS = [
    '#2563eb',
    '#7c3aed',
    '#059669',
    '#dc2626',
    '#ea580c',
    '#0891b2',
];

function getAvatarInitials(user) {
    const first = (user.first_name || '').trim();
    const last = (user.last_name || '').trim();
    if (first || last) {
        const firstInitial = first ? first[0].toUpperCase() : '';
        const lastInitial = last ? last[0].toUpperCase() : '';
        return `${firstInitial}${lastInitial}` || (user.email || '').trim().charAt(0).toUpperCase();
    }
    return (user.email || '').trim().charAt(0).toUpperCase();
}

function getAvatarColor(email) {
    const normalized = String(email || '').trim().toLowerCase();
    let hash = 0;
    for (let i = 0; i < normalized.length; i += 1) {
        hash = ((hash << 5) - hash) + normalized.charCodeAt(i);
        hash |= 0;
    }
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function formatUserDisplayName(user) {
    const first = (user.first_name || '').trim();
    const last = (user.last_name || '').trim();
    if (first || last) {
        return `${first} ${last}`.trim();
    }
    return user.email || 'Unknown user';
}

function renderAvatarHtml(user) {
    if (user.avatar_url) {
        return `<img class="avatar-image" src="${user.avatar_url}" alt="User avatar">`;
    }
    const initials = getAvatarInitials(user);
    const background = getAvatarColor(user.email || '');
    return `<div class="avatar-circle" style="background:${background};">${initials}</div>`;
}

function renderUserProfile(userData) {
    const avatarContainers = document.querySelectorAll('.sidebar-avatar, .header-avatar');
    avatarContainers.forEach((container) => {
        container.innerHTML = renderAvatarHtml(userData);
    });

    const userDisplayNames = document.querySelectorAll('.user-display-name');
    const displayName = formatUserDisplayName(userData);
    userDisplayNames.forEach((el) => {
        el.textContent = displayName;
    });

    const userEmails = document.querySelectorAll('.user-email');
    userEmails.forEach((el) => {
        el.textContent = userData.email || '';
    });
}

function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) {
        return;
    }

    themeToggle.checked = getTheme() === 'dark';
    themeToggle.addEventListener('change', () => {
        setTheme(themeToggle.checked ? 'dark' : 'light');
    });
}

applyTheme(getTheme());

document.addEventListener('DOMContentLoaded', async () => {
    initThemeToggle();

    if (window.location.pathname.includes('login.html') || window.location.pathname.includes('register.html')) {
        return;
    }

    try {
        const res = await fetchWithAuth('/auth/me/');
        if (!res.ok) throw new Error();

        const userData = await res.json();

        renderUserProfile(userData);

        const orgDisplays = document.querySelectorAll('.org-display-name');
        orgDisplays.forEach(el => {
            if (userData.organization) el.textContent = userData.organization.name;
        });

        const profileEmail = document.getElementById('profile-email');
        const profileRole = document.getElementById('profile-role');
        if (profileEmail) profileEmail.value = userData.email || '';
        if (profileRole) profileRole.value = userData.role || 'ADMIN';

        const geminiKeyInput = document.getElementById('gemini-api-key');
        const aiPersonalizationToggle = document.getElementById('enable-ai-personalization');
        const orgNameInput = document.getElementById('org-name');
        const orgIdInput = document.getElementById('org-id');
        const avatarUrlInput = document.getElementById('avatar-url');
        const firstNameInput = document.getElementById('first-name');
        const lastNameInput = document.getElementById('last-name');

        if (userData.organization) {
            if (orgNameInput) orgNameInput.value = userData.organization.name || '';
            if (orgIdInput) orgIdInput.value = userData.organization.id || '';
            if (geminiKeyInput) geminiKeyInput.value = userData.organization.gemini_api_key || '';
            if (aiPersonalizationToggle) {
                aiPersonalizationToggle.checked = userData.organization.enable_ai_personalization !== false;
            }
        }

        if (avatarUrlInput) avatarUrlInput.value = userData.avatar_url || '';
        if (firstNameInput) firstNameInput.value = userData.first_name || '';
        if (lastNameInput) lastNameInput.value = userData.last_name || '';

    } catch (e) {
        console.error('Error loading user profile:', e);
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            clearTokens();
            window.location.href = '/login.html';
        });
    }
});
