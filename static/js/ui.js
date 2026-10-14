/* Presentation only: auth scrolling, navigation drawers, field errors, dialogs. */
document.documentElement.classList.add('js');

const authShowcase = document.querySelector('.auth-showcase');
const authPanel = document.querySelector('.auth-panel');
if (authShowcase && authPanel) {
    authShowcase.addEventListener('wheel', (event) => {
        if (window.matchMedia('(max-width: 700px)').matches || authPanel.scrollHeight <= authPanel.clientHeight) return;
        event.preventDefault();
        authPanel.scrollBy({ top: event.deltaY, left: 0 });
    }, { passive: false });
}

document.querySelectorAll('.form-field').forEach((wrapper) => {
    const controls = wrapper.querySelectorAll('input:not([type="hidden"]), select, textarea');
    const descriptions = wrapper.querySelectorAll('.field-help[id], .field-errors[id]');
    controls.forEach((control) => {
        const ids = new Set((control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
        descriptions.forEach((description) => ids.add(description.id));
        if (ids.size) control.setAttribute('aria-describedby', [...ids].join(' '));
        if (wrapper.classList.contains('has-errors')) control.setAttribute('aria-invalid', 'true');
    });
});

const sidebar = document.getElementById('app-sidebar');
const toggle = document.querySelector('[data-sidebar-toggle]');
const backdrop = document.querySelector('.sidebar-backdrop');
if (sidebar && toggle && backdrop) {
    const mobile = window.matchMedia('(max-width: 1023px)');
    const workspace = document.querySelector('.app-workspace');
    let previousFocus;
    const setNavigation = (open, restoreFocus = true) => {
        const isOpen = open && mobile.matches;
        sidebar.classList.toggle('is-open', isOpen);
        backdrop.hidden = !isOpen;
        toggle.setAttribute('aria-expanded', String(isOpen));
        sidebar.inert = mobile.matches && !isOpen;
        workspace.inert = isOpen;
        document.body.classList.toggle('navigation-open', isOpen);
        if (isOpen) {
            previousFocus = document.activeElement;
            sidebar.querySelector('[data-sidebar-close]').focus();
        } else if (restoreFocus && previousFocus) {
            previousFocus.focus();
            previousFocus = null;
        }
    };
    toggle.addEventListener('click', () => setNavigation(!sidebar.classList.contains('is-open')));
    document.querySelectorAll('[data-sidebar-close]').forEach((button) => {
        button.addEventListener('click', () => setNavigation(false));
    });
    sidebar.addEventListener('keydown', (event) => {
        if (!mobile.matches || !sidebar.classList.contains('is-open')) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            setNavigation(false);
        }
        if (event.key === 'Tab') {
            const focusable = [...sidebar.querySelectorAll('a[href], button:not(:disabled)')].filter((element) => element.getClientRects().length);
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });
    mobile.addEventListener('change', () => {
        const focusWasInSidebar = sidebar.contains(document.activeElement);
        setNavigation(false, false);
        if (mobile.matches && focusWasInSidebar) toggle.focus();
    });
    sidebar.querySelectorAll('a[href]').forEach((link) => {
        link.addEventListener('click', () => {
            if (mobile.matches) setNavigation(false);
        });
    });
    setNavigation(false, false);
}

document.querySelectorAll('[data-modal-target]').forEach((button) => {
    button.addEventListener('click', () => {
        const modal = document.getElementById(button.dataset.modalTarget);
        if (modal instanceof HTMLDialogElement && !modal.open) {
            modal.showModal();
            document.body.classList.add('modal-open');
        }
    });
});
document.querySelectorAll('dialog.modal').forEach((modal) => {
    modal.querySelectorAll('[data-modal-close]').forEach((button) => {
        button.addEventListener('click', () => modal.close());
    });
    modal.addEventListener('close', () => {
        document.body.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
    });
});

// Reusable form confirmation; server-side confirmation remains required.
document.querySelectorAll('form[data-confirm-dialog], form[data-submit-loading]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        const dialog = document.getElementById(form.dataset.confirmDialog);
        if (dialog instanceof HTMLDialogElement && !event.submitter?.hasAttribute('data-confirmed')) {
            event.preventDefault();
            if (!dialog.open) dialog.showModal();
            document.body.classList.add('modal-open');
            return;
        }
        form.setAttribute('aria-busy', 'true');
        if (event.submitter && !event.submitter.name) {
            event.submitter.disabled = true;
            event.submitter.textContent = 'Saving…';
        }
    });
});
