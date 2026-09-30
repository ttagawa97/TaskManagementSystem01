'use strict';
const dropdowns = document.querySelectorAll('.search-dropdown');
for (const dropdown of dropdowns) {
    const refresh = () => {
        const selected = [...dropdown.querySelectorAll('input:checked')];
        const label = selected.length ? selected[0].nextElementSibling.textContent : '指定なし';
        dropdown.querySelector('[data-selection-label]').textContent = label + (selected.length > 1 ? ` 他${selected.length - 1}件` : '');
    };
    refresh();
    dropdown.addEventListener('change', refresh);
    dropdown.addEventListener('toggle', () => {
        if (dropdown.open) for (const other of dropdowns) if (other !== dropdown) other.open = false;
    });
    dropdown.addEventListener('keydown', event => {
        if (event.key === 'Escape') { dropdown.open = false; dropdown.querySelector('summary').focus(); }
    });
}
document.addEventListener('click', event => {
    for (const dropdown of dropdowns) if (!dropdown.contains(event.target)) dropdown.open = false;
});
