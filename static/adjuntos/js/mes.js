/* Consulta mensual común. Los cobros se leen en su API; nunca pasan por adjuntos. */
(function () {
    'use strict';
    var filtros = document.getElementById('fpRespaldosFiltros');
    if (filtros) {
        var filas = Array.from(document.querySelectorAll('[data-documento]'));
        filtros.hidden = false;
        function filtrar(valor) {
            var visibles = 0;
            filas.forEach(function (fila) {
                fila.hidden = valor !== 'todos' && Number(fila.dataset[valor]) <= 0;
                if (!fila.hidden) visibles++;
            });
            filtros.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.filtro === valor)); });
            document.getElementById('fpRespaldosResultado').textContent = visibles + ' de ' + filas.length + ' documentos';
            document.getElementById('fpRespaldosSinResultados').hidden = visibles !== 0;
        }
        filtros.addEventListener('click', function (e) {
            var boton = e.target.closest('[data-filtro]');
            if (boton) filtrar(boton.dataset.filtro);
        });
        filtrar('todos');
    }
    document.addEventListener('fp-adjuntos:cerrado', function (e) {
        if (e.detail && e.detail.cambios) window.location.reload();
    });

    document.addEventListener('fp-cobros:cerrado', function (e) {
        if (e.detail && e.detail.cambios) window.location.reload();
    });
}());
