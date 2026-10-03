
import { fetchWithAuth, clearTokens, refreshAccessToken } from './api.js';

const THEME_STORAGE_KEY = 'theme';
const LEADORBIT_VERSION = 'v1.0.0-beta';
const LEADORBIT_REPO_URL = 'https://github.com/Kuldeeep18/LeadOrbit';

// ==========================================
// THEME MANAGEMENT
// ==========================================

function decodeJwt(token) {
    try {
        const payload = token.split('.')[1];
        return JSON.parse(atob(payload));
    } catch {
        return null;
    }
}

function getTokenExpiryTime() {
    const token = localStorage.getItem('access_token');
    if (!token) return null;

    const decoded = decodeJwt(token);
    if (!decoded?.exp) return null;

    return decoded.exp * 1000;
}


let sessionWarningTimer = null;
let sessionLogoutTimer = null;


function clearSessionTimers() {
    if (sessionWarningTimer) {
        clearTimeout(sessionWarningTimer);
        sessionWarningTimer = null;
    }

    if (sessionLogoutTimer) {
        clearTimeout(sessionLogoutTimer);
        sessionLogoutTimer = null;
    }
}

function showSessionTimeoutModal() {
    const modalEl = document.getElementById('sessionTimeoutModal');

    if (!modalEl || !window.bootstrap) {
        console.warn('Session timeout modal not found');
        return;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    const stayLoggedInBtn = document.getElementById('sessionStayLoggedInBtn');

    if (stayLoggedInBtn && !stayLoggedInBtn.dataset.bound) {
        stayLoggedInBtn.dataset.bound = 'true';

        stayLoggedInBtn.addEventListener('click', async () => {
            try {
                await refreshAccessToken();

                document.activeElement?.blur();
                modal.hide();

                scheduleSessionWarning();

                console.log('Session refreshed successfully');
            } catch (error) {
                console.error(error);

                clearTokens();
                window.location.href = '/login.html';
            }
        });
    }

    modal.show();
}


function injectSessionTimeoutModal() {
    if (document.getElementById('sessionTimeoutModal')) {
        return;
    }

    const modalHTML = `
        <div class="modal fade" id="sessionTimeoutModal" tabindex="-1" aria-labelledby="sessionTimeoutModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="sessionTimeoutModalLabel">
                            Session Expiring Soon
                        </h5>
                    </div>

                    <div class="modal-body">
                        Your session will expire in approximately 2 minutes.

                        Would you like to stay logged in?
                    </div>

                    <div class="modal-footer">
                        <button type="button"
                                class="btn btn-secondary"
                                id="sessionLogoutBtn">
                            Log Out
                        </button>

                        <button type="button"
                                class="btn btn-primary"
                                id="sessionStayLoggedInBtn">
                            Stay Logged In
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
}

function scheduleSessionWarning() {
    const expiryTime = getTokenExpiryTime();

    if (!expiryTime) return;

    clearSessionTimers();

    const now = Date.now();
    const warningTime = expiryTime - (2 * 60 * 1000);

    const warningDelay = warningTime - now;
    const logoutDelay = expiryTime - now;

    console.log('Session warning in:', warningDelay);
    console.log('Auto logout in:', logoutDelay);

    sessionWarningTimer = setTimeout(() => {
    showSessionTimeoutModal();
    }, Math.max(0, warningDelay));

    sessionLogoutTimer = setTimeout(() => {
    clearSessionTimers();
    clearTokens();
    window.location.href = '/login.html';
    }, Math.max(0, logoutDelay));
}



export function getTheme() {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (savedTheme === 'dark' || savedTheme === 'light') {
        return savedTheme;
    }
    // Check system preference if no saved theme
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
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
    
    // Dispatch event for other components to react
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: value } }));
}

export function toggleTheme() {
    const newTheme = getTheme() === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    
    // Update toggle if it exists
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.checked = newTheme === 'dark';
    }
    return newTheme;
}

function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) {
        console.debug('Theme toggle not found on this page');
    } else {
        // Set initial state from saved or system preference
        const currentTheme = getTheme();
        themeToggle.checked = currentTheme === 'dark';
        applyTheme(currentTheme);

        // Remove existing listeners by cloning (prevents duplicates)
        const newToggle = themeToggle.cloneNode(true);
        themeToggle.parentNode.replaceChild(newToggle, themeToggle);

        // Add change listener
        newToggle.addEventListener('change', () => {
            const newTheme = newToggle.checked ? 'dark' : 'light';
            setTheme(newTheme);
        });
    }

    // Header icon button (present on dashboard, leads, campaigns, analytics)
    const headerThemeBtn = document.getElementById('header-theme-toggle');
    if (headerThemeBtn) {
        const updateHeaderIcon = (theme) => {
            const icon = headerThemeBtn.querySelector('i');
            if (!icon) return;
            if (theme === 'dark') {
                icon.className = 'bi bi-sun';
                headerThemeBtn.setAttribute('aria-label', 'Switch to light mode');
                headerThemeBtn.setAttribute('title', 'Switch to light mode (Ctrl+T)');
            } else {
                icon.className = 'bi bi-moon-stars';
                headerThemeBtn.setAttribute('aria-label', 'Switch to dark mode');
                headerThemeBtn.setAttribute('title', 'Switch to dark mode (Ctrl+T)');
            }
        };

        // Set initial icon state
        updateHeaderIcon(getTheme());

        headerThemeBtn.addEventListener('click', () => {
            const newTheme = toggleTheme();
            updateHeaderIcon(newTheme);
        });

        // Keep icon in sync when theme changes via other means (settings page, keyboard shortcut, other tab)
        window.addEventListener('themeChanged', (e) => updateHeaderIcon(e.detail.theme));
    }
}

// Sync theme across multiple tabs
window.addEventListener('storage', (event) => {
    if (event.key === THEME_STORAGE_KEY && event.newValue) {
        const newTheme = event.newValue === 'dark' ? 'dark' : 'light';
        applyTheme(newTheme);
        
        // Update settings page toggle if it exists
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.checked = newTheme === 'dark';
        }

        // Update header icon button if it exists
        const headerThemeBtn = document.getElementById('header-theme-toggle');
        if (headerThemeBtn) {
            const icon = headerThemeBtn.querySelector('i');
            if (icon) {
                icon.className = newTheme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
            }
        }
    }
});

// ==========================================
// PASSWORD VISIBILITY TOGGLE
// ==========================================

function initPasswordVisibilityToggle() {
    const toggles = [
        { inputId: 'floatingPassword', toggleId: 'floatingPasswordToggle' },
        { inputId: 'password', toggleId: 'passwordToggle' }
    ];

    toggles.forEach(({ inputId, toggleId }) => {
        const input = document.getElementById(inputId);
        const toggle = document.getElementById(toggleId);

        if (!input || !toggle) {
            return;
        }

        const updateToggleState = () => {
            const isPasswordVisible = input.type === 'text';

            toggle.innerHTML = isPasswordVisible
                ? '<i class="bi bi-eye-slash" aria-hidden="true"></i>'
                : '<i class="bi bi-eye" aria-hidden="true"></i>';

            toggle.setAttribute(
                'aria-label',
                isPasswordVisible ? 'Hide password' : 'Show password'
            );

            toggle.setAttribute('aria-pressed', String(isPasswordVisible));
        };

        updateToggleState();

        toggle.addEventListener('click', () => {
            input.type = input.type === 'password' ? 'text' : 'password';
            updateToggleState();
        });
    });
}

// ==========================================
// FOOTER ATTRIBUTION
// ==========================================

function buildProjectFooterMarkup() {
    return `
        <div class="project-attribution-footer" id="project-attribution-footer">
            <span class="project-attribution-version">${LEADORBIT_VERSION}</span>
            <span class="project-attribution-separator">•</span>
            <a class="project-attribution-link" href="${LEADORBIT_REPO_URL}" target="_blank" rel="noreferrer noopener">
                <i class="bi bi-github me-1" aria-hidden="true"></i>GitHub repository
            </a>
            <span class="project-attribution-separator">•</span>
            <span class="project-attribution-note">Made with ❤️ for GSSoC 2026</span>
        </div>
    `;
}

function injectProjectFooter() {
    const footerMarkup = buildProjectFooterMarkup();

    const sidebarFooter = document.querySelector('.sidebar-footer');
    if (sidebarFooter && !sidebarFooter.querySelector('#project-attribution-footer')) {
        sidebarFooter.insertAdjacentHTML('afterbegin', footerMarkup);
    }

    if (/campaign-builder\.html/i.test(window.location.pathname)) {
        const editorPanel = document.getElementById('editor-panel');
        if (editorPanel && !editorPanel.querySelector('#project-attribution-footer')) {
            editorPanel.insertAdjacentHTML('beforeend', footerMarkup);
        }
    }
}

// Apply theme on load
applyTheme(getTheme());

// ==========================================
// ACTIVE NAVIGATION LINK
// ==========================================
function setActiveNavLink() {
    const pathname = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link');

    if (navLinks.length === 0) return;

    navLinks.forEach(link => {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
    });

    let activeHref = '/dashboard.html';

    if (/campaign-builder\.html/i.test(pathname)) {
        activeHref = '/campaigns.html';
    } else if (/dashboard\.html/i.test(pathname)) {
        activeHref = '/dashboard.html';
    } else if (/leads\.html/i.test(pathname)) {
        activeHref = '/leads.html';
    } else if (/campaigns\.html/i.test(pathname)) {
        activeHref = '/campaigns.html';
    } else if (/analytics\.html/i.test(pathname)) {
        activeHref = '/analytics.html';
    } else if (/settings\.html/i.test(pathname)) {
        activeHref = '/settings.html';
    }

    const activeLink = document.querySelector(`a.nav-link[href="${activeHref}"]`);
    if (activeLink) {
        activeLink.classList.add('active');
        activeLink.setAttribute('aria-current', 'page');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setActiveNavLink);
} else {
    setActiveNavLink();
}

// ==========================================
// APP SHELL INITIALIZATION
// ==========================================

let appShellInitialized = false;

async function initAppShell() {
    if (appShellInitialized) {
        return;
    }
    appShellInitialized = true;

    initThemeToggle();
    initPasswordVisibilityToggle();
    injectSessionTimeoutModal();

    document.addEventListener('click', (event) => {
    if (event.target.id === 'sessionLogoutBtn') {
        clearSessionTimers();
        clearTokens();

    const modalEl = document.getElementById('sessionTimeoutModal');
    if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    }

    window.location.href = '/login.html';

    }
    });

    if (window.location.pathname.includes('login.html') || window.location.pathname.includes('register.html')) {
        return;
    }

    injectProjectFooter();

    try {
        const res = await fetchWithAuth('/auth/me/');
        if (!res.ok) throw new Error();

        const userData = await res.json();

        const userDisplays = document.querySelectorAll('.user-display-name');
        userDisplays.forEach(el => el.textContent = userData.email);

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

        if (userData.organization) {
            if (orgNameInput) orgNameInput.value = userData.organization.name || '';
            if (orgIdInput) orgIdInput.value = userData.organization.id || '';
            if (geminiKeyInput) geminiKeyInput.value = userData.organization.gemini_api_key || '';
            if (aiPersonalizationToggle) {
                aiPersonalizationToggle.checked = userData.organization.enable_ai_personalization !== false;
            }
        }

        console.log("Scheduling session warning...");
        scheduleSessionWarning();

    } catch (e) {
        console.error('Error loading user profile:', e);
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            clearSessionTimers();
            clearTokens();
            window.location.href = '/login.html';
    });
    }
    
    // Responsive sidebar toggle
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    if (hamburgerBtn && sidebar && overlay) {
        hamburgerBtn.addEventListener('click', () => {
            sidebar.classList.toggle('sidebar-open');
            overlay.classList.toggle('active');
        });

        overlay.addEventListener('click', () => {
            sidebar.classList.remove('sidebar-open');
            overlay.classList.remove('active');
        });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAppShell, { once: true });
} else {
    initAppShell();
}

// ==========================================
// KEYBOARD SHORTCUTS
// ==========================================

function injectShortcutsModal() {
    if (!document.getElementById('shortcutsHelpModal')) {
        const modalHTML = `
            <div class="modal fade" id="shortcutsHelpModal" tabindex="-1" aria-labelledby="shortcutsHelpModalLabel" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="shortcutsHelpModalLabel">⌨️ Keyboard Shortcuts</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <table class="table table-borderless align-middle mb-0">
                                <thead>
                                    <tr class="border-bottom">
                                        <th>Shortcut</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td><kbd>Alt + D</kbd></td><td>Navigate to Dashboard</td></tr>
                                    <tr><td><kbd>Alt + L</kbd></td><td>Navigate to Leads</td></tr>
                                    <tr><td><kbd>Alt + C</kbd></td><td>Navigate to Campaigns</td></tr>
                                    <tr><td><kbd>Alt + A</kbd></td><td>Navigate to Analytics</td></tr>
                                    <tr><td><kbd>Alt + S</kbd></td><td>Navigate to Settings</td></tr>
                                    <tr><td><kbd>Alt + N</kbd></td><td>New Campaign Builder</td></tr>
                                    <tr><td><kbd>Ctrl/Cmd + T</kbd></td><td>Toggle Dark/Light Theme</td></tr>
                                    <tr><td><kbd>?</kbd></td><td>Show this help menu</td></tr>
                                    <tr><td><kbd>/</kbd></td><td>Focus search bar</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHTML);
    }

    const sidebarFooter = document.querySelector('.sidebar-footer') || 
                          document.querySelector('aside .small') || 
                          document.querySelector('aside');
                          
    if (sidebarFooter) {
        if (!document.getElementById('shortcut-trigger-btn')) {
            const linkHTML = `
                <div class="mt-2 pt-2 border-top border-secondary border-opacity-25" id="shortcut-link-wrapper">
                    <a href="#" id="shortcut-trigger-btn" class="text-white opacity-50 text-decoration-none small" title="Show Keyboard Shortcuts">
                        <i class="bi bi-keyboard me-1"></i> Shortcuts <kbd class="bg-dark text-white border-secondary">?</kbd>
                    </a>
                </div>
            `;
            sidebarFooter.insertAdjacentHTML('afterbegin', linkHTML);

            document.getElementById('shortcut-trigger-btn').addEventListener('click', (e) => {
                e.preventDefault();
                const modalEl = document.getElementById('shortcutsHelpModal');
                if (modalEl && window.bootstrap) {
                    bootstrap.Modal.getOrCreateInstance(modalEl).show();
                }
            });
        }
    } else {
        setTimeout(injectShortcutsModal, 100);
    }
}

function initKeyboardShortcuts() {
    if (window.location.pathname.includes('login.html') || window.location.pathname.includes('register.html')) {
        return;
    }

    injectShortcutsModal();
    setTimeout(injectShortcutsModal, 200);

    document.addEventListener('keydown', (event) => {
        const activeEl = document.activeElement;
        if (activeEl && (
            activeEl.tagName === 'INPUT' || 
            activeEl.tagName === 'TEXTAREA' || 
            activeEl.isContentEditable
        )) {
            return;
        }

        // Show help modal
        if (event.key === '?') {
            event.preventDefault();
            const modalEl = document.getElementById('shortcutsHelpModal');
            if (modalEl && window.bootstrap) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
            return;
        }
        
        // Focus search
        if (event.key === '/') {
            const searchInput = document.querySelector('input[type="search"]') || 
                                document.querySelector('input[placeholder*="Search"]') ||
                                document.querySelector('.search-box input');
            if (searchInput) {
                event.preventDefault();
                searchInput.focus();
                searchInput.select();
            }
            return;
        }
        
        // Toggle theme with Ctrl+T or Cmd+T
        if ((event.ctrlKey || event.metaKey) && event.key === 't') {
            event.preventDefault();
            toggleTheme();
            return;
        }

        // Alt shortcuts for navigation
        if (event.altKey) {
            let targetPage = '';
            switch (event.key.toLowerCase()) {
                case 'd': targetPage = 'dashboard.html'; break;
                case 'l': targetPage = 'leads.html'; break;
                case 'c': targetPage = 'campaigns.html'; break;
                case 'a': targetPage = 'analytics.html'; break;
                case 's': targetPage = 'settings.html'; break;
                case 'n': targetPage = 'campaign-builder.html'; break;
                default: return;
            }
            event.preventDefault();
            window.location.href = targetPage;
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initKeyboardShortcuts);
} else {
    initKeyboardShortcuts();
}