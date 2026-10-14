document.querySelectorAll('[data-return-unit]').forEach((row) => {
    const selected = row.querySelector('input[type="checkbox"]');
    const condition = row.querySelector('select');
    const notes = row.querySelector('textarea');
    const validateSelection = () => {
        condition.required = selected.checked;
        notes.required = selected.checked && condition.value === 'DAMAGED';
    };
    selected.addEventListener('change', validateSelection);
    condition.addEventListener('change', validateSelection);
    validateSelection();
});

document.querySelectorAll('form[data-confirm-operation]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        const dialog = document.getElementById(form.dataset.confirmOperation);
        if (event.submitter?.hasAttribute('data-confirmed-submit') || !(dialog instanceof HTMLDialogElement)) {
            form.setAttribute('aria-busy', 'true');
            if (event.submitter) {
                event.submitter.disabled = true;
                event.submitter.textContent = 'Saving…';
            }
            const status = form.querySelector('[data-operation-status]');
            if (status) status.textContent = 'Saving your changes…';
            return;
        }
        event.preventDefault();
        const summary = dialog.querySelector('[data-confirm-summary]');
        summary.replaceChildren();
        form.querySelectorAll('[data-return-unit]').forEach((row) => {
            if (!row.querySelector('input[type="checkbox"]').checked) return;
            const condition = row.querySelector('select');
            const item = document.createElement('li');
            item.textContent = `${row.dataset.unitLabel} — ${condition.selectedOptions[0].textContent}`;
            summary.append(item);
        });
        if (form.id === 'return-form' && !summary.children.length) {
            const status = form.querySelector('[data-operation-status]');
            status.textContent = 'Select at least one physical unit to return.';
            form.querySelector('[data-return-unit] input[type="checkbox"]')?.focus();
            return;
        }
        dialog.showModal();
        document.body.classList.add('modal-open');
    });
});

document.querySelectorAll('[data-print-slip]').forEach((button) => {
    button.addEventListener('click', () => window.print());
});
