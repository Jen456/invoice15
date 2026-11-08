(() => {
    const form = document.querySelector('#fp-diseno-form');
    const frame = document.querySelector('#fp-diseno-preview');
    const reset = document.querySelector('#fp-diseno-reset');
    const abrir = document.querySelector('#fp-diseno-abrir');   // en móviles el PDF no se ve dentro del iframe
    if (!form || !frame || !reset) return;

    const colors = ['primary', 'secondary'].map((name) => form.elements.namedItem(name));
    const selected = () => form.querySelector('input[name="style"]:checked');
    const defaultColors = (option) => [option.dataset.primary, option.dataset.secondary];
    const applyColors = (values) => colors.forEach((input, index) => { input.value = values[index]; });
    let previous = selected();
    let timer;

    function schedulePreview() {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
            const option = selected();
            if (!option) return;
            const url = new URL(form.dataset.previewUrl, window.location.origin);
            if (url.origin !== window.location.origin) return;
            url.searchParams.set('style', option.value);
            for (const input of colors) url.searchParams.set(input.name, input.value);
            frame.src = url.href;
            if (abrir) abrir.href = url.href;
        }, 260);
    }

    form.addEventListener('change', (event) => {
        if (event.target.name !== 'style') return;
        const next = selected();
        if (!next) return;
        if (previous && defaultColors(previous).every((color, index) =>
            colors[index].value.toUpperCase() === color.toUpperCase())) applyColors(defaultColors(next));
        previous = next;
        schedulePreview();
    });
    for (const input of colors) input.addEventListener('input', schedulePreview);
    reset.hidden = false;
    reset.addEventListener('click', () => {
        const option = selected();
        if (!option) return;
        applyColors(defaultColors(option));
        schedulePreview();
    });
})();
