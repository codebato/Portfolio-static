(function () {
    // Sadece bu iki değer kabul ediliyor; localStorage'a elle yazılan başka bir değer yok sayılır
    const THEMES = ['dark', 'light'];

    // Gizli sekme veya engellenmiş depolamada localStorage hata fırlatabilir, bu yüzden try/catch
    function readTheme() {
        try {
            const saved = localStorage.getItem('theme');
            return THEMES.includes(saved) ? saved : 'dark';
        } catch (e) {
            return 'dark';
        }
    }

    function saveTheme(theme) {
        try {
            localStorage.setItem('theme', theme);
        } catch (e) {
            // Kaydedilemezse tema sadece bu oturumda geçerli olur, sorun değil
        }
    }

    function updateIcon(theme) {
        const icon = document.getElementById('theme-icon');
        if (!icon) return;
        icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
    }

    // Bu satır head'de çalışıyor: sayfa çizilmeden tema uygulanır
    document.documentElement.setAttribute('data-theme', readTheme());

    document.addEventListener('DOMContentLoaded', function () {
        // ---------- Tema butonu ----------
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            updateIcon(readTheme());

            toggleBtn.addEventListener('click', function () {
                const current = document.documentElement.getAttribute('data-theme');
                const next = current === 'dark' ? 'light' : 'dark';

                document.documentElement.setAttribute('data-theme', next);
                saveTheme(next);
                updateIcon(next);
            });
        }

        // ---------- E-posta linki ----------
        // Adres HTML'de "kullanici@domain" şeklinde geçmiyor; burada birleştiriliyor.
        // Basit botlar sayfayı regex ile tarar ve JS çalıştırmaz, bu yüzden adresi göremez.
        const emailLink = document.getElementById('email-link');
        if (emailLink) {
            const user = emailLink.dataset.user;
            const domain = emailLink.dataset.domain;
            if (user && domain) {
                emailLink.href = 'mailto:' + user + '@' + domain;
                emailLink.hidden = false;
            }
        }
    });
})();
