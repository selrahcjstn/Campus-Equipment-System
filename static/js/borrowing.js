const catalogStatus = document.querySelector('[data-catalog-status]');
document.querySelector('[data-catalog-search]')?.addEventListener('input', (event) => {
    const query = event.target.value.toLocaleLowerCase().trim();
    let matches = 0;
    document.querySelectorAll('[data-catalog-entry]').forEach((entry) => {
        entry.hidden = !entry.dataset.searchText.toLocaleLowerCase().includes(query);
        if (!entry.hidden) matches += 1;
    });
    catalogStatus.textContent = `${matches} equipment items match your search.`;
});
document.querySelectorAll('[data-select-equipment]').forEach((button) => {
    button.addEventListener('click', () => {
        const choices = [...document.querySelectorAll('.borrowing-item-row select')];
        if (choices.some((choice) => choice.value === button.dataset.selectEquipment)) {
            catalogStatus.textContent = 'This equipment is already selected. Adjust its quantity below.';
            choices.find((choice) => choice.value === button.dataset.selectEquipment).focus();
            return;
        }
        const empty = choices.find((choice) => !choice.value);
        if (!empty) {
            catalogStatus.textContent = 'All equipment slots are filled. Replace a selection below to choose another item.';
            return;
        }
        empty.value = button.dataset.selectEquipment;
        empty.dispatchEvent(new Event('change', { bubbles: true }));
        empty.closest('fieldset').querySelector('input').focus();
        catalogStatus.textContent = 'Equipment selected. Set the quantity and due date below.';
    });
});

document.querySelectorAll('form[data-borrow-confirm], form[data-submit-loading]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        const dialog = document.getElementById(form.dataset.borrowConfirm);
        if (dialog instanceof HTMLDialogElement && !event.submitter?.hasAttribute('data-borrow-confirmed')) {
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
