/* Editor de proformas (crear y editar). Las filas se arman con nodos del DOM y .text()/.val(): ningún dato del usuario se
   inserta como HTML. Los totales son una vista previa; el servidor recalcula y manda. */
var fpForm = {
    config: {},
    proforma: null,
    lineas: [],
    validaHastaTocada: false,
    esperaModal: null,
    redondear: function (valor) { return Math.round((valor + Number.EPSILON) * 100) / 100; },
    dinero: function (valor) { return fpForm.redondear(valor).toFixed(2); },
    sumarDias: function (iso, dias) {
        var partes = iso.split('-').map(Number);
        var fecha = new Date(Date.UTC(partes[0], partes[1] - 1, partes[2] + dias));
        return fecha.toISOString().slice(0, 10);
    },
    ids: function () { return fpForm.lineas.map(function (l) { return l.product; }); },
    desdeProducto: function (p) {
        return {
            product: p.id, codigo: p.code, nombre: p.name, descripcion: p.name, cant: 1,
            price: Number(p.price_current).toFixed(2), dscto: 0, tarifa: Number(p.tarifa), nombre_tarifa: p.nombre_tarifa,
            stock: p.stock, inventariado: p.inventoried
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
    importes: function (l) {
        var subtotal = fpForm.redondear((parseFloat(l.price) || 0) * (parseInt(l.cant, 10) || 0));
        var descuento = fpForm.redondear(subtotal * (parseInt(l.dscto, 10) || 0) / 100);
        var total = subtotal - descuento;
        return {subtotal: subtotal, descuento: descuento, total: total, iva: fpForm.redondear(total * l.tarifa / 100)};
    },
    celda: function (etiqueta) { return $('<td>').attr('data-label', etiqueta); },
    entrada: function (nombre, valor, atributos, etiqueta) {
        return $('<input class="form-control form-control-sm">').attr($.extend({name: nombre, 'aria-label': etiqueta}, atributos)).val(valor);
    },
    dibujar: function () {
        var cuerpo = $('#tblLineas tbody').empty();
        fpForm.lineas.forEach(function (l, indice) {
            var fila = $('<tr>').attr('data-indice', indice);
            fila.append(fpForm.celda('Código').text(l.codigo));
            var producto = fpForm.celda('Producto').text(l.nombre);
            producto.append($('<br>'), $('<small class="text-muted">').text('IVA ' + l.nombre_tarifa +
                (l.inventariado ? ' · stock ' + l.stock : '')));
            fila.append(producto);
            fila.append(fpForm.celda('Descripción').append(fpForm.entrada('descripcion', l.descripcion, {maxlength: 300}, 'Descripción de ' + l.nombre)));
            fila.append(fpForm.celda('Cantidad').append(fpForm.entrada('cant', l.cant, {type: 'number', min: 1, max: 999999, step: 1}, 'Cantidad de ' + l.nombre)));
            fila.append(fpForm.celda('Precio unitario USD').append(fpForm.entrada('price', l.price, {type: 'number', min: 0, max: 999999.99, step: '0.01'}, 'Precio de ' + l.nombre)));
            fila.append(fpForm.celda('Descuento %').append(fpForm.entrada('dscto', l.dscto, {type: 'number', min: 0, max: 100, step: 1}, 'Descuento de ' + l.nombre)));
            fila.append(fpForm.celda('Total USD').addClass('fp-total-linea text-right').text(fpForm.dinero(fpForm.importes(l).total)));
            fila.append(fpForm.celda('Quitar').append($('<button type="button" class="btn btn-danger btn-xs btn-flat" data-quitar>')
                .attr('aria-label', 'Quitar ' + l.nombre).append('<i class="fas fa-times" aria-hidden="true"></i>')));
            cuerpo.append(fila);
        });
        fpForm.totales();
    },
    totales: function () {
        var grupos = {}, orden = [], descuento = 0, total = 0;
        fpForm.lineas.forEach(function (l) {
            var i = fpForm.importes(l);
            if (!grupos[l.nombre_tarifa]) {
                grupos[l.nombre_tarifa] = {base: 0, iva: 0, tarifa: l.tarifa};
                orden.push(l.nombre_tarifa);
            }
            grupos[l.nombre_tarifa].base += i.total;
            grupos[l.nombre_tarifa].iva += i.iva;
            descuento += i.descuento;
            total += i.total + i.iva;
        });
        orden.sort(function (a, b) { return grupos[b].tarifa - grupos[a].tarifa; });
        var cuerpo = $('#fp-totales tbody').empty();
        var fila = function (texto, valor, fuerte) {
            var tr = $('<tr>').append($('<th scope="row">').text(texto), $('<td class="text-right">').text(fpForm.dinero(valor)));
            if (fuerte) { tr.addClass('font-weight-bold'); }
            cuerpo.append(tr);
        };
        orden.forEach(function (n) { fila('Subtotal ' + n, grupos[n].base); });
        fila('Descuentos', descuento);
        orden.forEach(function (n) { if (grupos[n].tarifa > 0) { fila('IVA ' + n, grupos[n].iva); } });
        fila('TOTAL USD', total, true);
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
                    fila.find('[name="' + e.campo + '"]').addClass('is-invalid');
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
        ['fp_tipo_cliente', 'descripcion', 'cant', 'price', 'dscto'].forEach(function (n) { datos.delete(n); });
        datos.append('lineas', JSON.stringify(fpForm.lineas.map(function (l) {
            return {product: l.product, cant: l.cant, price: l.price, dscto: l.dscto, descripcion: l.descripcion};
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
                    cuerpo.append($('<tr>').append(
                        $('<td>').text(p.code), $('<td>').text(p.name), $('<td class="text-right">').text(Number(p.price_current).toFixed(2)),
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
        $('#fp-condiciones').val(p.condiciones);
        var omitidas = [];
        p.lineas.forEach(function (l) {
            if (!l.product_id) {
                omitidas.push(l.descripcion);
                return;
            }
            fpForm.lineas.push({
                product: l.product_id, codigo: l.codigo, nombre: l.producto.nombre, descripcion: l.descripcion, cant: l.cant,
                price: l.price, dscto: parseInt(l.dscto, 10), tarifa: parseFloat(l.tarifa), nombre_tarifa: l.nombre_tarifa,
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

    $('#tblLineas tbody')
        .on('input change', 'input', function () {
            var fila = $(this).closest('tr');
            var linea = fpForm.lineas[Number(fila.attr('data-indice'))];
            linea[this.name] = $(this).val();
            fila.find('.fp-total-linea').text(fpForm.dinero(fpForm.importes(linea).total));
            fpForm.totales();
        })
        .on('click', '[data-quitar]', function () {
            fpForm.lineas.splice(Number($(this).closest('tr').attr('data-indice')), 1);
            fpForm.dibujar();
        });

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
