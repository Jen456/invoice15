/* Modal «Detalle» de los listados de ventas y de notas de crédito (administración y portal del cliente). Solo presentación.
   Un comprobante guardado con precios CON IVA (todas sus líneas traen `con_iva_incluido`, contrato «precios con IVA» §2)
   se muestra con lo que manda el servidor: la descripción de cada línea, el precio unitario con IVA, el descuento con IVA y
   el total con IVA. Un comprobante anterior al cambio se muestra como siempre (nombre del producto y el precio, el
   descuento y el total que guardó): no se calcula un precio con IVA que no se guardó. */
(function (raiz) {
    'use strict';

    var ENCABEZADOS = {
        nuevo: ['Descripción', 'P. unitario con IVA', 'Cantidad', 'Descuento con IVA', 'Total con IVA'],
        anterior: ['Producto', 'P./Unitario', 'Cantidad', 'Descuento', 'Total']
    };

    // «1000.00» → 100000 centavos (entero); null si no es un importe con hasta 2 decimales.
    function centavos(valor) {
        var m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(String(valor === null || valor === undefined ? '' : valor).trim());
        return m ? Number(m[1]) * 100 + Number(((m[2] || '') + '00').slice(0, 2)) : null;
    }

    function dinero(c) {
        var s = String(c);
        while (s.length < 3) s = '0' + s;
        return s.slice(0, -2) + '.' + s.slice(-2);
    }

    // Como lo mostraba el modal antes del cambio: número con 2 decimales.
    function decimales(valor) {
        var n = Number(valor);
        return isFinite(n) ? n.toFixed(2) : '0.00';
    }

    // ¿Todas las líneas se guardaron con precio con IVA? Una sola línea anterior deja el comprobante entero como antes.
    function conIva(lineas) {
        return Array.isArray(lineas) && lineas.length > 0 && lineas.every(function (l) {
            return Boolean(l) && l.con_iva_incluido === true && centavos(l.precio_con_iva) !== null &&
                centavos(l.total_con_iva) !== null;
        });
    }

    // Una fila del modal: textos listos para pintar. `precioAnterior` es el campo que mostraba «P./Unitario» antes del
    // cambio ('price' en ventas, 'price_with_vat' en notas de crédito).
    function fila(linea, nuevo, precioAnterior) {
        var producto = linea.product || {}, nombre = String(producto.short_name || '');
        if (!nuevo) {
            return {descripcion: nombre, producto: '', precio: decimales(linea[precioAnterior || 'price']),
                cantidad: String(linea.cant), descuento: decimales(linea.total_dscto), total: decimales(linea.total)};
        }
        var P = centavos(linea.precio_con_iva), T = centavos(linea.total_con_iva), q = Number(linea.cant);
        // Descuento con IVA = precio con IVA × cantidad − total con IVA (enteros: sin coma flotante).
        var descuento = Number.isInteger(q) && q > 0 && P * q >= T ? P * q - T : 0;
        var descripcion = typeof linea.descripcion === 'string' && linea.descripcion.trim() ? linea.descripcion :
            String(producto.name || nombre);
        return {descripcion: descripcion, producto: descripcion === String(producto.name || '') ? '' : nombre,
            precio: dinero(P), cantidad: String(linea.cant), descuento: dinero(descuento), total: dinero(T)};
    }

    function filas(lineas, precioAnterior) {
        var nuevo = conIva(lineas);
        return {con_iva: nuevo, encabezados: ENCABEZADOS[nuevo ? 'nuevo' : 'anterior'],
            filas: (Array.isArray(lineas) ? lineas : []).map(function (l) { return fila(l, nuevo, precioAnterior); })};
    }

    // Opciones de DataTables del modal. `ajax`: la consulta de siempre (acción `search_detail_products`).
    function opciones(tabla, ajax, precioAnterior) {
        var $ = raiz.jQuery;
        var texto = function (x) { return $('<div>').text(x === null || x === undefined ? '' : String(x)).html(); };
        ajax.dataSrc = function (respuesta) {
            if (!Array.isArray(respuesta) && respuesta && respuesta.error && typeof raiz.message_error === 'function') {
                raiz.message_error(respuesta.error);
            }
            var r = filas(Array.isArray(respuesta) ? respuesta : [], precioAnterior);
            $(tabla).find('thead th').each(function (i) { $(this).text(r.encabezados[i]); });
            $(tabla).attr('data-con-iva', r.con_iva ? '1' : '0');
            return r.filas;
        };
        return {
            autoWidth: false,
            destroy: true,
            ajax: ajax,
            order: [],   // las líneas, en el orden guardado (el del comprobante); se puede ordenar por una columna al pulsarla
            columns: [{data: 'descripcion'}, {data: 'precio'}, {data: 'cantidad'}, {data: 'descuento'}, {data: 'total'}],
            columnDefs: [
                {
                    targets: [0],
                    render: function (data, type, row) {
                        return texto(data) + (row.producto ? '<br><small class="text-muted">Producto: ' + texto(row.producto) + '</small>' : '');
                    }
                },
                {targets: [1, 3, 4], class: 'text-center', render: function (data) { return '$' + texto(data); }},
                {targets: [2], class: 'text-center', render: function (data) { return texto(data); }}
            ],
            initComplete: function () {
                if (!$(this).parent().hasClass('dataTables_scroll')) { $(this).wrap('<div class="dataTables_scroll"></div>'); }
            }
        };
    }

    var api = {conIva: conIva, fila: fila, filas: filas, opciones: opciones, ENCABEZADOS: ENCABEZADOS};
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
    raiz.fpDetalleLineas = api;
}(typeof window !== 'undefined' ? window : this));
