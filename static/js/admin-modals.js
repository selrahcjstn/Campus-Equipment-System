/* Enhance ordinary Create/Edit links; existing form URLs remain the fallback. */
(() => {
    const dialog = document.querySelector('[data-admin-form-dialog]');
    if (!(dialog instanceof HTMLDialogElement) || !dialog.showModal || !window.fetch) return;

    const content = dialog.querySelector('[data-admin-form-content]');
    const title = dialog.querySelector('#admin-form-title');
    const description = dialog.querySelector('#admin-form-description');
    let trigger, controller, initialValues, saving = false, uncertain = false;
    const values = (form) => JSON.stringify([...new FormData(form)].filter(([name]) => name !== 'csrfmiddlewaretoken'));
    const setBusy = (busy) => {
        saving = busy;
        dialog.setAttribute('aria-busy', String(busy));
        dialog.querySelectorAll('button').forEach((button) => { button.disabled = busy; });
    };
    const close = () => {
        if (saving) return;
        const form = content.querySelector('form');
        if (form && initialValues !== values(form) && !window.confirm('Discard your unsaved changes?')) return;
        dialog.close();
    };
    const notice = (message, href, label) => {
        const box = document.createElement('div');
        box.className = 'admin-form-dialog__notice';
        box.setAttribute('role', 'alert');
        box.tabIndex = -1;
        const text = document.createElement('p');
        text.textContent = message;
        const link = document.createElement('a');
        link.href = href;
        link.textContent = label;
        box.append(text, link);
        return box;
    };
    const installForm = (html, resetValues = false) => {
        const documentFragment = new DOMParser().parseFromString(html, 'text/html');
        const fragment = documentFragment.querySelector('[data-admin-modal-content]');
        if (!fragment || !fragment.querySelector('form[data-admin-modal-form], [data-admin-modal-unavailable]')) throw new Error('Missing form');
        content.replaceChildren(document.importNode(fragment, true));
        title.textContent = fragment.dataset.title;
        description.textContent = fragment.dataset.description;
        const form = content.querySelector('form');
        if (!form) {
            initialValues = null;
            content.querySelector('[data-admin-modal-unavailable]').focus();
            return;
        }
        if (resetValues) initialValues = values(form);
        form.querySelectorAll('.form-field').forEach((wrapper) => {
            const ids = [...wrapper.querySelectorAll('.field-help[id], .field-errors[id]')].map((item) => item.id);
            wrapper.querySelectorAll('input, select, textarea').forEach((field) => {
                const describedBy = new Set([...(field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean), ...ids]);
                if (describedBy.size) field.setAttribute('aria-describedby', [...describedBy].join(' '));
                if (wrapper.classList.contains('has-errors')) field.setAttribute('aria-invalid', 'true');
            });
        });
        (form.querySelector('.has-errors input, .has-errors textarea, .has-errors select, [role="alert"]') || form.querySelector('input:not([type="hidden"]), select, textarea'))?.focus();
    };

    document.addEventListener('click', async (event) => {
        const link = event.target.closest('a[data-admin-form]');
        if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || new URL(link.href).origin !== location.origin) return;
        event.preventDefault();
        if (dialog.open) return;
        trigger = link;
        initialValues = null;
        uncertain = false;
        controller = new AbortController();
        title.textContent = link.dataset.adminForm;
        description.textContent = 'Loading form…';
        content.replaceChildren();
        dialog.showModal();
        document.body.classList.add('modal-open');
        dialog.setAttribute('aria-busy', 'true');
        try {
            const response = await fetch(link.href, { headers: { 'X-Admin-Modal': '1' }, signal: controller.signal, credentials: 'same-origin' });
            if (!response.ok || response.redirected) throw new Error('Unable to load form');
            const html = await response.text();
            if (dialog.open) installForm(html, true);
        } catch (error) {
            if (error.name !== 'AbortError' && dialog.open) {
                content.replaceChildren(notice('Unable to load this form. You can use the full page instead.', link.href, 'Open full page'));
                content.firstElementChild.focus();
            }
        } finally {
            dialog.setAttribute('aria-busy', 'false');
        }
    });

    dialog.addEventListener('click', (event) => {
        if (event.target.closest('[data-admin-form-close]')) close();
    });
    dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
    dialog.addEventListener('close', () => {
        controller?.abort();
        content.replaceChildren();
        document.body.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
        trigger?.focus();
    });
    dialog.addEventListener('submit', async (event) => {
        const form = event.target.closest('form[data-admin-modal-form]');
        if (!form) return;
        event.preventDefault();
        if (saving || uncertain) return;
        const data = new FormData(form);
        const submitter = form.querySelector('[type="submit"]');
        const label = submitter.textContent;
        setBusy(true);
        submitter.textContent = 'Saving…';
        try {
            const response = await fetch(form.action, { method: 'POST', body: data, headers: { 'X-Admin-Modal': '1' }, credentials: 'same-origin' });
            if (!response.redirected && response.ok && response.headers.get('Content-Type')?.includes('application/json') && (await response.json()).saved) {
                dialog.close();
                location.reload(); // Keep the list's search, filters, sorting and page intact.
                return;
            }
            if (!response.redirected && [422, 409].includes(response.status)) {
                installForm(await response.text());
            } else {
                throw new Error('Unable to confirm save');
            }
        } catch {
            uncertain = true;
            form.prepend(notice('Unable to confirm whether changes were saved. Reload the list before trying again.', location.href, 'Reload list'));
            form.querySelector('[role="alert"]').focus();
        } finally {
            setBusy(false);
            if (submitter.isConnected) submitter.textContent = label;
            if (uncertain) form.querySelector('[type="submit"]').disabled = true;
        }
    });
})();
