/* Solo presentación del formset Django; cálculo y validación permanecen en servidor. */
(function () {
    'use strict';
    const button = document.getElementById('fp-retencion-agregar');
    const container = document.getElementById('fp-retencion-lineas');
    const template = document.getElementById('fp-retencion-linea-vacia');
    const total = document.querySelector('[name="lineas-TOTAL_FORMS"]');
    const maximum = document.querySelector('[name="lineas-MAX_NUM_FORMS"]');
    const status = document.getElementById('fp-retencion-lineas-estado');
    if (!button || !container || !template || !total || !maximum) return;
    const limit = Math.min(10, Number(maximum.value));
    function update() {
        button.disabled = Number(total.value) >= limit;
        status.textContent = total.value + ' de ' + limit + ' líneas disponibles. Puedes dejar vacías las que no uses.';
    }
    button.hidden = false;
    button.addEventListener('click', function () {
        const index = Number(total.value);
        if (index >= limit) return;
        const fragment = document.createElement('template');
        fragment.innerHTML = template.innerHTML.replace(/__prefix__/g, String(index)).replace(/__numero__/g, String(index + 1));
        const first = fragment.content.querySelector('select, input');
        container.appendChild(fragment.content);
        total.value = String(index + 1);
        update();
        if (first) first.focus();
    });
    update();
}());
