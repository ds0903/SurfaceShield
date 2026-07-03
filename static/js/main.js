// Header shrink on scroll (desktop only)
const header = document.querySelector('.site-header');
if (header) {
    window.addEventListener('scroll', () => {
        if (window.innerWidth <= 768) return;
        const y = window.scrollY;
        if (!header.classList.contains('scrolled') && y > 60) {
            header.classList.add('scrolled');
        } else if (header.classList.contains('scrolled') && y < 30) {
            header.classList.remove('scrolled');
        }
    }, { passive: true });
}

// Hamburger menu
const hamburger = document.getElementById('hamburger');
const mainNav = document.getElementById('mainNav');

if (hamburger && mainNav) {
    hamburger.addEventListener('click', () => {
        mainNav.classList.toggle('open');
    });
}

// CONTACT US → scroll to footer contacts + highlight
document.querySelectorAll('.nav-contact-scroll').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const target = document.getElementById('footer-contact');
        if (!target) return;
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => {
            target.classList.add('highlighted');
            setTimeout(() => target.classList.remove('highlighted'), 2200);
        }, 600);
        // close mobile nav if open
        if (mainNav) mainNav.classList.remove('open');
    });
});

// Auto-dismiss messages
setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
        el.style.transition = 'opacity 0.5s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
    });
}, 4000);
