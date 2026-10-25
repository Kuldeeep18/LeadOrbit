(function () {
    var saved = localStorage.getItem('theme');
    var theme = saved === 'light' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-bs-theme', theme);
    document.documentElement.style.colorScheme = theme;
})();

// Send logged-out visitors to login before app pages fire API calls that would 401.
(function () {
    var appPages = /\/(dashboard|leads|campaigns|campaign-builder|analytics|settings)\.html$/i;
    if (appPages.test(window.location.pathname) && !localStorage.getItem('access_token')) {
        window.location.replace('/login.html');
    }
})();
