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
