
import { fetchWithAuth, clearTokens } from './api.js';

document.addEventListener('DOMContentLoaded', async () => {
    // If we're on a public page, do nothing special
    if (window.location.pathname.includes('login.html') || window.location.pathname.includes('register.html')) {
        return;
    }

    // Attempt to fetch profile info on authenticated pages
    try {
        const res = await fetchWithAuth('/auth/me/');
        if (!res.ok) throw new Error();

        const userData = await res.json();

        // Update UI placeholders generically
        const userDisplays = document.querySelectorAll('.user-display-name');
        userDisplays.forEach(el => el.textContent = userData.email);

        const orgDisplays = document.querySelectorAll('.org-display-name');
        orgDisplays.forEach(el => el.textContent = userData.organization.name);

    } catch (e) {
        // Automatically redirects to login via fetchWithAuth on 401
    }

    // Handle logout attachments
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            clearTokens();
            window.location.href = '/login.html';
        });
    }
});
