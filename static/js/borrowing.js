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
const requestForm = document.getElementById('borrowing-request-form');
if (requestForm) {
    const rows = requestForm.querySelector('[data-equipment-rows]');
    const template = requestForm.querySelector('[data-equipment-template]');
    const addButton = requestForm.querySelector('[data-add-equipment]');
    const rowStatus = requestForm.querySelector('[data-equipment-status]');
    const total = requestForm.querySelector('[name="items-TOTAL_FORMS"]');
    const initial = requestForm.querySelector('[name="items-INITIAL_FORMS"]');
    const maximum = +requestForm.dataset.maxEquipment;
    const equipmentRows = () => [...rows.querySelectorAll('[data-equipment-row]')];
    const choices = () => equipmentRows().map((row) => row.querySelector('select'));

    function updateRows() {
        const currentRows = equipmentRows();
        currentRows.forEach((row, index) => {
            row.querySelector('[data-row-number]').textContent = index + 1;
            row.querySelectorAll('[name], [id], [for], [aria-describedby]').forEach((element) => {
                ['name', 'id', 'for', 'aria-describedby'].forEach((attribute) => {
                    const value = element.getAttribute(attribute);
                    if (value) element.setAttribute(attribute, value.replace(/items-(?:\d+|__prefix__)-/g, `items-${index}-`));
                });
            });
            const remove = row.querySelector('[data-remove-equipment]');
            remove.hidden = index === 0;
            remove.value = `remove:items-${index}`;
            remove.setAttribute('aria-label', `Remove equipment ${index + 1}`);
        });
        total.value = currentRows.length;
        initial.value = Math.min(+initial.value, currentRows.length);
        addButton.disabled = currentRows.length >= maximum;
        const selects = choices();
        selects.forEach((select) => {
            const others = selects.filter((other) => other !== select).map((other) => other.value).filter(Boolean);
            [...select.options].forEach((option) => {
                option.disabled = !!option.value && option.value !== select.value && others.includes(option.value);
            });
            select.setCustomValidity(select.value && others.includes(select.value) ? 'Each equipment item can be selected only once.' : '');
        });
    }

    function addRow() {
        if (equipmentRows().length >= maximum) return null;
        const row = template.content.firstElementChild.cloneNode(true);
        rows.append(row);
        updateRows();
        rowStatus.textContent = `Equipment row added. ${equipmentRows().length} of ${maximum} rows.`;
        return row;
    }

    addButton.addEventListener('click', (event) => {
        event.preventDefault();
        addRow()?.querySelector('select').focus();
    });
    rows.addEventListener('click', (event) => {
        const remove = event.target.closest('[data-remove-equipment]');
        if (!remove) return;
        event.preventDefault();
        const row = remove.closest('[data-equipment-row]');
        const index = equipmentRows().indexOf(row);
        if (index < 1) return;
        row.remove();
        updateRows();
        equipmentRows()[index - 1].querySelector('select').focus();
        rowStatus.textContent = `Equipment row removed. ${equipmentRows().length} of ${maximum} rows.`;
    });
    rows.addEventListener('change', updateRows);
    updateRows();

    document.querySelectorAll('[data-select-equipment]').forEach((button) => {
        button.addEventListener('click', () => {
            const selected = choices().find((choice) => choice.value === button.dataset.selectEquipment);
            if (selected) {
                catalogStatus.textContent = 'This equipment is already selected. Adjust its quantity below.';
                selected.focus();
                return;
            }
            const empty = choices().find((choice) => !choice.value) || addRow()?.querySelector('select');
            if (!empty) {
                catalogStatus.textContent = `You can select up to ${maximum} distinct equipment items. Remove or replace a selection to choose another item.`;
                return;
            }
            empty.value = button.dataset.selectEquipment;
            empty.dispatchEvent(new Event('change', { bubbles: true }));
            empty.closest('fieldset').querySelector('input').focus();
            catalogStatus.textContent = 'Equipment selected. Set the quantity and due date below.';
        });
    });
}

document.querySelectorAll('form[data-borrow-confirm], form[data-submit-loading]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        if (event.defaultPrevented || event.submitter?.name === 'row_action') return;
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
