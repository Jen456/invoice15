var fvSale, fvClient;
var select_client, select_payment_type, select_receipt, select_medio_cobro;
var input_birthdate, input_search_product, input_end_credit, input_time_limit, input_date_joined;
var tblSearchProducts, tblProducts;

var sale = {
    detail: {
        subtotal_0: 0.00,
        subtotal_12: 0.00,
        subtotal: 0.00,
        iva: 0.00,
        total_iva: 0.00,
        total_dscto: 0.00,
        total: 0.00,
        products: [],
        additional_info: [],
    },
    // Precios CON IVA incluido (contrato común «precios con IVA»): lo que se escribe en «P. unitario» es el precio final y
    // la base y el IVA se derivan línea por línea, en centavos enteros (static/js/fp-importes.js), con el mismo algoritmo
    // que el servidor. El servidor recalcula y manda; aquí se ve lo mismo que se emitirá.
    tarifaDe: function (linea) {
        // IVA % de la línea: el de la factura en borrador o el del catálogo; sin dato, el general si el producto cobra IVA.
        if (linea.tarifa !== undefined && linea.tarifa !== null && linea.tarifa !== '') return parseFloat(linea.tarifa);
        return linea.with_tax ? parseFloat(this.detail.iva) : 0;
    },
    precioConIva: function (linea) {
        // «1000.00» que manda el servidor (precio_con_iva). Si una respuesta anterior al cambio no lo trae, se deriva del
        // precio sin IVA con la conversión del catálogo (pvp × (1 + tarifa), mitad hacia arriba a centavos).
        var valor = linea.precio_con_iva, c;
        if (valor !== undefined && valor !== null && valor !== '') {
            c = fpImportes.centavos(typeof valor === 'number' ? valor : String(valor));
        } else {
            c = fpImportes.desdeSinIva(linea.price_current, this.tarifaDe(linea));
        }
        return c === null ? null : fpImportes.dinero(c);
    },
    prepararLinea: function (linea) {
        // Lo que la tabla edita: precio con IVA (texto con 2 decimales), descripción (por defecto el nombre del producto),
        // cantidad y descuento enteros. Un precio que no se puede leer queda vacío (nunca 0,00 en silencio): la línea se
        // marca y no se puede emitir hasta corregirlo.
        var precio = this.precioConIva(linea);
        linea.precio_con_iva = precio === null ? '' : precio;
        if (typeof linea.descripcion !== 'string' || !linea.descripcion.trim()) linea.descripcion = String(linea.name || '');
        linea.descripcion = fpLineas.descripcion.limpiar(linea.descripcion).slice(0, fpLineas.descripcion.MAX);
        linea.cant = parseInt(linea.cant, 10) || 1;
        linea.dscto = parseInt(linea.dscto, 10) || 0;
        return linea;
    },
    calculateInvoice: function () {
        var calculos = [];
        this.detail.products.forEach(function (value) {
            var r = fpImportes.lineaSegura({precio_con_iva: value.precio_con_iva, cant: value.cant, dscto: value.dscto,
                tarifa: sale.tarifaDe(value)});
            value.importes_validos = r !== null;
            value.excede_maximo = r !== null && r.total > sale.MAXIMO_CENTAVOS;
            if (r) {
                r.grupo = value.nombre_tarifa ? 'IVA ' + value.nombre_tarifa : 'IVA ' + r.tarifa + ' %';
                calculos.push(r);
            }
            // Solo texto y números para mostrar: el JSON que se envía se arma aparte (lineasParaEnviar).
            value.total_con_iva = r ? fpImportes.dinero(r.total) : '';
            value.descuento_con_iva = r ? fpImportes.dinero(r.descuento) : '0.00';
            value.total = r ? fpImportes.numero(r.total) : 0;
            value.total_dscto = r ? fpImportes.numero(r.descuento) : 0;
        });
        var t = fpImportes.totales(calculos);
        this.detail.excede_maximo = t.total > sale.MAXIMO_CENTAVOS;
        this.detail.subtotal_0 = fpImportes.numero(t.base_0);
        this.detail.subtotal_12 = fpImportes.numero(t.base_gravada);
        this.detail.subtotal = fpImportes.numero(t.base);
        this.detail.total_dscto = fpImportes.numero(t.descuento);
        this.detail.total_iva = fpImportes.numero(t.iva);
        this.detail.total = fpImportes.numero(t.total);

        $('input[name="subtotal_0"]').val(fpImportes.dinero(t.base_0));
        $('input[name="subtotal_12"]').val(fpImportes.dinero(t.base_gravada));
        $('input[name="iva"]').val(parseFloat(this.detail.iva).toFixed(2));
        $('input[name="total_iva"]').val(fpImportes.dinero(t.iva));
        $('input[name="total_dscto"]').val(fpImportes.dinero(t.descuento));
        $('input[name="total"]').val(fpImportes.dinero(t.total));
        this.pintarDesglose(t.grupos);
    },
    pintarDesglose: function (grupos) {
        // Si «Subtotal gravado» o «Subtotal 0 %» juntan más de una tarifa (15 % y 5 %; 0 %, exento y no objeto), base sin
        // IVA e IVA de cada una, como el pie del RIDE.
        var tabla = $('.fp-sale-summary tbody');
        tabla.find('tr.fp-sale-desglose').remove();
        var gravadas = grupos.filter(function (g) { return g.tarifa > 0; }).length;
        if (gravadas < 2 && grupos.length - gravadas < 2) return;
        var ancla = tabla.find('tr.fp-sale-subtotales').last();
        grupos.slice().reverse().forEach(function (g) {
            var detalle = g.tarifa > 0 ? ' · IVA ' + fpImportes.dinero(g.iva) : '';
            ancla.after($('<tr class="fp-sale-desglose">').append(
                $('<th scope="row">').text('Base ' + g.nombre.replace(/^IVA /, '') + ' (sin IVA)'),
                $('<td>').text(fpImportes.dinero(g.base) + detalle)));
        });
    },
    listProducts: function () {
        this.detail.products.forEach(function (linea) { sale.prepararLinea(linea); });
        this.calculateInvoice();
        var etiqueta = function (texto, clase) {
            return {className: clase, createdCell: function (td) { td.setAttribute('data-label', texto); }};
        };
        tblProducts = $('#tblProducts').DataTable({
            autoWidth: false,
            destroy: true,
            data: this.detail.products,
            ordering: false,
            lengthChange: false,
            searching: false,
            paginate: false,
            columns: [
                $.extend({data: 'id'}, etiqueta('Orden', 'fp-col-orden')),
                $.extend({data: 'code'}, etiqueta('Código', 'fp-col-codigo')),
                $.extend({data: 'descripcion'}, etiqueta('Descripción', 'fp-col-desc')),
                $.extend({data: 'cant'}, etiqueta('Cantidad', 'fp-col-cant')),
                $.extend({data: 'precio_con_iva'}, etiqueta('P. unitario con IVA', 'fp-col-precio')),
                $.extend({data: 'dscto'}, etiqueta('Descuento', 'fp-col-dscto')),
                $.extend({data: 'total_con_iva'}, etiqueta('Total con IVA', 'fp-col-total')),
                $.extend({data: 'id'}, etiqueta('Quitar', 'fp-col-quitar')),
            ],
            columnDefs: [
                {targets: [0], render: function (data, type, row, meta) { return sale.celdaOrden(row, meta.row); }},
                {targets: [1], render: $.fn.dataTable.render.text()},
                {targets: [2], render: function (data, type, row, meta) { return sale.celdaDescripcion(row, meta.row); }},
                {
                    targets: [3],
                    render: function (data, type, row, meta) {
                        return '<div class="fp-num"><input type="number" inputmode="numeric" class="form-control fp-num-campo" ' +
                            'name="cant" min="1" max="' + sale.maximoDe(row) + '" step="1" autocomplete="off" value="' + row.cant +
                            '" aria-label="Cantidad de la línea ' + (meta.row + 1) + '"></div>';
                    }
                },
                {
                    targets: [4],
                    render: function (data, type, row, meta) {
                        // Precio CON IVA de esta factura: no cambia el catálogo; el servidor lo valida y recalcula.
                        if (sale.precioEditable()) {
                            return '<div class="fp-num fp-dinero"><span class="fp-num-prefijo" aria-hidden="true">$</span>' +
                                '<input type="text" inputmode="decimal" class="form-control fp-num-campo fp-precio-linea" ' +
                                'autocomplete="off" name="precio_linea" maxlength="10" value="' + sale.escapar(row.precio_con_iva) +
                                '" aria-label="Precio unitario con IVA de la línea ' + (meta.row + 1) + '"></div>';
                        }
                        return '<span class="fp-importe">' + (row.precio_con_iva ? '$' + sale.escapar(row.precio_con_iva) : '—') + '</span>';
                    }
                },
                {
                    targets: [5],
                    render: function (data, type, row, meta) {
                        var id = 'fp-dscto-valor-' + meta.row;
                        return '<div class="fp-dscto"><div class="fp-num fp-num-pct"><input type="number" inputmode="numeric" ' +
                            'class="form-control fp-num-campo" name="dscto_unitary" min="0" max="100" step="1" autocomplete="off" ' +
                            'value="' + row.dscto + '" aria-label="Descuento en porcentaje de la línea ' + (meta.row + 1) +
                            '" aria-describedby="' + id + '"><span class="fp-num-sufijo" aria-hidden="true">%</span></div>' +
                            '<small class="fp-dscto-valor" id="' + id + '">' + sale.textoDescuento(row) + '</small></div>';
                    }
                },
                {
                    targets: [6],
                    render: function (data, type, row) {
                        return '<span class="fp-importe fp-total-linea">' + (row.importes_validos ? '$' + row.total_con_iva : '—') + '</span>';
                    }
                },
                {
                    targets: [7],
                    render: function (data, type, row, meta) {
                        return '<button type="button" rel="remove" class="btn btn-outline-danger fp-quitar" aria-label="Quitar la línea ' +
                            (meta.row + 1) + ': ' + sale.escapar(row.descripcion || row.name) + '"><i class="fas fa-trash-alt" aria-hidden="true"></i></button>';
                    }
                },
            ],
            rowCallback: function (row, data, index) {
                $(row).toggleClass('fp-linea-invalida', !data.importes_validos);
            },
            drawCallback: function () {
                fpLineas.descripcion.ajustarTodas(document.getElementById('tblProducts'));
            },
            initComplete: function (settings, json) {
                if (!$(this).parent().hasClass('dataTables_scroll')) { $(this).wrap('<div class="dataTables_scroll"></div>'); }
            }
        });
    },
    maximoDe: function (row) {
        var stock = row.inventoried ? Number(row.stock) : 999999;
        // Al reutilizar una factura se conserva la cantidad original para revisarla, sin recortarla en silencio.
        if (row.fp_base) stock = Math.max(stock, row.cant);
        return Math.max(1, Math.min(999999, stock));
    },
    textoDescuento: function (row) {
        return Number(row.dscto) > 0 ? '−$' + row.descuento_con_iva + ' con IVA' : 'Sin descuento';
    },
    celdaOrden: function (row, indice) {
        var n = indice + 1, total = this.detail.products.length;
        return '<div class="fp-orden">' +
            '<button type="button" class="fp-asa" aria-label="Mover la línea ' + n + '" aria-describedby="fp-orden-ayuda">' +
            '<span aria-hidden="true">⋮⋮</span></button>' +
            '<span class="fp-orden-num" aria-hidden="true">' + n + '</span><span class="fp-orden-flechas">' +
            '<button type="button" class="fp-orden-btn" data-mover="-1" aria-label="Subir la línea ' + n + '"' + (n === 1 ? ' disabled' : '') +
            '><i class="fas fa-chevron-up" aria-hidden="true"></i></button>' +
            '<button type="button" class="fp-orden-btn" data-mover="1" aria-label="Bajar la línea ' + n + '"' + (n === total ? ' disabled' : '') +
            '><i class="fas fa-chevron-down" aria-hidden="true"></i></button></span></div>';
    },
    celdaDescripcion: function (row, indice) {
        var esc = sale.escapar, id = 'fp-desc-' + indice;
        var tarifa = row.codigo_porcentaje !== undefined ? sale.celdaTarifa(row) :
            (row.nombre_tarifa ? '<small class="fp-desc-tarifa">IVA ' + esc(row.nombre_tarifa) + '</small>' : '');
        var otro = row.descripcion !== row.name ? '' : ' hidden';
        var stock = row.inventoried ? '<span class="badge badge-pill ' + (row.stock > 0 ? 'badge-success' : 'badge-danger') +
            '">Stock ' + esc(row.stock) + '</span>' : '<span class="badge badge-pill badge-secondary">No inventariado</span>';
        return '<textarea class="form-control fp-desc-linea" name="descripcion_linea" id="' + id + '" rows="1" maxlength="' +
            fpLineas.descripcion.MAX + '" autocomplete="off" spellcheck="true" data-contador="' + id + '-aviso" aria-label="Descripción de la línea ' +
            (indice + 1) + '" aria-describedby="' + id + '-aviso">' + esc(row.descripcion) + '</textarea>' +
            '<div class="fp-desc-pie">' + stock + tarifa + '<small class="fp-desc-producto"' + otro + '>Producto: ' + esc(row.name) + '</small>' +
            '<small class="fp-desc-aviso" id="' + id + '-aviso" aria-live="polite"></small></div>' +
            '<p class="fp-linea-aviso" role="status" hidden></p>';
    },
    filaDe: function (elemento) {
        var tr = $(elemento).closest('tr');
        return {tr: tr, indice: tblProducts.row(tr).index()};
    },
    avisarLinea: function (tr, texto) {
        var aviso = tr.find('.fp-linea-aviso');
        aviso.text(texto || '').prop('hidden', !texto);
    },
    refrescarFila: function (indice) {
        // Sin volver a dibujar la tabla (no se pierde el foco): total y descuento de la línea, y el pie.
        var linea = this.detail.products[indice], tr = $(tblProducts.row(indice).node());
        tr.find('.fp-total-linea').text(linea.importes_validos ? '$' + linea.total_con_iva : '—');
        tr.find('.fp-dscto-valor').text(this.textoDescuento(linea));
        tr.toggleClass('fp-linea-invalida', !linea.importes_validos);
    },
    moverLinea: function (desde, hasta) {
        var lineas = this.detail.products;
        if (desde < 0 || desde >= lineas.length || hasta < 0 || hasta >= lineas.length) return;
        lineas.splice(hasta, 0, lineas.splice(desde, 1)[0]);
        this.listProducts();
    },
    lineasParaEnviar: function () {
        // Contrato §3, en el orden en que se ven las filas. El precio sin IVA (price_current) ya no se envía.
        return this.detail.products.map(function (l) {
            var fila = {id: l.id, cant: parseInt(l.cant, 10), precio_con_iva: l.precio_con_iva, dscto: parseInt(l.dscto, 10) || 0,
                descripcion: fpLineas.descripcion.normalizar(l.descripcion)};
            if (l.codigo_porcentaje !== undefined) fila.codigo_porcentaje = l.codigo_porcentaje;   // factura en borrador
            return fila;
        });
    },
    MAXIMO_CENTAVOS: 999999999,   // USD 9.999.999,99: lo más que guardan la línea y el comprobante (9 dígitos)
    lineasValidas: function () {
        // Antes de enviar: ninguna línea con importes sin calcular ni descripción fuera de lo que admite el servidor.
        var mala = this.detail.products.findIndex(function (l) {
            return !l.importes_validos || fpLineas.descripcion.normalizar(l.descripcion).length > fpLineas.descripcion.MAX;
        });
        if (mala !== -1) {
            message_error('Revisa la línea ' + (mala + 1) + ': cantidad, precio con IVA, descuento o descripción.');
            return false;
        }
        var grande = this.detail.products.findIndex(function (l) { return l.excede_maximo; });
        if (grande !== -1 || this.detail.excede_maximo) {
            message_error((grande !== -1 ? 'La línea ' + (grande + 1) : 'El total') +
                ' supera USD 9.999.999,99, lo máximo que admite un comprobante.');
            return false;
        }
        return true;
    },
    camposDeLinea: ['search_product', 'input_search_product', 'cant', 'precio_linea', 'price_current', 'dscto_unitary',
        'tarifa_linea', 'descripcion_linea'],
    getProductsIds: function () {
        return this.detail.products.map(value => value.id);
    },
    precioEditable: function () {
        return $('.fp-sale-editor').attr('data-precio-editable') === '1';
    },
    tarifas: [],
    escapar: function (x) {   // para atributos: también comillas ($('<div>').text(x).html() no las escapa)
        return String(x === null || x === undefined ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
    tarifaEditable: function () {
        return $('.fp-sale-editor').attr('data-tarifa-editable') === '1';
    },
    celdaTarifa: function (row) {
        // IVA de la línea en la factura en borrador de una proforma: se revisa para ESTA factura; el catálogo no cambia.
        var esc = sale.escapar, catalogo = row.tarifa_catalogo !== row.codigo_porcentaje ?
            ' <small class="text-muted">(catálogo: ' + esc(row.nombre_tarifa_catalogo) + ')</small>' : '';
        if (!sale.tarifaEditable() || !sale.tarifas.length) {
            return '<small class="fp-desc-tarifa">IVA ' + esc(row.nombre_tarifa) + '</small>' + catalogo;
        }
        var opciones = sale.tarifas.map(function (t) {
            return '<option value="' + esc(t.codigo) + '"' + (t.codigo === row.codigo_porcentaje ? ' selected' : '') + '>IVA ' +
                esc(t.nombre) + '</option>';
        }).join('');
        return '<select class="form-control form-control-sm fp-tarifa-linea" name="tarifa_linea" aria-label="IVA de ' +
            esc(row.descripcion || row.name) + ' en esta factura">' + opciones + '</select>' + catalogo;
    },
    cambiarTarifa: function (indice, codigo) {
        var linea = this.detail.products[indice], tarifa = this.tarifas.find(function (t) { return t.codigo === codigo; });
        if (!linea || !tarifa) return;
        linea.codigo_porcentaje = tarifa.codigo;
        linea.tarifa_iva = tarifa.codigo;
        linea.tarifa = tarifa.tarifa;
        linea.nombre_tarifa = tarifa.nombre;
        this.listProducts();   // recalcula base, IVA y total con la tarifa de la línea (el precio con IVA no cambia)
    },
    datosBorrador: function () {
        // Lo mismo que envía «Emitir factura», para guardarlo sin emitir.
        var params = new FormData(fvSale.form);
        sale.camposDeLinea.forEach(function (value) {
            params.delete(value);
        });
        params.append('products', JSON.stringify(sale.lineasParaEnviar()));
        params.append('additional_info', JSON.stringify(sale.detail.additional_info.filter(value => !$.isEmptyObject(value.name) && !$.isEmptyObject(value.value))));
        return params;
    },
    restaurarVencimiento: function (texto) {
        // Factura en borrador: el vencimiento guardado se muestra tal cual. El calendario nace con el mínimo «ahora» (con
        // hora): descartaría la fecha de hoy y cualquier fecha pasada y dejaría el campo vacío. Se pone sin mínimo y el
        // mínimo vuelve al comienzo de hoy (useCurrent: false no toca la fecha puesta; un Date y no un moment, para que el
        // calendario conserve su idioma). Si la fecha ya pasó, el campo queda marcado hasta que se corrija.
        var fecha = moment(texto, 'YYYY-MM-DD', true);
        if (!fecha.isValid()) return;
        input_end_credit.datetimepicker('minDate', false);
        input_end_credit.datetimepicker('date', fecha);
        input_end_credit.datetimepicker('minDate', moment().startOf('day').toDate());
        fvSale.revalidateField('end_credit');
    },
    enviarBorrador: function (accion, exito) {
        if (accion === 'guardar_borrador' && !sale.lineasValidas()) return;
        var params = accion === 'guardar_borrador' ? sale.datosBorrador() : new FormData();
        params.set('action', accion);
        params.set('borrador_id', $('input[name="borrador_id"]').val());
        $.ajax({
            url: pathname, type: 'POST', data: params, dataType: 'json', processData: false, contentType: false,
            headers: {'X-CSRFToken': csrftoken},
            beforeSend: function () { loading({'text': '...'}); },
            success: function (r) {
                if (r.error) {
                    message_error(r.error);
                    return;
                }
                exito(r);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || (errorThrown + ' ' + textStatus));
            },
            complete: function () { $.LoadingOverlay('hide'); }
        });
    },
    addProduct: function (item) {
        var index = this.detail.products.findIndex(value => value.code === item.code);
        if (index === -1 && this.tarifas.length && item.codigo_porcentaje === undefined) {
            // Producto agregado a una factura en borrador: empieza con la tarifa del catálogo y se puede revisar igual.
            item.codigo_porcentaje = item.tarifa_catalogo = item.tarifa_iva;
            item.nombre_tarifa_catalogo = item.nombre_tarifa;
        }
        if (index === -1) {
            this.detail.products.push(this.prepararLinea(item));
        } else {
            var product = this.detail.products[index];
            if ((product.cant + 1 <= product.stock) || !product.inventoried) {
                product.cant += 1;
            }
        }
        this.listProducts();
    },
    searchProductBarcode: function () {
        var code = input_search_product.val();
        $.ajax({
            url: pathname,
            data: {
                'action': 'search_product_code',
                'code': code
            },
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            dataType: 'json',
            success: function (request) {
                if (!request.hasOwnProperty('error')) {
                    if (!$.isEmptyObject(request)) {
                        request.cant = 1;
                        sale.addProduct(request);
                    } else {
                        message_error('Producto no encontrado con el código ' + code);
                    }
                    return false;
                }
                message_error(request.error);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || (errorThrown + ' ' + textStatus));
            },
            complete: function () {
                input_search_product.val('').focus();
            }
        });
    },
    searchVoucherNumber: function () {
        if (this.consultaNumero) this.consultaNumero.abort();
        var version = this.versionNumero = (this.versionNumero || 0) + 1;
        var panel = $('.fp-punto-emision'), aviso = panel.find('.fp-punto-aviso');
        $('input[name="voucher_number"]').val('');
        panel.find('.fp-punto-proximo').text('Consultando…');
        this.consultaNumero = $.ajax({
            url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            data: {action: 'search_voucher_number', receipt: select_receipt.val(), punto: panel.find('[name="punto"]').val() || ''},
            success: function (r) {
                if (version !== sale.versionNumero) return;
                var mensaje = r.error || (r.pending && r.pending.mensaje);
                aviso.text(mensaje || '').prop('hidden', !mensaje);
                $('input[name="voucher_number"]').val(r.voucher_number || '');
                panel.find('.fp-punto-proximo').text(r.voucher_number_full || 'Por confirmar');
                if (r.punto) panel.find('.fp-punto-etiqueta').text(r.punto.etiqueta);
            },
            error: function (xhr, status) {
                if (status === 'abort' || version !== sale.versionNumero) return;
                panel.find('.fp-punto-proximo').text('Por confirmar');
                aviso.text((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo consultar el próximo número. Vuelve a elegir el punto para reintentar.').prop('hidden', false);
            }
        });
    },
    listAdditionalInfo: function () {
        tblAdditionalInfo = $('#tblAdditionalInfo').DataTable({
            autoWidth: false,
            destroy: true,
            data: this.detail.additional_info,
            ordering: false,
            lengthChange: false,
            searching: false,
            paginate: false,
            info: false,
            columns: [
                {data: "name"},
                {data: "name"},
                {data: "value"},
            ],
            columnDefs: [
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" placeholder="Ingrese un nombre" autocomplete="off" name="additional_info_name" value="' + sale.escapar(row.name) + '">';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" placeholder="Ingrese un valor" autocomplete="off" name="additional_info_value" value="' + sale.escapar(row.value) + '">';
                    }
                },
                {
                    targets: [0],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a rel="remove" class="btn btn-danger btn-flat btn-xs"><i class="fas fa-times"></i></a>';
                    }
                },
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    cargarProforma: function (datos) {
        // Factura de una proforma (core/proformas): comprobante 01, líneas con el precio y el descuento cotizados (sin
        // addProduct, que fusiona y suma cantidades), información adicional que se puede quitar, forma de pago y cliente
        // o prospecto. Todo se puede revisar antes de emitir; el servidor recalcula y manda.
        select_receipt.val('01').trigger('change');
        select_receipt.find('option').not('[value="01"]').prop('disabled', true);
        datos.lineas.forEach(function (linea) {
            sale.detail.products.push(linea);
        });
        sale.detail.additional_info = datos.info_adicional.slice();
        sale.listAdditionalInfo();
        if (datos.forma_pago) {
            $('select[name="payment_method"]').val(datos.forma_pago).trigger('change');
        }
        if (datos.borrador) {   // factura en borrador: tarifas de IVA, condición, medio de cobro, plazo y vencimiento
            sale.tarifas = datos.tarifas || [];
            if (datos.condicion_pago) select_payment_type.val(datos.condicion_pago).trigger('change');
            if (datos.medio_cobro) select_medio_cobro.val(datos.medio_cobro).trigger('change');
            if (datos.time_limit !== null && datos.time_limit !== undefined) input_time_limit.val(datos.time_limit);
            if (datos.end_credit) sale.restaurarVencimiento(datos.end_credit);
        }
        if (datos.cliente) {
            select_client.select2('trigger', 'select', {data: datos.cliente});
        } else if (datos.prospecto) {
            var prospecto = datos.prospecto, formulario = $('#frmClient');
            var correos = (prospecto.correo || '').split(',').map(function (c) { return c.trim(); }).filter(Boolean);
            var identificacion = (prospecto.identificacion || '').trim();
            var telefono = (prospecto.telefono || '').replace(/\D/g, '');
            formulario.find('input[name="names"]').val(prospecto.nombre);
            formulario.find('input[name="email"]').val(correos.length ? correos[0] : '');
            formulario.find('input[name="extra_emails"]').val(correos.slice(1).join(', '));
            formulario.find('input[name="dni"]').val(identificacion);
            formulario.find('input[name="mobile"]').val(telefono.length <= 10 ? telefono : '');
            formulario.find('[name="address"]').val(prospecto.direccion);
            if (/^\d{10}$/.test(identificacion)) {
                formulario.find('select[name="identification_type"]').val('05').trigger('change');
            } else if (/^\d{13}$/.test(identificacion)) {
                formulario.find('select[name="identification_type"]').val('04').trigger('change');
            }
            input_birthdate.datetimepicker('clear');   // sin fecha de nacimiento inventada
            if ($('.btnAddClient').length) {
                $('#myModalClient').modal('show');
            } else {   // sin add_client el alta no se ofrece
                message_error('La proforma es para un prospecto: elige un cliente registrado antes de emitir.');
            }
        }
    }
};

document.addEventListener('DOMContentLoaded', function (e) {
    fvClient = FormValidation.formValidation(document.getElementById('frmClient'), {
            locale: 'es_ES',
            localization: FormValidation.locales.es_ES,
            plugins: {
                trigger: new FormValidation.plugins.Trigger(),
                submitButton: new FormValidation.plugins.SubmitButton(),
                bootstrap: new FormValidation.plugins.Bootstrap(),
                icon: new FormValidation.plugins.Icon({
                    valid: 'fa fa-check',
                    invalid: 'fa fa-times',
                    validating: 'fa fa-refresh',
                }),
            },
            fields: {
                names: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 2,
                        },
                    }
                },
                dni: {
                    validators: {
                        notEmpty: {},
                        callback: {
                            message: 'La identificación no es válida para el tipo elegido',
                            callback: function (input) {
                                return identificacion_valida(fvClient.form.querySelector('[name="identification_type"]').value, input.value);
                            },
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fvClient.form.querySelector('[name="dni"]').value,
                                    pattern: 'dni',
                                    empresa: (fvClient.form.querySelector('[name="empresa"]') || {}).value || '',
                                    action: 'validate_client'
                                };
                            },
                            // Sin mensaje fijo: el servidor dice si el cliente está repetido o si la empresa cambió en otra pestaña.
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                // Opcionales y repetibles: hay compradores sin teléfono ni correo, y empresas de un mismo grupo comparten ambos.
                mobile: {
                    validators: {
                        stringLength: {
                            min: 7
                        },
                        digits: {}
                    }
                },
                email: {
                    validators: {
                        stringLength: {
                            min: 5
                        },
                        regexp: {
                            regexp: /^([a-z0-9_\.-]+)@([\da-z\.-]+)\.([a-z\.]{2,6})$/i,
                            message: 'El formato email no es correcto'
                        }
                    }
                },
                address: {
                    validators: {
                        stringLength: {
                            min: 4,
                        }
                    }
                },
                image: {
                    validators: {
                        file: {
                            extension: 'jpeg,jpg,png',
                            type: 'image/jpeg,image/png',
                            maxFiles: 1,
                            message: 'Introduce una imagen válida'
                        }
                    }
                },
                birthdate: {
                    validators: {
                        date: {   // opcional: vacío es válido (ya no se inventa la fecha de hoy)
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    },
                },
                identification_type: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un item'
                        }
                    }
                },
            },
        }
    )
        .on('core.element.validated', function (e) {
            if (e.valid) {
                const groupEle = FormValidation.utils.closest(e.element, '.form-group');
                if (groupEle) {
                    FormValidation.utils.classSet(groupEle, {
                        'has-success': false,
                    });
                }
                FormValidation.utils.classSet(e.element, {
                    'is-valid': false,
                });
            }
            const iconPlugin = fvClient.getPlugin('icon');
            const iconElement = iconPlugin && iconPlugin.icons.has(e.element) ? iconPlugin.icons.get(e.element) : null;
            iconElement && (iconElement.style.display = 'none');
        })
        .on('core.validator.validated', function (e) {
            if (!e.result.valid) {
                const messages = [].slice.call(fvClient.form.querySelectorAll('[data-field="' + e.field + '"][data-validator]'));
                messages.forEach((messageEle) => {
                    const validator = messageEle.getAttribute('data-validator');
                    messageEle.style.display = validator === e.validator ? 'block' : 'none';
                });
            }
        })
        .on('core.form.valid', function () {
            fpClienteRapido.guardar();
        });
});

document.addEventListener('DOMContentLoaded', function (e) {
    fvSale = FormValidation.formValidation(document.getElementById('frmForm'), {
            locale: 'es_ES',
            localization: FormValidation.locales.es_ES,
            plugins: {
                trigger: new FormValidation.plugins.Trigger(),
                submitButton: new FormValidation.plugins.SubmitButton(),
                bootstrap: new FormValidation.plugins.Bootstrap(),
                // excluded: new FormValidation.plugins.Excluded(),
                icon: new FormValidation.plugins.Icon({
                    valid: 'fa fa-check',
                    invalid: 'fa fa-times',
                    validating: 'fa fa-refresh',
                }),
            },
            fields: {
                client: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un cliente'
                        },
                    }
                },
                date_joined: {
                    validators: {
                        notEmpty: {
                            enabled: false,
                            message: 'La fecha es obligatoria'
                        },
                        date: {
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    }
                },
                voucher_number: {
                    validators: {
                        notEmpty: {}
                    }
                },
                end_credit: {
                    validators: {
                        // Obligatoria solo a crédito y desde hoy (lo mismo que exige el servidor). Un validador con
                        // enabled: false no se reactiva en el adaptador local (enableValidator no lo revive): la condición va
                        // dentro del callback, que da su propio mensaje (sin `message`, que el adaptador antepondría).
                        callback: {
                            callback: function (input) {
                                if (select_payment_type.val() !== 'credito') return true;
                                var texto = String(input.value || '').trim();
                                if (texto === '') return {valid: false, message: 'Indica la fecha de plazo del crédito.'};
                                var fecha = moment(texto, 'YYYY-MM-DD', true);
                                if (fecha.isValid() && fecha.isBefore(moment().startOf('day'), 'day')) {
                                    return {valid: false, message: 'La fecha de plazo del crédito ya pasó: elige una fecha desde hoy.'};
                                }
                                return true;
                            }
                        },
                        date: {
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    }
                },
                payment_type: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un tipo de pago'
                        },
                    }
                },
                payment_method: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un método de pago'
                        },
                    }
                },
                time_limit: {
                    validators: {
                        notEmpty: {},
                        digits: {}
                    }
                },
            },
        }
    )
        .on('core.element.validated', function (e) {
            if (e.valid) {
                const groupEle = FormValidation.utils.closest(e.element, '.form-group');
                if (groupEle) {
                    FormValidation.utils.classSet(groupEle, {
                        'has-success': false,
                    });
                }
                FormValidation.utils.classSet(e.element, {
                    'is-valid': false,
                });
            }
            const iconPlugin = fvSale.getPlugin('icon');
            const iconElement = iconPlugin && iconPlugin.icons.has(e.element) ? iconPlugin.icons.get(e.element) : null;
            iconElement && (iconElement.style.display = 'none');
        })
        .on('core.validator.validated', function (e) {
            if (!e.result.valid) {
                const messages = [].slice.call(fvSale.form.querySelectorAll('[data-field="' + e.field + '"][data-validator]'));
                messages.forEach((messageEle) => {
                    const validator = messageEle.getAttribute('data-validator');
                    messageEle.style.display = validator === e.validator ? 'block' : 'none';
                });
            }
        })
        .on('core.form.valid', function () {
            if (sale.validarBase && !sale.validarBase()) return false;
            if (sale.detail.products.length === 0) {
                message_error('Debe tener al menos un item en el detalle de la venta');
                return false;
            }
            if (!sale.lineasValidas()) return false;
            var customer = select_client.select2('data')[0];
            if (select_receipt.val() === '01') {
                if (customer.identification_type.id === '07' && sale.detail.total > 50.00) {
                    message_error('Una factura a consumidor final no puede superar USD 50,00: registra los datos del comprador.');
                    return false;
                }
                if (customer.identification_type.id === '07' && select_payment_type.val() === 'credito') {
                    message_error('No se puede facturar a crédito con un cliente consumidor final');
                    return false;
                }
            }
            var list_url = $(fvSale.form).attr('data-url');
            var params = new FormData(fvSale.form);
            sale.camposDeLinea.forEach(function (value) {
                params.delete(value);
            });
            params.append('products', JSON.stringify(sale.lineasParaEnviar()));
            params.append('additional_info', JSON.stringify(sale.detail.additional_info.filter(value => !$.isEmptyObject(value.name) && !$.isEmptyObject(value.value))));
            var args = {
                'params': params,
                'success': function (request) {
                    if (request.en_proceso || !request.print_url) {
                        // El SRI aún autoriza la factura: quedó guardada; se consulta desde el listado.
                        alert_sweetalert({'message': request.mensaje || 'Venta guardada.', 'timer': 9000, 'callback': function () {
                            location.href = list_url;
                        }});
                        return;
                    }
                    dialog_action({
                        'content': (request.mensaje ? request.mensaje + '<br>' : '') + '¿Desea Imprimir el Comprobante?',
                        'success': function () {
                            console.log(request);
                            window.open(request.print_url, '_blank');
                            location.href = list_url;
                        },
                        'cancel': function () {
                            location.href = list_url;
                        }
                    });
                }
            };
            submit_with_formdata(args);
        });
});

$(function () {
    input_search_product = $('input[name="search_product"]');
    select_client = $('select[name="client"]');
    select_receipt = $('select[name="receipt"]');
    input_birthdate = $('input[name="birthdate"]');
    input_date_joined = $('input[name="date_joined"]');
    input_end_credit = $('input[name="end_credit"]');
    select_payment_type = $('select[name="payment_type"]');
    select_medio_cobro = $('select[name="medio_cobro"]');
    input_time_limit = $('input[name="time_limit"]');

    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es",
    });

    // Product

    input_search_product.autocomplete({
        source: function (request, response) {
            $.ajax({
                url: pathname,
                data: {
                    'action': 'search_product',
                    'term': request.term,
                    'ids': JSON.stringify(sale.getProductsIds()),
                },
                dataType: "json",
                type: "POST",
                headers: {
                    'X-CSRFToken': csrftoken
                },
                beforeSend: function () {

                },
                success: function (data) {
                    response(data);
                }
            });
        },
        min_length: 3,
        delay: 300,
        select: function (event, ui) {
            event.preventDefault();
            $(this).blur();
            if (ui.item.stock === 0 && ui.item.inventoried) {
                message_error('El stock de este producto esta en 0');
                return false;
            }
            ui.item.cant = 1;
            sale.addProduct(ui.item);
            $(this).val('').focus();
        }
    });
    // Cada resultado muestra el precio CON IVA del catálogo, el mismo que llega a la línea.
    var autocompletar = input_search_product.autocomplete('instance');
    if (autocompletar) {
        autocompletar._renderItem = function (ul, item) {
            var precio = sale.precioConIva(item);
            return $('<li>').append($('<div class="fp-ac-item">').append(
                $('<span class="fp-ac-nombre">').text(item.label || item.value || item.name || ''),
                $('<span class="fp-ac-precio">').text(precio === null ? '' : '$' + precio + ' con IVA'))).appendTo(ul);
        };
    }

    $('.btnClearProducts').on('click', function () {
        input_search_product.val('').focus();
    });

    // Líneas: cantidad, precio con IVA y descuento se recalculan al escribir (sin redibujar: no se pierde el foco); al
    // salir de la casilla se corrige lo que no vale y se avisa en la misma fila. La lista sale.detail.products es la
    // fuente de verdad: el orden de las filas es el orden que se envía.
    var tablaLineas = document.getElementById('tblProducts');
    function recalcular(indice) {
        sale.calculateInvoice();
        sale.refrescarFila(indice);
    }
    $('#tblProducts tbody')
        .off()
        .on('keypress', 'input[name="cant"]', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        })
        .on('input', 'input[name="cant"]', function () {
            var f = sale.filaDe(this), linea = sale.detail.products[f.indice];
            var n = fpImportes.entero(this.value, 1, sale.maximoDe(linea));
            if (n === null) return;
            linea.cant = n;
            sale.avisarLinea(f.tr, '');
            recalcular(f.indice);
        })
        .on('change', 'input[name="cant"]', function () {
            var f = sale.filaDe(this), linea = sale.detail.products[f.indice], maximo = sale.maximoDe(linea);
            var n = /^\s*\d+\s*$/.test(this.value) ? parseInt(this.value, 10) : NaN, aviso = '';
            if (isNaN(n)) {
                n = linea.cant;
                aviso = 'La cantidad es un número entero de 1 a ' + maximo + '.';
            } else if (n < 1) {
                n = 1;
                aviso = 'La cantidad mínima es 1.';
            } else if (n > maximo) {
                n = maximo;
                aviso = linea.inventoried ? 'Hay ' + linea.stock + ' en stock: la cantidad quedó en ' + maximo + '.' :
                    'La cantidad máxima es ' + maximo + '.';
            }
            linea.cant = n;
            this.value = String(n);
            sale.avisarLinea(f.tr, aviso);
            recalcular(f.indice);
        })
        .on('keypress', 'input[name="precio_linea"]', function (e) {
            return (e.which || e.keyCode) === 44 || validate_text_box({'event': e, 'type': 'decimals'});   // coma o punto
        })
        .on('input', 'input[name="precio_linea"]', function () {
            var f = sale.filaDe(this), c = fpImportes.centavos(String(this.value));
            if (c === null) return;
            sale.detail.products[f.indice].precio_con_iva = fpImportes.dinero(c);
            sale.avisarLinea(f.tr, '');
            recalcular(f.indice);
        })
        .on('change', 'input[name="precio_linea"]', function () {
            var f = sale.filaDe(this), linea = sale.detail.products[f.indice], c = fpImportes.centavos(String(this.value));
            if (c === null) {
                sale.avisarLinea(f.tr, 'El precio con IVA va de 0 a 999999,99, con hasta 2 decimales.');
            } else {
                linea.precio_con_iva = fpImportes.dinero(c);
                sale.avisarLinea(f.tr, '');
            }
            this.value = linea.precio_con_iva;
            recalcular(f.indice);
        })
        .on('keypress', 'input[name="dscto_unitary"]', function (e) {
            var tecla = e.which || e.keyCode;
            if (tecla === 44 || tecla === 46) {   // sin borrar el separador en silencio (2.5 no puede volverse 25)
                sale.avisarLinea($(this).closest('tr'), 'El descuento es un porcentaje entero de 0 a 100, sin decimales.');
                return false;
            }
            return validate_text_box({'event': e, 'type': 'numbers'});
        })
        .on('input', 'input[name="dscto_unitary"]', function () {
            var f = sale.filaDe(this), n = fpImportes.entero(this.value, 0, 100);
            if (n === null) return;
            sale.detail.products[f.indice].dscto = n;
            sale.avisarLinea(f.tr, '');
            recalcular(f.indice);
        })
        .on('change', 'input[name="dscto_unitary"]', function () {
            var f = sale.filaDe(this), linea = sale.detail.products[f.indice], texto = String(this.value).trim(), aviso = '';
            var n = texto === '' ? 0 : (/^\d+$/.test(texto) ? parseInt(texto, 10) : NaN);
            if (isNaN(n)) {
                n = linea.dscto;
                aviso = 'El descuento es un porcentaje entero de 0 a 100, sin decimales.';
            } else if (n > 100) {
                n = 100;
                aviso = 'El descuento máximo es 100 %.';
            }
            linea.dscto = n;
            this.value = String(n);
            sale.avisarLinea(f.tr, aviso);
            recalcular(f.indice);
        })
        .on('change', 'select[name="tarifa_linea"]', function () {
            sale.cambiarTarifa(sale.filaDe(this).indice, $(this).val());
        })
        .on('click', '[rel="remove"]', function () {
            var indice = sale.filaDe(this).indice;
            sale.detail.products.splice(indice, 1);
            sale.listProducts();
            var filas = fpLineas.filas(tablaLineas), siguiente = filas[Math.min(indice, filas.length - 1)];
            if (siguiente) { $(siguiente).find('[rel="remove"]').trigger('focus'); } else { input_search_product.trigger('focus'); }
        });

    // Descripción de cada línea (por defecto el nombre del producto): va en `descripcion`; no cambia el catálogo.
    fpLineas.descripcion.activar(tablaLineas.tBodies[0], function (area, texto) {
        var f = sale.filaDe(area), linea = sale.detail.products[f.indice];
        linea.descripcion = texto;
        f.tr.find('.fp-desc-producto').prop('hidden', fpLineas.descripcion.normalizar(texto) === String(linea.name || ''));
    });
    // Arrastrar el asa ⋮⋮ (ratón o dedo), flechas sobre el asa o «Subir»/«Bajar»: se reordena la lista y se redibuja.
    fpLineas.ordenar(tablaLineas, {
        mover: function (desde, hasta) { sale.moverLinea(desde, hasta); },
        redibujar: function () { sale.listProducts(); },
        nombre: function (i) { return sale.detail.products[i] ? sale.detail.products[i].descripcion : ''; },
        anuncio: document.getElementById('fp-orden-anuncio')
    });
    fpLineas.sinRueda(tablaLineas);

    // Factura en borrador de una proforma: guardar sin emitir y descartar (la proforma queda como estaba).
    $('.fp-guardar-borrador').on('click', function () {
        sale.enviarBorrador('guardar_borrador', function (r) {
            alert_sweetalert({'message': r.mensaje, 'timer': 4000, 'callback': function () {}});
        });
    });
    $('.fp-descartar-borrador').on('click', function () {
        dialog_action({
            'content': 'Se borrará la factura en borrador (no se envió nada al SRI). La proforma queda como está. ¿Continuar?',
            'success': function () {
                sale.enviarBorrador('descartar_borrador', function (r) { location.href = r.url; });
            },
            'cancel': function () {}
        });
    });

    $('.btnSearchProducts').on('click', function () {
        tblSearchProducts = $('#tblSearchProducts').DataTable({
            autoWidth: false,
            destroy: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search_product',
                    'term': input_search_product.val(),
                    'ids': JSON.stringify(sale.getProductsIds()),
                },
                dataSrc: ""
            },
            columns: [
                {data: "code"},
                {data: "short_name"},
                {data: "precio_con_iva", defaultContent: ''},
                {data: "stock"},
                {data: "id"},
            ],
            columnDefs: [
                {targets: [0, 1], render: $.fn.dataTable.render.text()},
                {
                    targets: [-3],
                    class: 'text-center fp-catalogo-precio',
                    render: function (data, type, row) {
                        // Precio CON IVA del catálogo (o el de la promoción, con IVA), el mismo que llega a la línea.
                        var precio = sale.precioConIva(row);
                        return (precio === null ? '—' : '$' + precio) +
                            (Number(row.price_promotion) > 0 ? '<br><small class="text-muted">En promoción</small>' : '');
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (row.inventoried) {
                            if (row.stock > 0) {
                                return '<span class="badge badge-success badge-pill">' + row.stock + '</span>';
                            }
                            return '<span class="badge badge-danger badge-pill">' + row.stock + '</span>';
                        }
                        return '<span class="badge badge-secondary badge-pill">Sin stock</span>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<button type="button" rel="add" class="btn btn-success btn-flat btn-xs" aria-label="Agregar ' +
                            sale.escapar(row.short_name || row.name) + '"><i class="fas fa-plus" aria-hidden="true"></i></button>';
                    }
                }
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
        $('#myModalSearchProducts').modal('show');
    });

    $('#tblSearchProducts tbody')
        .off()
        .on('click', '[rel="add"]', function () {
            var row = tblSearchProducts.row($(this).parents('tr')).data();
            row.cant = 1;
            sale.addProduct(row);
            tblSearchProducts.row($(this).parents('tr')).remove().draw();
        });

    $('.btnRemoveAllProducts').on('click', function () {
        if (sale.detail.products.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                sale.detail.products = [];
                sale.listProducts();
            },
            'cancel': function () {

            }
        });
    });

    // Client

    select_client.select2({
        theme: "bootstrap4",
        language: 'es',
        allowClear: true,
        ajax: {
            delay: 250,
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            url: pathname,
            data: function (params) {
                return {
                    term: params.term,
                    action: 'search_client'
                };
            },
            processResults: function (data) {
                return {
                    results: data
                };
            },
        },
        placeholder: 'Busca por nombre o identificación',
        minimumInputLength: 1,
    })
        .on('select2:select', function (e) {
            fvSale.revalidateField('client');
        })
        .on('select2:clear', function (e) {
            fvSale.revalidateField('client');
        });

    $('.btnAddClient').on('click', function () {
        $('#myModalClient').modal('show');
    });

    $('#frmClient input[name="dni"]').on('keypress', function (e) {
        return es_identificacion_extranjera($('#frmClient select[name="identification_type"]').val()) || validate_text_box({'event': e, 'type': 'numbers'});
    });

    $('#frmClient select[name="identification_type"]').on('change', function () {
        if ($('#frmClient input[name="dni"]').val()) {
            fvClient.revalidateField('dni');
        }
    });

    $('input[name="mobile"]').on('keypress', function (e) {
        return validate_text_box({'event': e, 'type': 'numbers'});
    });

    input_birthdate.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
    });

    input_birthdate.on('change.datetimepicker', function (e) {
        fvClient.revalidateField('birthdate');
    });

    // Sale

    select_receipt.on('change', function () {
        $('.content-electronic-billing').find('input,select').prop('disabled', $(this).val() !== '01');
        sale.searchVoucherNumber();
    });

    // Cambio explícito del punto de emisión dentro del formulario: se vuelve a pedir el próximo número de ese punto.
    $('select[name="punto"]').on('change', function () {
        sale.searchVoucherNumber();
    });

    // Condición de pago (contado / crédito) y medio de cobro (core/cobros). Sin «Efectivo recibido» ni «Cambio»: el
    // servidor ya no los pide. Con un medio distinto del efectivo el servidor exige comprobante o nota. A crédito no hay
    // cobro al emitir y se pide la fecha de plazo.
    function aplicarCondicionYMedio() {
        var contado = select_payment_type.val() === 'efectivo';
        var efectivo = contado && select_medio_cobro.val() === 'efectivo';
        $('.fp-sale-vence').prop('hidden', contado);
        $('.fp-cobro').toggle(contado).find('input,select,textarea').prop('disabled', !contado);
        $('.fp-cobro-efectivo-aviso').toggle(efectivo);
        if (contado) { fvSale.disableValidator('end_credit'); } else { fvSale.enableValidator('end_credit'); }
    }

    select_payment_type.on('change', aplicarCondicionYMedio);
    select_medio_cobro.on('change', aplicarCondicionYMedio);

    input_date_joined.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
    });

    input_date_joined.on('change.datetimepicker', function (e) {
        fvSale.revalidateField('date_joined');
        // El servidor emite con la fecha de hoy: un plazo copiado de una fecha pasada lo rechazaría.
        var hoy = moment().startOf('day');
        var minimo = e.date && e.date.isAfter(hoy, 'day') ? e.date : hoy;
        input_end_credit.datetimepicker('minDate', minimo.toDate());   // un Date: el calendario conserva su idioma
        if ($('input[name="borrador_id"]').length && String(input_end_credit.val() || '').trim() !== '') {
            // Factura en borrador: cambiar «Fecha» no sustituye en silencio el vencimiento guardado o ya elegido (fijar el
            // mínimo no toca la fecha puesta). Se vuelve a validar: si no vale, el campo queda marcado.
            fvSale.revalidateField('end_credit');
            return;
        }
        input_end_credit.datetimepicker('date', minimo);
    });

    input_end_credit.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
        minDate: new Date()
    });

    input_end_credit.datetimepicker('date', input_end_credit.val());

    input_end_credit.on('change.datetimepicker', function (e) {
        fvSale.revalidateField('end_credit');
    });
    // Una fecha escrita a mano que el calendario rechaza (anterior al mínimo) se repone sola: se valida lo que queda.
    input_end_credit.on('error.datetimepicker', function () {
        fvSale.revalidateField('end_credit');
    });

    // Plazo (días): casilla numérica legible, sin los botones grandes de TouchSpin; misma validación (0–1000 días).
    input_time_limit
        .on('change', function () {
            var dias = parseInt(this.value, 10);
            if (!isNaN(dias)) this.value = String(Math.max(0, Math.min(1000, dias)));   // los límites que ponía TouchSpin
            fvSale.revalidateField('time_limit');
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    // Barcode

    $(document).on('keypress', function (e) {
        if (e.which !== 13) return;
        if (e.target === input_search_product[0]) {
            e.preventDefault();
            sale.searchProductBarcode();
        } else if ($(e.target).closest('#frmForm').length && $(e.target).is('input:not([type=file]):not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit])')) {
            // Evita la emisión implícita desde un campo; conserva Enter en notas y botones.
            e.preventDefault();
        }
    });

    // Additional Info

    $('.btnAdditionalInfo').on('click', function () {
        $('#myModalAdditionalInfo').modal('show');
    });

    $('.btnCreateAdditionalInfo').on('click', function () {
        sale.detail.additional_info.push({'name': '', 'value': ''});
        sale.listAdditionalInfo();
    });

    $('.btnRemoveAdditionalInfo').on('click', function () {
        if (sale.detail.additional_info.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                sale.detail.additional_info = [];
                sale.listAdditionalInfo();
            },
            'cancel': function () {

            }
        });
    });

    $('#tblAdditionalInfo tbody')
        .off()
        .on('keyup', 'input[name="additional_info_name"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info[tr.row].name = $(this).val();
            console.log(sale.detail.additional_info);
        })
        .on('keyup', 'input[name="additional_info_value"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info[tr.row].value = $(this).val();
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info.splice(tr.row, 1);
            tblAdditionalInfo.row(tr.row).remove().draw();
        });

    sale.searchVoucherNumber();

    $('i[data-field="client"]').hide();
    $('i[data-field="input_search_product"]').hide();
    $('i[data-field="time_limit"]').hide();

    var nodoProforma = document.getElementById('fp-proforma-precarga');
    if (nodoProforma) {
        sale.cargarProforma(JSON.parse(nodoProforma.textContent));
    }
});
