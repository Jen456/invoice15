/* Editor de proformas (crear y editar). Las filas se arman con nodos del DOM y .text()/.val(): ningún dato del usuario se
   inserta como HTML. Precios CON IVA incluido y el mismo cálculo que la factura (static/js/fp-importes.js, contrato
   «precios con IVA»); las filas se ordenan con su asa (static/js/fp-lineas.js) y el orden de fpForm.lineas es el que se
   guarda. Los totales son una vista previa; el servidor recalcula y manda. */
var fpForm = {
    config: {},
    proforma: null,
    lineas: [],
    validaHastaTocada: false,
    esperaModal: null,
    sumarDias: function (iso, dias) {
        var partes = iso.split('-').map(Number);
        var fecha = new Date(Date.UTC(partes[0], partes[1] - 1, partes[2] + dias));
        return fecha.toISOString().slice(0, 10);
    },
    ids: function () { return fpForm.lineas.map(function (l) { return l.product; }); },
    // Precio con IVA «0.00»: el que manda el servidor o, en datos anteriores al cambio, el precio sin IVA convertido como el
    // catálogo (× (1 + tarifa), mitad hacia arriba). '' si no hay un precio válido.
    precioConIva: function (conIva, sinIva, tarifa) {
        var c = conIva !== undefined && conIva !== null && conIva !== '' ? fpImportes.centavos(String(conIva)) :
            fpImportes.desdeSinIva(sinIva === undefined || sinIva === null ? null : Number(sinIva), tarifa);
        return c === null ? '' : fpImportes.dinero(c);
    },
    desdeProducto: function (p) {
        return {
            product: p.id, codigo: p.code, nombre: p.name, descripcion: typeof p.descripcion === 'string' && p.descripcion.trim() ? p.descripcion : p.name,
            cant: 1, precio_con_iva: fpForm.precioConIva(p.precio_con_iva, p.price_current, Number(p.tarifa)), dscto: 0,
            tarifa: Number(p.tarifa), nombre_tarifa: p.nombre_tarifa, stock: p.stock, inventariado: p.inventoried
        };
    },
    agregar: function (producto) {
        if (fpForm.ids().indexOf(producto.id) !== -1) {
            message_error('Ese producto ya está en la proforma: cambia la cantidad de su línea.');
            return;
        }
        if (fpForm.lineas.length >= fpForm.config.max_lineas) {
            message_error('Una proforma admite hasta ' + fpForm.config.max_lineas + ' líneas.');
            return;
        }
        fpForm.lineas.push(fpForm.desdeProducto(producto));
        fpForm.dibujar();
    },
    // Importes en centavos (contrato §1): T = precio con IVA × cantidad − descuento; base e IVA se derivan. null si algún
    // dato de la línea no es válido.
    importes: function (l) {
        var r = fpImportes.lineaSegura({precio_con_iva: l.precio_con_iva, cant: l.cant, dscto: l.dscto, tarifa: l.tarifa});
        if (r) r.grupo = l.nombre_tarifa || (r.tarifa + ' %');
        return r;
    },
    celda: function (etiqueta, clase) { return $('<td>').attr('data-label', etiqueta).addClass(clase || ''); },
    entrada: function (nombre, valor, atributos, etiqueta) {
        return $('<input class="form-control fp-num-campo">').attr($.extend({name: nombre, 'aria-label': etiqueta, autocomplete: 'off'}, atributos)).val(valor);
    },
    textoDescuento: function (r, dscto) {
        return r && Number(dscto) > 0 ? '−$' + fpImportes.dinero(r.descuento) + ' con IVA' : 'Sin descuento';
    },
    dibujar: function () {
        var cuerpo = $('#tblLineas tbody').empty(), total = fpForm.lineas.length;
        fpForm.lineas.forEach(function (l, indice) {
            var n = indice + 1, r = fpForm.importes(l), idDesc = 'fp-pf-desc-' + indice, idDscto = 'fp-pf-dscto-' + indice;
            var fila = $('<tr>').attr('data-indice', indice).toggleClass('fp-linea-invalida', !r);
            fila.append(fpForm.celda('Orden', 'fp-col-orden').append($('<div class="fp-orden">').append(
                $('<button type="button" class="fp-asa" aria-describedby="fp-orden-ayuda">').attr('aria-label', 'Mover la línea ' + n)
                    .append($('<span aria-hidden="true">').text('⋮⋮')),
                $('<span class="fp-orden-num" aria-hidden="true">').text(n),
                $('<span class="fp-orden-flechas">').append(
                    $('<button type="button" class="fp-orden-btn" data-mover="-1">').attr('aria-label', 'Subir la línea ' + n)
                        .prop('disabled', n === 1).append('<i class="fas fa-chevron-up" aria-hidden="true"></i>'),
                    $('<button type="button" class="fp-orden-btn" data-mover="1">').attr('aria-label', 'Bajar la línea ' + n)
                        .prop('disabled', n === total).append('<i class="fas fa-chevron-down" aria-hidden="true"></i>')))));
            fila.append(fpForm.celda('Código', 'fp-col-codigo').text(l.codigo));
            var descripcion = $('<textarea class="form-control fp-desc-linea" name="descripcion" rows="1">').attr({
                id: idDesc, maxlength: fpLineas.descripcion.MAX, 'data-contador': idDesc + '-aviso', 'aria-describedby': idDesc + '-aviso',
                'aria-label': 'Descripción de la línea ' + n, spellcheck: 'true'}).val(l.descripcion);
            var pie = $('<div class="fp-desc-pie">').append(
                $('<small class="fp-desc-tarifa">').text('IVA ' + l.nombre_tarifa + (l.inventariado ? ' · stock ' + l.stock : '')),
                $('<small class="fp-desc-producto">').text('Producto: ' + l.nombre).prop('hidden', fpLineas.descripcion.normalizar(l.descripcion) === l.nombre),
                $('<small class="fp-desc-aviso" aria-live="polite">').attr('id', idDesc + '-aviso'));
            fila.append(fpForm.celda('Descripción en la proforma', 'fp-col-desc').append(descripcion, pie));
            fila.append(fpForm.celda('Cantidad', 'fp-col-cant').append($('<div class="fp-num">').append(
                fpForm.entrada('cant', l.cant, {type: 'number', inputmode: 'numeric', min: 1, max: 999999, step: 1}, 'Cantidad de la línea ' + n))));
            fila.append(fpForm.celda('P. unitario con IVA', 'fp-col-precio').append($('<div class="fp-num fp-dinero">').append(
                $('<span class="fp-num-prefijo" aria-hidden="true">').text('$'),
                fpForm.entrada('precio_con_iva', l.precio_con_iva, {type: 'text', inputmode: 'decimal', maxlength: 10}, 'Precio unitario con IVA de la línea ' + n))));
            fila.append(fpForm.celda('Descuento', 'fp-col-dscto').append($('<div class="fp-dscto">').append(
                $('<div class="fp-num fp-num-pct">').append(
                    fpForm.entrada('dscto', l.dscto, {type: 'number', inputmode: 'numeric', min: 0, max: 100, step: 1, 'aria-describedby': idDscto}, 'Descuento en porcentaje de la línea ' + n),
                    $('<span class="fp-num-sufijo" aria-hidden="true">').text('%')),
                $('<small class="fp-dscto-valor">').attr('id', idDscto).text(fpForm.textoDescuento(r, l.dscto)))));
            fila.append(fpForm.celda('Total con IVA', 'fp-col-total text-right').append(
                $('<span class="fp-importe fp-total-linea">').text(r ? '$' + fpImportes.dinero(r.total) : '—')));
            fila.append(fpForm.celda('Quitar', 'fp-col-quitar').append($('<button type="button" class="btn btn-outline-danger fp-quitar" data-quitar>')
                .attr('aria-label', 'Quitar la línea ' + n + ': ' + l.descripcion).append('<i class="fas fa-trash-alt" aria-hidden="true"></i>')));
            cuerpo.append(fila);
        });
        fpLineas.descripcion.ajustarTodas(document.getElementById('tblLineas'));
        fpForm.totales();
    },
    mover: function (desde, hasta) {
        var l = fpForm.lineas;
        if (desde < 0 || desde >= l.length || hasta < 0 || hasta >= l.length) return;
        l.splice(hasta, 0, l.splice(desde, 1)[0]);
        fpForm.dibujar();
    },
    refrescarFila: function (fila, linea) {
        var r = fpForm.importes(linea);
        fila.toggleClass('fp-linea-invalida', !r);
        fila.find('.fp-total-linea').text(r ? '$' + fpImportes.dinero(r.total) : '—');
        fila.find('.fp-dscto-valor').text(fpForm.textoDescuento(r, linea.dscto));
        fpForm.totales();
    },
    totales: function () {
        var t = fpImportes.totales(fpForm.lineas.map(fpForm.importes));
        var cuerpo = $('#fp-totales tbody').empty();
        var fila = function (texto, valor, fuerte) {
            var tr = $('<tr>').append($('<th scope="row">').text(texto), $('<td class="text-right">').text(fpImportes.dinero(valor)));
            if (fuerte) { tr.addClass('font-weight-bold'); }
            cuerpo.append(tr);
        };
        t.grupos.forEach(function (g) { fila('Subtotal ' + g.nombre + ' (sin IVA)', g.base); });
        fila('Descuentos (con IVA)', t.descuento);
        t.grupos.forEach(function (g) { if (g.tarifa > 0) { fila('IVA ' + g.nombre, g.iva); } });
        fila('TOTAL USD (con IVA)', t.total, true);
    },
    tipoCliente: function (tipo) {
        $('.fp-registrado').toggleClass('d-none', tipo !== 'registrado');
        $('.fp-prospecto').toggleClass('d-none', tipo !== 'prospecto');
        if (tipo === 'prospecto') {
            $('#fp-cliente').val(null).trigger('change');
        }
    },
    limpiarErrores: function () {
        $('#fp-errores').addClass('d-none').empty();
        $('#frmForm .is-invalid').removeClass('is-invalid');
        $('#frmForm [data-campo]').text('');
    },
    mostrarErrores: function (datos) {
        var lista = $('<ul class="mb-0">');
        $.each(datos.campos || {}, function (campo, texto) {
            if (campo === 'lineas' && $.isArray(texto)) {
                texto.forEach(function (e) {
                    var fila = $('#tblLineas tbody tr[data-indice="' + Number(e.indice) + '"]');
                    // El servidor anterior llamaba «price» al precio; ahora es el precio con IVA.
                    fila.find('[name="' + (e.campo === 'price' ? 'precio_con_iva' : e.campo) + '"]').addClass('is-invalid');
                    var nombre = fpForm.lineas[e.indice] ? fpForm.lineas[e.indice].nombre : '';
                    lista.append($('<li>').text('Línea ' + (Number(e.indice) + 1) + (nombre ? ' (' + nombre + ')' : '') + ': ' + e.texto));
                });
                return;
            }
            $('#frmForm [name="' + campo + '"]').addClass('is-invalid');
            $('#frmForm [data-campo="' + campo + '"]').text(texto);
            lista.append($('<li>').text(texto));
        });
        $('#fp-errores').empty().append($('<p class="mb-1">').text(datos.error || 'Revisa los datos marcados.'), lista)
            .removeClass('d-none').trigger('focus');
    },
    guardar: function () {
        fpForm.limpiarErrores();
        var datos = new FormData(document.getElementById('frmForm'));
        ['fp_tipo_cliente', 'descripcion', 'cant', 'price', 'precio_con_iva', 'dscto'].forEach(function (n) { datos.delete(n); });
        // Contrato «precios con IVA» §3: en el orden en que se ven las filas, con el precio CON IVA y la descripción.
        datos.append('lineas', JSON.stringify(fpForm.lineas.map(function (l) {
            // Números y precio normalizados cuando son válidos; si no, tal como se escribieron: el servidor marca la línea.
            var c = fpImportes.centavos(String(l.precio_con_iva)), cant = fpImportes.entero(l.cant, 1, 999999),
                dscto = l.dscto === '' ? 0 : fpImportes.entero(l.dscto, 0, 100);
            return {product: l.product, cant: cant === null ? l.cant : cant,
                precio_con_iva: c === null ? l.precio_con_iva : fpImportes.dinero(c), dscto: dscto === null ? l.dscto : dscto,
                descripcion: fpLineas.descripcion.normalizar(l.descripcion)};
        })));
        $.ajax({
            url: pathname, type: 'POST', data: datos, dataType: 'json', processData: false, contentType: false,
            headers: {'X-CSRFToken': csrftoken},
            beforeSend: function () { loading({'text': '...'}); },
            success: function (respuesta) {
                alert_sweetalert({'message': respuesta.mensaje, 'timer': 2500, 'callback': function () {
                    location.href = respuesta.url_ver;
                }});
            },
            error: function (jqXHR) {
                var datos = jqXHR.responseJSON || {};
                if (datos.campos) {
                    fpForm.mostrarErrores(datos);
                } else {
                    message_error(datos.error || 'No se pudo guardar la proforma.');
                }
            },
            complete: function () { $.LoadingOverlay('hide'); }
        });
    },
    buscarCodigo: function (codigo) {
        $.ajax({
            url: pathname, type: 'POST', dataType: 'json', data: {action: 'search_product_code', code: codigo},
            headers: {'X-CSRFToken': csrftoken},
            success: function (producto) {
                if ($.isEmptyObject(producto)) {
                    message_error('No hay un producto con el código ' + codigo + '.');
                    return;
                }
                fpForm.agregar(producto);
            },
            error: fpAccionesError
        });
    },
    buscarEnModal: function () {
        $.ajax({
            url: pathname, type: 'POST', dataType: 'json',
            data: {action: 'search_product', term: $('#fp-modal-termino').val(), ids: JSON.stringify(fpForm.ids())},
            headers: {'X-CSRFToken': csrftoken},
            success: function (productos) {
                var cuerpo = $('#fp-modal-resultados tbody').empty();
                productos.forEach(function (p) {
                    var boton = $('<button type="button" class="btn btn-success btn-xs">').attr('aria-label', 'Agregar ' + p.name)
                        .append('<i class="fas fa-plus" aria-hidden="true"></i>').on('click', function () {
                            fpForm.agregar(p);
                            $(this).closest('tr').remove();
                        });
                    var precio = fpForm.precioConIva(p.precio_con_iva, p.price_current, Number(p.tarifa));
                    cuerpo.append($('<tr>').append(
                        $('<td>').text(p.code), $('<td>').text(p.name), $('<td class="text-right">').text(precio ? '$' + precio : '—'),
                        $('<td>').text(p.inventoried ? p.stock : 'No inventariado'), $('<td>').text(p.nombre_tarifa), $('<td>').append(boton)));
                });
            },
            error: fpAccionesError
        });
    },
    cargar: function (p) {
        if (p.cliente.id) {
            var opcion = new Option(p.cliente.nombre + (p.cliente.identificacion ? ' (' + p.cliente.identificacion + ')' : ''), p.cliente.id, true, true);
            $('#fp-cliente').append(opcion).trigger('change');
        } else {
            $('#fp-tipo-prospecto').prop('checked', true);
            fpForm.tipoCliente('prospecto');
            $('#fp-cliente-nombre').val(p.cliente.nombre);
            $('#fp-cliente-identificacion').val(p.cliente.identificacion);
            $('#fp-cliente-correo').val(p.cliente.correo);
            $('#fp-cliente-telefono').val(p.cliente.telefono);
            $('#fp-cliente-direccion').val(p.cliente.direccion);
        }
        $('#fp-fecha').val(p.fecha);
        $('#fp-valida-hasta').val(p.valida_hasta);
        fpForm.validaHastaTocada = true;
        $('#fp-forma-pago').val(p.forma_pago_sugerida ? p.forma_pago_sugerida.id : '');
        $('#fp-medio-pago').val(p.medio_pago_sugerido ? p.medio_pago_sugerido.id : '');
        $('#fp-ocultar-vendedor').prop('checked', !!p.ocultar_vendedor);
        $('#fp-condiciones').val(p.condiciones);
        var omitidas = [];
        p.lineas.forEach(function (l) {
            if (!l.product_id) {
                omitidas.push(l.descripcion);
                return;
            }
            fpForm.lineas.push({
                product: l.product_id, codigo: l.codigo, nombre: l.producto.nombre, descripcion: l.descripcion, cant: l.cant,
                precio_con_iva: fpForm.precioConIva(l.precio_con_iva, l.price, parseFloat(l.tarifa)),
                dscto: parseInt(l.dscto, 10), tarifa: parseFloat(l.tarifa), nombre_tarifa: l.nombre_tarifa,
                stock: l.producto.stock, inventariado: l.producto.inventariado
            });
        });
        if (omitidas.length) {
            message_error('Estas líneas no se pueden conservar porque su producto ya no existe: ' + omitidas.join(', ') + '.');
        }
    }
};

function fpAccionesError(jqXHR) {
    var datos = jqXHR.responseJSON || {};
    message_error(datos.error || 'No se pudo completar la búsqueda.');
}

$(function () {
    fpForm.config = JSON.parse(document.getElementById('fp-proforma-config').textContent);
    var nodo = document.getElementById('fp-proforma');
    $('#fp-cliente').select2({
        theme: 'bootstrap4', language: 'es', allowClear: true, placeholder: 'Busca por nombre o identificación',
        ajax: {
            url: pathname, type: 'POST', dataType: 'json', delay: 250,
            headers: {'X-CSRFToken': csrftoken},
            data: function (params) { return {action: 'search_client', term: params.term || ''}; },
            processResults: function (datos) { return {results: datos}; }
        },
        minimumInputLength: 1
    });
    $('input[name="fp_tipo_cliente"]').on('change', function () { fpForm.tipoCliente(this.value); });
    if (nodo) {
        fpForm.proforma = JSON.parse(nodo.textContent);
        fpForm.cargar(fpForm.proforma);
    } else {
        $('#fp-fecha').val(fpForm.config.hoy).attr('max', fpForm.config.hoy);
        $('#fp-valida-hasta').val(fpForm.config.valida_hasta);
    }
    $('#fp-fecha').on('change', function () {
        if (this.value && !fpForm.validaHastaTocada) {
            $('#fp-valida-hasta').val(fpForm.sumarDias(this.value, fpForm.config.validez_por_defecto));
        }
    });
    $('#fp-valida-hasta').on('change', function () { fpForm.validaHastaTocada = true; });
    // El medio de pago («Transferencia bancaria») elige su forma de pago del SRI (20); el servidor aplica la misma regla.
    $('#fp-medio-pago').on('change', function () {
        var forma = (fpForm.config.forma_sri_de_medio || {})[this.value];
        if (forma) {
            $('#fp-forma-pago').val(forma);
        }
    });

    var buscador = $('#fp-buscar-producto');
    buscador.autocomplete({
        source: function (pedido, respuesta) {
            $.ajax({
                url: pathname, type: 'POST', dataType: 'json',
                data: {action: 'search_product', term: pedido.term, ids: JSON.stringify(fpForm.ids())},
                headers: {'X-CSRFToken': csrftoken},
                success: function (datos) { respuesta(datos); }
            });
        },
        minLength: 2, delay: 300,
        select: function (evento, ui) {
            evento.preventDefault();
            fpForm.agregar(ui.item);
            $(this).val('');
        }
    }).on('keydown', function (evento) {
        if (evento.key === 'Enter') {
            evento.preventDefault();
            var codigo = $(this).val().trim();
            if (codigo) {
                $(this).autocomplete('close');
                fpForm.buscarCodigo(codigo);
                $(this).val('');
            }
        }
    });
    $('#fp-abrir-busqueda').on('click', function () {
        $('#fp-modal-productos').modal('show');
        fpForm.buscarEnModal();
    });
    $('#fp-modal-termino').on('input', function () {
        clearTimeout(fpForm.esperaModal);
        fpForm.esperaModal = setTimeout(fpForm.buscarEnModal, 300);
    });

    var tabla = document.getElementById('tblLineas');
    $('#tblLineas tbody')
        .on('input change', 'input', function (e) {
            var fila = $(this).closest('tr');
            var linea = fpForm.lineas[Number(fila.attr('data-indice'))];
            linea[this.name] = $(this).val();
            if (e.type === 'change' && this.name === 'precio_con_iva') {   // «12,5» → «12.50» (el servidor valida igual)
                var c = fpImportes.centavos(String(this.value));
                if (c !== null) { linea.precio_con_iva = fpImportes.dinero(c); $(this).val(linea.precio_con_iva); }
            }
            fpForm.refrescarFila(fila, linea);
        })
        .on('click', '[data-quitar]', function () {
            var indice = Number($(this).closest('tr').attr('data-indice'));
            fpForm.lineas.splice(indice, 1);
            fpForm.dibujar();
            var filas = fpLineas.filas(tabla), siguiente = filas[Math.min(indice, filas.length - 1)];
            if (siguiente) { $(siguiente).find('[data-quitar]').trigger('focus'); } else { buscador.trigger('focus'); }
        });
    // Descripción (hasta 300 caracteres, sin saltos de línea) y orden de las filas: el orden de fpForm.lineas es el que se guarda.
    fpLineas.descripcion.activar(tabla.tBodies[0], function (area, texto) {
        var fila = $(area).closest('tr'), linea = fpForm.lineas[Number(fila.attr('data-indice'))];
        linea.descripcion = texto;
        fila.find('.fp-desc-producto').prop('hidden', fpLineas.descripcion.normalizar(texto) === linea.nombre);
    });
    fpLineas.ordenar(tabla, {
        mover: fpForm.mover,
        redibujar: fpForm.dibujar,
        nombre: function (i) { return fpForm.lineas[i] ? fpForm.lineas[i].descripcion : ''; },
        anuncio: document.getElementById('fp-orden-anuncio')
    });
    fpLineas.sinRueda(tabla);

    $('#frmForm').on('submit', function (evento) {
        evento.preventDefault();
        if (!fpForm.lineas.length) {
            message_error('Agrega al menos un producto.');
            return;
        }
        fpForm.guardar();
    });
    fpForm.dibujar();
});
