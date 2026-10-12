// Presentation defaults; chart data and application flows stay on the backend.
(function () {
    if (!window.Chart) return;
    Chart.defaults.font.family = 'system-ui, sans-serif';
    Chart.defaults.font.size = 15;
    Chart.defaults.color = '#526B7A';
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;
})();
(function () {
    // Script runs before jQuery ready callbacks initialize each DataTable.
    if (window.jQuery && jQuery.fn.dataTable) {
        jQuery.extend(true, jQuery.fn.dataTable.defaults, {
            language: {search: 'Buscar:', lengthMenu: 'Mostrar _MENU_ registros', info: '_START_–_END_ de _TOTAL_ registros', infoEmpty: 'Sin registros', infoFiltered: '(de _MAX_ registros)', zeroRecords: 'No se encontraron resultados', emptyTable: 'Todavía no hay registros', loadingRecords: 'Cargando…', processing: 'Procesando…', paginate: {first: 'Primero', last: 'Último', next: 'Siguiente', previous: 'Anterior'}, aria: {sortAscending: ': ordenar ascendente', sortDescending: ': ordenar descendente'}}
        });
    }
    document.addEventListener('click', function (event) {
        var button = event.target.closest('.fp-toggle-secret');
        if (!button) return;
        var input = document.getElementById(button.getAttribute('aria-controls'));
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        button.setAttribute('aria-pressed', String(show));
        button.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && document.body.classList.contains('sidebar-open') && window.jQuery) {
            jQuery('[data-widget="pushmenu"]').PushMenu('collapse');
            var trigger = document.getElementById('collapsedMenu');
            if (trigger) trigger.focus();
        }
    });
})();

/* Mobile document lines: retain original cells, inputs and event handlers. */
(function () {
    function enhanceForms() {
        document.querySelectorAll('#frmForm table').forEach(function (table) {
            if (!table.querySelector('thead')) { table.classList.add('fp-form-totals'); return; }
            table.classList.add('fp-mobile-lines');
            var titles = Array.from(table.querySelectorAll('thead th')).map(function (th) { return th.textContent.trim(); });
            table.querySelectorAll('tbody tr').forEach(function (row) {
                if (row.children.length !== titles.length) { return; }
                Array.from(row.children).forEach(function (cell, i) { cell.dataset.label = titles[i];
                    cell.querySelectorAll('input,select').forEach(function (input) {
                        if (!input.hasAttribute('aria-label')) { input.setAttribute('aria-label', titles[i]); }
                    });
                    cell.querySelectorAll('a[rel="remove"]').forEach(function (button) {
                        button.setAttribute('role', 'button'); button.tabIndex = 0;
                        button.setAttribute('aria-label', 'Eliminar producto');
                    }); });
            });
        });
        document.querySelectorAll('#frmForm label:not([for])').forEach(function (label) {
            var group = label.closest('.form-group');
            var input = group && group.querySelector('input[id],select[id],textarea[id]');
            if (input) { label.htmlFor = input.id; }
        });
    }
    function start() {
        enhanceForms();
        var form = document.getElementById('frmForm');
        if (!form) { return; }
        form.addEventListener('keydown', function (event) {
            if (event.target.matches('a[rel="remove"]') && (event.key === 'Enter' || event.key === ' ')) {
                event.preventDefault(); event.target.click();
            }
        });
        var scheduled = false;
        new MutationObserver(function () {
            if (scheduled) { return; }
            scheduled = true;
            requestAnimationFrame(function () { scheduled = false; enhanceForms(); });
        }).observe(form, {childList: true, subtree: true});
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();
