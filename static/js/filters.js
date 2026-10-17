/* Progressive enhancement: the server remains responsible for filtering and validation. */
document.querySelectorAll('[data-filter-toolbar]').forEach((form) => {
    const search = form.querySelector('input[type="search"]');
    const panel = form.querySelector('details');
    const fieldGroup = panel?.querySelector('.filter-toolbar__controls');
    const fields = fieldGroup ? [...fieldGroup.children] : [];
    const mobile = window.matchMedia('(max-width: 639px)');
    const chips = form.querySelector('.filter-toolbar__chips');
    const count = form.querySelector('.filter-toolbar__count');
    const controls = [...form.querySelectorAll('.filter-toolbar__controls input, .filter-toolbar__controls select')];
    const signature = () => new URLSearchParams(new FormData(form)).toString();
    let lastSubmission = signature();
    let timer;
    let composing = false;
    const focusKey = `filter-focus:${location.pathname}`;

    const setPanel = () => {
        if (!panel) return;
        // Desktop fields share one wrapping row; mobile keeps a native disclosure.
        // Move the original nodes so values, labels and GET names stay intact.
        if (mobile.matches) {
            fieldGroup.append(...fields);
            panel.hidden = false;
            panel.open = Boolean(form.querySelector('.has-errors, .filter-toolbar__errors'));
        } else {
            fields.forEach((field) => form.insertBefore(field, panel));
            panel.hidden = true;
        }
    };
    setPanel();
    mobile.addEventListener('change', setPanel);

    const renderChips = () => {
        chips.replaceChildren();
        let activeCount = 0;
        controls.forEach((control) => {
            const defaultValue = control.tagName === 'SELECT' ? control.options[0]?.value : '';
            if (!control.value || control.value === defaultValue) return;
            activeCount += 1;
            // Required dates (the activity chart) cannot be removed independently.
            if (control.required && control.type === 'date') return;
            const label = control.labels[0]?.textContent.trim() || control.name;
            const value = control.tagName === 'SELECT' ? control.selectedOptions[0].textContent : control.value;
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'filter-toolbar__chip';
            chip.setAttribute('aria-label', `Remove ${label}: ${value}`);
            const text = document.createElement('span');
            text.textContent = `${label}: ${value}`;
            const close = document.createElement('span');
            close.textContent = '×';
            close.setAttribute('aria-hidden', 'true');
            chip.append(text, close);
            chip.addEventListener('click', () => {
                control.value = defaultValue || '';
                control.dispatchEvent(new Event('change', { bubbles: true }));
            });
            chips.append(chip);
        });
        chips.hidden = !chips.children.length;
        if (count) {
            count.textContent = activeCount;
            count.hidden = !activeCount;
        }
    };

    const apply = () => {
        clearTimeout(timer);
        if (composing || signature() === lastSubmission) return;
        // Reveal an invalid mobile control before the browser tries to focus it.
        if (!form.checkValidity() && panel) panel.open = true;
        form.requestSubmit();
    };
    form.addEventListener('submit', () => {
        clearTimeout(timer);
        lastSubmission = signature();
        const focused = document.activeElement;
        if (focused === search || controls.includes(focused)) {
            try {
                sessionStorage.setItem(focusKey, JSON.stringify({ name: focused.name, value: focused.value, start: focused.selectionStart, end: focused.selectionEnd, expanded: panel?.open, time: Date.now() }));
            } catch { /* Storage may be disabled; GET submission still works. */ }
        }
    });
    controls.forEach((control) => control.addEventListener('change', () => {
        renderChips();
        apply();
    }));
    if (search) {
        const schedule = () => {
            clearTimeout(timer);
            if (!composing) timer = setTimeout(apply, 350);
        };
        search.addEventListener('input', schedule);
        search.addEventListener('compositionstart', () => { composing = true; clearTimeout(timer); });
        search.addEventListener('compositionend', () => { composing = false; schedule(); });
    }
    try {
        const saved = JSON.parse(sessionStorage.getItem(focusKey));
        sessionStorage.removeItem(focusKey);
        const focused = [search, ...controls].find((control) => control && control.name === saved?.name && control.value === saved.value);
        if (focused && Date.now() - saved.time < 10000) {
            if (panel && saved.expanded) panel.open = true;
            focused.focus({ preventScroll: true });
            if (focused === search) focused.setSelectionRange(saved.start, saved.end);
        }
    } catch { /* Focus restoration is optional. */ }
    renderChips();
    form.setAttribute('data-enhanced', '');
});
