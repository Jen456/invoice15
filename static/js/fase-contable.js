/* Presentación de la fase contable. No calcula importes, permisos ni estados fiscales. */
(function () {
    'use strict';
    var alcance = /^\/(proformas|comprobantes|importacion|reports)\//.test(location.pathname) ||
        /^\/pos\/(purchase|provider|expenses|type\/expense|ctas\/collect|debts\/pay|sale|credit\/note|company)\//.test(location.pathname);
    if (!alcance) return;
    document.body.classList.add('fp-stage');
    var root = document.querySelector('.content-wrapper');
    if (!root) return;
    function preparar() {
        root.querySelectorAll('form table:not(.dataTable):not(#data)').forEach(function (tabla) {
            var headers = Array.from(tabla.querySelectorAll('thead tr:first-child th'));
            if (headers.length < 3) return;
            tabla.classList.add('fp-stage-lines');
            tabla.querySelectorAll('tbody > tr').forEach(function (fila) {
                if (fila.querySelector('[colspan]')) return;
                Array.from(fila.cells).forEach(function (celda, indice) {
                    if (!celda.hasAttribute('data-label')) celda.setAttribute('data-label', headers[indice] ? headers[indice].textContent.trim() : 'Detalle');
                    celda.querySelectorAll('input:not([type="hidden"]),select,textarea').forEach(function (campo) {
                        if (!campo.getAttribute('aria-label') && !campo.labels.length) campo.setAttribute('aria-label', celda.getAttribute('data-label') || 'Valor');
                    });
                });
            });
        });
        root.querySelectorAll('.table-responsive').forEach(function (tabla) {
            if (!tabla.hasAttribute('tabindex')) { tabla.tabIndex = 0; tabla.setAttribute('role', 'region'); tabla.setAttribute('aria-label', 'Tabla: desplaza para ver todas las columnas'); }
        });
    }
    preparar();
    var pendiente = false;
    new MutationObserver(function () {
        if (pendiente) return;
        pendiente = true;
        requestAnimationFrame(function () { preparar(); pendiente = false; });
    }).observe(root, {childList: true, subtree: true});
})();
