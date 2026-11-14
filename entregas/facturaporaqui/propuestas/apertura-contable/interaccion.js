// Maqueta independiente: no consulta APIs ni persiste datos contables.
(function () {
    'use strict';
    var paso = new URLSearchParams(window.location.search).get('paso') || 'elegir';
    if (!['elegir', 'saldos', 'historial', 'validacion'].includes(paso)) paso = 'elegir';
    document.querySelectorAll('[data-panel]').forEach(function (panel) { panel.hidden = panel.dataset.panel !== paso; });
    document.querySelectorAll('[data-step]').forEach(function (link) {
        if (link.dataset.step === paso) link.setAttribute('aria-current', 'step');
    });
    document.querySelectorAll('input[name="modalidad"]').forEach(function (input) {
        input.addEventListener('change', function () {
            document.querySelectorAll('.choice').forEach(function (label) {
                label.classList.toggle('selected', label.querySelector('input').checked);
            });
        });
    });
    document.getElementById('continuar').addEventListener('click', function () {
        window.location.href = '?paso=' + document.querySelector('input[name="modalidad"]:checked').value;
    });
    document.querySelectorAll('[data-demo]').forEach(function (button) {
        button.addEventListener('click', function () {
            var mensaje = document.getElementById('mensaje');
            mensaje.hidden = false;
            mensaje.textContent = button.textContent.includes('diferencia')
                ? 'Ejemplo: debe 10.000 y haber 9.950 dejan una diferencia de 50. Se solicita corregir la fuente; no se inventa una cuenta para cuadrar.'
                : 'Demostración visual: no se envió, importó ni confirmó una apertura. La revisión real necesita el backend y los permisos correspondientes.';
            setTimeout(function () { mensaje.hidden = true; }, 9000);
        });
    });
}());
