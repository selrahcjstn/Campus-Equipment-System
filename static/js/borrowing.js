const requestForm = document.getElementById('borrowing-request-form');
if (requestForm) {
    const rows = requestForm.querySelector('[data-equipment-rows]');
    const template = requestForm.querySelector('[data-equipment-template]');
    const selectionStep = requestForm.querySelector('[data-selection-step]');
    const detailsStep = requestForm.querySelector('[data-details-step]');
    const continueButton = requestForm.querySelector('[data-continue]');
    const backButton = requestForm.querySelector('[data-back]');
    const addAnother = requestForm.querySelector('[data-add-another]');
    const catalogPicker = requestForm.querySelector('[data-catalog-picker]');
    const selectedSection = requestForm.querySelector('[data-selected-section]');
    const summary = requestForm.querySelector('[data-selection-summary]');
    const selectionError = requestForm.querySelector('[data-selection-error]');
    const catalogStatus = requestForm.querySelector('[data-catalog-status]');
    const catalogSearch = requestForm.querySelector('[data-catalog-search]');
    const maximum = +requestForm.dataset.maxEquipment;
    const equipmentRows = () => [...rows.querySelectorAll('[data-equipment-row]')];
    const selectedRows = () => equipmentRows().filter((row) => row.querySelector('select').value);
    const equipment = new Map([...requestForm.querySelectorAll('[data-select-equipment]')].map((button) => {
        const entry = button.closest('[data-catalog-entry]');
        return [button.dataset.selectEquipment, {button, entry, name: entry.dataset.equipmentName,
            category: entry.dataset.equipmentCategory, available: +entry.dataset.available}];
    }));

    function validSelection() {
        const ids = selectedRows().map((row) => row.querySelector('select').value);
        return ids.length >= 1 && ids.length <= maximum && new Set(ids).size === ids.length
            && ids.every((id) => equipment.get(id)?.available > 0)
            && equipmentRows().every((row) => row.querySelector('select').value || ['', '1'].includes(row.querySelector('input').value));
    }

    function updateRows() {
        const currentRows = equipmentRows();
        summary.replaceChildren();
        currentRows.forEach((row, index) => {
            row.querySelector('[data-row-number]').textContent = index + 1;
            row.querySelectorAll('[name], [id], [for], [aria-describedby]').forEach((element) => {
                ['name', 'id', 'for', 'aria-describedby'].forEach((attribute) => {
                    const value = element.getAttribute(attribute);
                    if (value) element.setAttribute(attribute, value.replace(/items-(?:\d+|__prefix__)-/g, `items-${index}-`));
                });
            });
            const choice = row.querySelector('select');
            const item = equipment.get(choice.value);
            const quantity = row.querySelector('input');
            row.querySelector('[data-equipment-picker]').hidden = true;
            row.querySelector('[data-remove-equipment]').hidden = true;
            row.querySelector('[data-equipment-display]').hidden = false;
            row.hidden = !choice.value;
            quantity.required = !!choice.value;
            quantity.disabled = !choice.value;
            quantity.dataset.policyMax ||= quantity.max;
            quantity.max = item ? Math.min(+quantity.dataset.policyMax, item.available) : quantity.dataset.policyMax;
            row.querySelector('[data-selected-name]').textContent = item?.name || 'Unavailable equipment';
            row.querySelector('[data-selected-availability]').textContent = item ? `${item.category} · ${item.available} available` : 'Return to equipment selection to choose an available item.';
            if (!choice.value) return;
            const selected = document.createElement('li');
            const info = document.createElement('div');
            info.className = 'borrowing-selected-info';
            const name = document.createElement('strong');
            name.textContent = item?.name || 'Unavailable equipment';
            const metadata = document.createElement('p');
            metadata.className = 'caption';
            metadata.textContent = item ? `${item.category} · ${item.available} available ${item.available === 1 ? 'unit' : 'units'}` : 'Choose another available item.';
            info.append(name, metadata);
            const actions = document.createElement('div');
            actions.className = 'borrowing-selected-actions';
            const badge = document.createElement('span');
            badge.className = 'badge badge--inactive';
            badge.textContent = 'Selected';
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'borrowing-remove';
            remove.dataset.removeSelection = index;
            remove.textContent = 'Remove';
            remove.setAttribute('aria-label', `Remove ${name.textContent}`);
            actions.append(badge, remove);
            selected.append(info, actions);
            summary.append(selected);
        });
        requestForm.querySelector('[name="items-TOTAL_FORMS"]').value = currentRows.length;
        const initial = requestForm.querySelector('[name="items-INITIAL_FORMS"]');
        initial.value = Math.min(+initial.value, currentRows.length);
        const ids = selectedRows().map((row) => row.querySelector('select').value);
        equipment.forEach((item, id) => {
            const added = ids.includes(id);
            item.button.disabled = added || item.available === 0 || ids.length >= maximum;
            item.button.textContent = added ? 'Selected' : 'Add';
            item.button.setAttribute('aria-label', added ? `${item.name} selected` : `Add ${item.name}`);
        });
        requestForm.querySelector('[data-selection-count]').textContent = `${ids.length} of ${maximum} selected`;
        requestForm.querySelector('[data-selection-empty]').hidden = ids.length > 0;
        selectedSection.hidden = ids.length === 0;
        addAnother.hidden = ids.length === 0 || ids.length >= maximum;
        continueButton.hidden = !validSelection();
        selectionError.hidden = true;
    }

    function filterCatalog(announce = true) {
        const query = catalogSearch.value.toLocaleLowerCase().trim();
        let matches = 0;
        equipment.forEach((item) => {
            item.entry.hidden = !item.entry.dataset.searchText.toLocaleLowerCase().includes(query);
            if (!item.entry.hidden) matches += 1;
        });
        requestForm.querySelector('[data-search-empty]').hidden = matches > 0;
        catalogStatus.textContent = announce ? `${matches} equipment ${matches === 1 ? 'item matches' : 'items match'} your search.` : '';
    }

    function setCatalogOpen(open, focus = false) {
        catalogPicker.hidden = !open;
        addAnother.setAttribute('aria-expanded', String(open));
        addAnother.textContent = open ? 'Hide equipment catalog' : 'Add another equipment';
        if (open && focus) catalogSearch.focus();
    }

    function showStep(step, focus = true) {
        requestForm.dataset.step = step;
        selectionStep.hidden = step !== 1;
        detailsStep.hidden = step !== 2;
        requestForm.querySelectorAll('[data-step-marker]').forEach((marker) => {
            if (+marker.dataset.stepMarker === step) marker.setAttribute('aria-current', 'step');
            else marker.removeAttribute('aria-current');
        });
        if (focus) (step === 1 ? selectionStep : detailsStep).querySelector('h2').focus();
    }

    equipment.forEach((item, id) => {
        item.button.addEventListener('click', () => {
            if (!item.available || selectedRows().length >= maximum || selectedRows().some((row) => row.querySelector('select').value === id)) return;
            let row = equipmentRows().find((candidate) => !candidate.querySelector('select').value);
            if (!row) {
                row = template.content.firstElementChild.cloneNode(true);
                rows.append(row);
            }
            row.querySelector('select').value = id;
            updateRows();
            setCatalogOpen(false);
            (continueButton.hidden ? summary.querySelector('li:last-child button') : continueButton)?.focus();
        });
    });
    summary.addEventListener('click', (event) => {
        const button = event.target.closest('[data-remove-selection]');
        if (!button) return;
        equipmentRows()[+button.dataset.removeSelection].remove();
        updateRows();
        if (!selectedRows().length) {
            catalogSearch.value = '';
            filterCatalog(false);
            setCatalogOpen(true, true);
        } else if (!catalogPicker.hidden) setCatalogOpen(true, true);
        else addAnother.focus();
    });
    addAnother.addEventListener('click', () => {
        const open = catalogPicker.hidden;
        if (open) {
            catalogSearch.value = '';
            filterCatalog(false);
        }
        setCatalogOpen(open, open);
    });
    catalogSearch.addEventListener('input', () => filterCatalog());
    catalogSearch.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') event.preventDefault();
    });
    continueButton.addEventListener('click', () => {
        if (validSelection()) showStep(2);
    });
    backButton.addEventListener('click', () => showStep(1));
    requestForm.addEventListener('submit', (event) => {
        if (requestForm.getAttribute('aria-busy') === 'true') {
            event.preventDefault();
            return;
        }
        if (event.submitter?.name === 'row_action') return;
        if (!validSelection()) {
            event.preventDefault();
            showStep(1);
            selectionError.textContent = `Select 1–${maximum} distinct, available equipment items before continuing.`;
            selectionError.hidden = false;
        } else if (requestForm.dataset.step !== '2') {
            event.preventDefault();
            showStep(2);
        } else if (!requestForm.checkValidity()) {
            event.preventDefault();
            requestForm.reportValidity();
        } else {
            requestForm.setAttribute('aria-busy', 'true');
            const submit = requestForm.querySelector('[data-final-submit]');
            submit.disabled = true;
            submit.textContent = 'Submitting…';
        }
    });
    window.addEventListener('pageshow', () => {
        requestForm.removeAttribute('aria-busy');
        const submit = requestForm.querySelector('[data-final-submit]');
        submit.disabled = false;
        submit.textContent = 'Submit Borrowing Request';
    });
    updateRows();
    setCatalogOpen(!validSelection());
    requestForm.noValidate = true;
    requestForm.querySelector('[data-fallback-controls]').hidden = true;
    requestForm.querySelector('[data-step-indicator]').hidden = false;
    backButton.hidden = false;
    showStep(requestForm.dataset.bound === 'true' && validSelection() ? 2 : 1, false);
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
