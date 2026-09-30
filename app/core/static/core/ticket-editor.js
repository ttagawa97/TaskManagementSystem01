'use strict';
const dialog = document.getElementById('markdown-preview-dialog');
if (dialog) {
    const content = document.getElementById('markdown-preview-content');
    const status = document.getElementById('preview-dialog-status');
    let requestNumber = 0;

    async function openPreview(source) {
        const currentRequest = ++requestNumber;
        dialog.showModal();
        content.replaceChildren();
        status.textContent = 'プレビューを読み込んでいます…';
        try {
            const form = source.closest('form');
            const response = await fetch('/markdown/preview', {
                method: 'POST', credentials: 'same-origin',
                headers: {'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value},
                body: new URLSearchParams({text: source.value})
            });
            if (!response.ok) throw new Error();
            const result = await response.json();
            if (currentRequest !== requestNumber || !dialog.open) return;
            content.innerHTML = result.html; // Server-rendered and sanitized Markdown only.
            status.textContent = '';
        } catch {
            if (currentRequest === requestNumber && dialog.open) {
                status.textContent = 'プレビューを表示できませんでした。入力内容は保持されています。';
            }
        }
    }

    document.getElementById('description-preview-button')?.addEventListener('click', () => {
        openPreview(document.getElementById('id_description_markdown'));
    });
    document.getElementById('comment-preview-button')?.addEventListener('click', () => {
        openPreview(document.querySelector('#comment-form textarea'));
    });
    document.getElementById('preview-close-button')?.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
        if (event.target === dialog) dialog.close();
    });
}
