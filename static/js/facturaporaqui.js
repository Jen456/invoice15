// Apply presentation defaults without changing chart data or application flows.
(function () {
    if (!window.Highcharts) return;
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    Highcharts.setOptions({
        colors: ['#CA462C', '#176581', '#44BADD', '#226E59', '#163B50', '#94613A'],
        chart: {style: {fontFamily: 'system-ui, sans-serif', fontSize: '16px'}, animation: !reduced},
        plotOptions: {series: {animation: reduced ? false : {duration: 650}}},
        legend: {itemStyle: {color: '#163B50', fontSize: '15px'}},
        xAxis: {labels: {style: {color: '#526B7A', fontSize: '14px'}}},
        yAxis: {labels: {style: {color: '#526B7A', fontSize: '14px'}}},
        credits: {enabled: false}
    });
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
