document.querySelectorAll('form[data-inventory-confirm], form[data-inventory-loading]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        const dialog = document.getElementById(form.dataset.inventoryConfirm);
        if (dialog instanceof HTMLDialogElement && !event.submitter?.hasAttribute('data-inventory-confirmed')) {
            event.preventDefault();
            dialog.showModal();
            document.body.classList.add('modal-open');
            return;
        }
        form.setAttribute('aria-busy', 'true');
        if (event.submitter) {
            event.submitter.disabled = true;
            event.submitter.textContent = 'Saving…';
        }
    });
});
