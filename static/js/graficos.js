/*
 * FacturaPorAquí — gráficos con Chart.js (MIT).
 * fpaGrafico.pastel(id, etiquetas, valores, {formato: 'unidades'|'dolares'})
 * fpaGrafico.barras(id, categorias, series[{name, data}], {formato: 'dolares'})
 * Cada contenedor recibe un <canvas> con descripción accesible; volver a dibujar
 * en el mismo contenedor reemplaza el gráfico anterior.
 */
(function (window) {
    'use strict';
    var PALETA = ['#44BADD', '#CA462C', '#163B50', '#8ED4EB', '#E8836D', '#5B7A8C', '#F2B84B', '#7BC67E', '#9B7EDE', '#F06292', '#2A9D8F', '#B8860B'];
    var dinero = new Intl.NumberFormat('es-EC', {style: 'currency', currency: 'USD'});
    var numero = new Intl.NumberFormat('es-EC', {maximumFractionDigits: 2});
    var instancias = {};

    function formatear(valor, formato) {
        return formato === 'dolares' ? dinero.format(valor) : numero.format(valor) + (formato === 'unidades' ? ' u.' : '');
    }

    function lienzo(id, descripcion) {
        var contenedor = document.getElementById(id);
        if (!contenedor || typeof window.Chart === 'undefined') { return null; }
        if (instancias[id]) { instancias[id].destroy(); delete instancias[id]; }
        contenedor.innerHTML = '';
        contenedor.classList.add('fpa-grafico');
        if (!contenedor.style.height) { contenedor.style.minHeight = '340px'; }
        contenedor.style.position = 'relative';
        var canvas = document.createElement('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', descripcion);
        canvas.textContent = descripcion;
        contenedor.appendChild(canvas);
        return canvas;
    }

    function comunes() {
        Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif';
        Chart.defaults.color = '#163B50';
        Chart.defaults.maintainAspectRatio = false;
        Chart.defaults.responsive = true;
    }

    function pastel(id, etiquetas, valores, opciones) {
        opciones = opciones || {};
        var total = valores.reduce(function (a, b) { return a + (+b || 0); }, 0);
        var resumen = etiquetas.map(function (e, i) { return e + ': ' + formatear(valores[i], opciones.formato); }).join('; ');
        var canvas = lienzo(id, (opciones.titulo || 'Gráfico de pastel') + '. ' + resumen);
        if (!canvas) { return null; }
        comunes();
        instancias[id] = new Chart(canvas, {
            type: 'doughnut',
            data: {labels: etiquetas, datasets: [{data: valores, backgroundColor: etiquetas.map(function (_, i) { return PALETA[i % PALETA.length]; }), borderColor: '#fff', borderWidth: 2}]},
            options: {
                cutout: '55%',
                plugins: {
                    legend: {position: window.innerWidth < 576 ? 'bottom' : 'right', labels: {boxWidth: 14, generateLabels: function (chart) {
                        // Nombres largos acortados en la leyenda; el texto emergente muestra el nombre completo.
                        var items = Chart.overrides.doughnut.plugins.legend.labels.generateLabels(chart);
                        items.forEach(function (item) { if (item.text.length > 30) { item.text = item.text.slice(0, 29) + '…'; } });
                        return items;
                    }}},
                    tooltip: {callbacks: {label: function (ctx) {
                        var porcentaje = total ? (ctx.parsed * 100 / total) : 0;
                        return ' ' + ctx.label + ': ' + formatear(ctx.parsed, opciones.formato) + ' (' + numero.format(porcentaje) + ' %)';
                    }}}
                }
            }
        });
        return instancias[id];
    }

    function barras(id, categorias, series, opciones) {
        opciones = opciones || {};
        var canvas = lienzo(id, (opciones.titulo || 'Gráfico de barras') + '. Series: ' + series.map(function (s) { return s.name; }).join(', '));
        if (!canvas) { return null; }
        comunes();
        instancias[id] = new Chart(canvas, {
            type: 'bar',
            data: {labels: categorias, datasets: series.map(function (s, i) {
                return {label: s.name, data: s.data, backgroundColor: PALETA[i % PALETA.length], borderRadius: 6, maxBarThickness: 38};
            })},
            options: {
                interaction: {mode: 'index', intersect: false},
                scales: {
                    x: {grid: {display: false}, ticks: {autoSkip: true, maxRotation: 45}},
                    y: {beginAtZero: true, title: {display: !!opciones.ejeY, text: opciones.ejeY || ''},
                        ticks: {callback: function (v) { return formatear(v, opciones.formato); }}}
                },
                plugins: {
                    legend: {position: 'bottom', labels: {boxWidth: 14}},
                    tooltip: {callbacks: {label: function (ctx) { return ' ' + ctx.dataset.label + ': ' + formatear(ctx.parsed.y, opciones.formato); }}}
                }
            }
        });
        return instancias[id];
    }

    window.fpaGrafico = {pastel: pastel, barras: barras, MESES: ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']};
})(window);
