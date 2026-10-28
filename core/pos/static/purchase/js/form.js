// Nueva compra (espec-etapa2-compras §6.B). El servidor valida y calcula todo (compras.calcular / crear_compra); aquí solo
// se arma la cabecera y las líneas. Nada que decida el crédito tributario se elige de oficio (DC12): forma de pago y
// sustento empiezan vacíos; las sugerencias solo cambian el campo con «Usar sugerencia». Los importes llegan como texto.
var opciones = {tarifas: [], sustentos: [], comprobantes_por_sustento: {}};
var tipo_inicial = 'inventario';
var sustento_sugerido = '';
var select_provider, select_compra_modificada, input_search_product;
var temporizador_calculo = null;
var ultimo_calculo = null;

var compra = {
    lineas: [],
    proveedor: null
};

function esc(valor) {
    return $('<div>').text(valor === null || valor === undefined ? '' : String(valor)).html();
}

function leer_json(id, defecto) {
    try {
        return JSON.parse(document.getElementById(id).textContent);
    } catch (e) {
        return defecto;
    }
}

function texto_errores(error) {
    if (typeof error === 'string') {
        return error;
    }
    return Object.keys(error || {}).map(function (campo) {
        var etiqueta = $('#frmProvider label[for="fp_proveedor_' + campo + '"]').text().replace(':', '') || campo;
        return etiqueta + ': ' + [].concat(error[campo]).join(' ');
    }).join('\n');
}

function campo(nombre) {
    return $('#frmForm [name="' + nombre + '"]');
}

function modo_actual() {
    return $('#frmForm input[name="modo_comprobante"]:checked').val() || 'si';
}

function tipo_actual() {
    return modo_actual() === 'liquidacion' ? '03' : campo('tipo_comprobante').val();
}

var form_compra = {
    lineas_para_enviar: function () {
        return compra.lineas.map(function (l) {
            var linea = {
                tipo: l.tipo, cant: l.cant, price: l.price, descuento: l.descuento,
                codigo_porcentaje: l.codigo_porcentaje
            };
            if (l.tipo === 'producto') {
                linea.product = l.product;
            } else {
                linea.descripcion = l.descripcion;
                linea.type_expense = l.type_expense;
            }
            if (l.codigo_porcentaje === '8') {
                linea.tarifa = l.tarifa;
            }
            return linea;
        });
    },
    parametros: function (accion) {
        var params = new FormData(document.getElementById('frmForm'));
        params.set('action', accion);
        params.set('lineas', JSON.stringify(this.lineas_para_enviar()));
        return params;
    },
    enviar: function (accion, exito, fallo) {
        $.ajax({
            url: pathname,
            data: this.parametros(accion),
            type: 'POST',
            dataType: 'json',
            headers: {'X-CSRFToken': csrftoken},
            processData: false,
            contentType: false
        }).done(function (data) {
            if (data.error) {
                if (fallo) {
                    fallo(data);
                } else {
                    message_error(data.error);
                }
                return;
            }
            exito(data);
        }).fail(function (jqXHR) {
            message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || 'No se pudo completar la acción.');
        });
    },
    // ------------------------------------------------------------------ cabecera
    actualizar_modo: function () {
        var modo = modo_actual();
        $('#fp-aviso-liquidacion').toggleClass('d-none', modo !== 'liquidacion');
        $('#fp-aviso-despues').toggleClass('d-none', modo !== 'despues');
        $('#fp-grupo-tipo').toggleClass('d-none', modo === 'liquidacion');
        $('#fp-numeracion').toggleClass('d-none', modo === 'liquidacion');
        if (modo === 'liquidacion') {
            ['estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision'].forEach(function (n) {
                campo(n).val('');
            });
            campo('tipo_comprobante').val('');
        }
        this.actualizar_tipo();
    },
    actualizar_tipo: function () {
        var tipo = tipo_actual();
        var actual = campo('cod_sustento').val();
        var select = campo('cod_sustento').empty().append($('<option>').val('').text('Elige el sustento tributario'));
        opciones.sustentos.forEach(function (s) {
            var admitidos = opciones.comprobantes_por_sustento[s[0]] || [];
            if (!tipo || admitidos.indexOf(tipo) >= 0) {
                select.append($('<option>').val(s[0]).text(s[0] + ' · ' + s[1]));
            }
        });
        if (select.find('option[value="' + actual + '"]').length) {
            select.val(actual);
        }
        var con_doc = (opciones.tipos_con_doc_modificado || []).indexOf(tipo) >= 0;
        $('#fp-doc-modificado').toggleClass('d-none', !con_doc);
        $('#fp-grupo-forma-pago').toggleClass('d-none', (opciones.tipos_sin_forma_pago || []).indexOf(tipo) >= 0);
        this.render_lineas();
        this.programar_calculo();
    },
    al_elegir_proveedor: function (proveedor) {
        compra.proveedor = proveedor;
        var aviso = $('#fp-proveedor-aviso').empty().addClass('d-none');
        if (!proveedor) {
            return;
        }
        if (campo('parte_relacionada').val() === '' && proveedor.parte_relacionada !== null && proveedor.parte_relacionada !== undefined) {
            campo('parte_relacionada').val(proveedor.parte_relacionada ? 'si' : 'no');   // dato ya registrado del proveedor
        }
        var tipo_id = proveedor.tipo_identificacion ? proveedor.tipo_identificacion.id : '';
        if (campo('pago_loc_ext').val() === '' && (tipo_id === '04' || tipo_id === '05')) {
            campo('pago_loc_ext').val('01');
        }
        if (proveedor.datos_completos === false) {
            aviso.append($('<strong>').text('El proveedor tiene datos incompletos: '));
            var lista = $('<ul class="mb-1">').appendTo(aviso);
            (proveedor.faltantes || []).forEach(function (f) {
                lista.append($('<li>').text(f.texto));
            });
            aviso.append($('<a>').attr('href', '/pos/provider/update/' + parseInt(proveedor.id, 10) + '/').attr('target', '_blank')
                .text('Completar los datos del proveedor'));
            aviso.removeClass('d-none');
        }
        select_compra_modificada.val(null).trigger('change');
        this.validar_comprobante();
        this.programar_calculo();
    },
    validar_comprobante: function () {
        var aviso = $('#fp-comprobante-aviso').empty().addClass('d-none');
        var datos = {
            action: 'validate_comprobante', provider: select_provider.val() || '', tipo_comprobante: tipo_actual() || '',
            estab: campo('estab').val(), pto_emi: campo('pto_emi').val(), secuencial: campo('secuencial').val()
        };
        if (!datos.provider || !datos.tipo_comprobante || !datos.secuencial) {
            return;
        }
        $.ajax({url: pathname, type: 'POST', headers: {'X-CSRFToken': csrftoken}, data: datos, dataType: 'json'})
            .done(function (data) {
                if (data.error || !data.mensaje) {
                    return;
                }
                aviso.text(data.mensaje + ' ');
                if (data.documento_importado) {
                    aviso.append($('<a>').attr('href', data.documento_importado.url).text('Ver el XML importado'));
                }
                aviso.toggleClass('alert-danger', !data.valid).toggleClass('alert-warning', data.valid).removeClass('d-none');
            });
    },
    // ------------------------------------------------------------------ líneas
    tarifas_admitidas: function () {
        var tipo = tipo_actual();
        if ((opciones.tipos_sin_iva_discriminado || []).indexOf(tipo) >= 0) {
            return opciones.tarifas.filter(function (t) {
                return (opciones.codigos_iva_nota_venta || []).indexOf(t.codigo) >= 0;
            });
        }
        return opciones.tarifas;
    },
    agregar_producto: function (item) {
        var admitidas = this.tarifas_admitidas().map(function (t) { return t.codigo; });
        compra.lineas.push({
            tipo: 'producto', product: item.id, nombre: item.full_name || item.value, codigo: item.code, cant: 1,
            price: Number(item.price || 0).toFixed(2), descuento: '0.00',
            codigo_porcentaje: admitidas.indexOf(item.tarifa_iva) >= 0 ? item.tarifa_iva : '', tarifa: ''
        });
        this.render_lineas();
        this.programar_calculo();
    },
    agregar_gasto: function () {
        compra.lineas.push({
            tipo: 'gasto', descripcion: '', type_expense: null, type_expense_nombre: '', cant: 1, price: '',
            descuento: '0.00', codigo_porcentaje: '', tarifa: ''
        });
        this.render_lineas();
        $('#tblLineas tbody tr:last input[name="descripcion"]').focus();
    },
    render_lineas: function () {
        var cuerpo = $('#tblLineas tbody').empty();
        var admitidas = this.tarifas_admitidas();
        var calculadas = (ultimo_calculo && ultimo_calculo.lineas) || [];
        compra.lineas.forEach(function (l, i) {
            if (l.codigo_porcentaje && !admitidas.some(function (t) { return t.codigo === l.codigo_porcentaje; })) {
                l.codigo_porcentaje = '';
            }
            var fila = $('<tr>').attr('data-index', i);
            var celda_nombre = $('<td>');
            if (l.tipo === 'producto') {
                celda_nombre.append($('<span class="badge badge-info mr-1">').text('Producto'))
                    .append($('<span>').text(l.nombre));
            } else {
                celda_nombre.append($('<span class="badge badge-secondary mr-1">').text('Gasto'))
                    .append($('<input type="text" class="form-control form-control-sm" name="descripcion" maxlength="300" aria-label="Descripción del gasto">')
                        .attr('placeholder', 'Descripción del gasto').val(l.descripcion));
            }
            fila.append(celda_nombre);
            var celda_tipo = $('<td>');
            if (l.tipo === 'gasto') {
                var select = $('<select class="form-control form-control-sm" name="type_expense" aria-label="Tipo de gasto" style="width: 100%;">');
                if (l.type_expense) {
                    select.append(new Option(l.type_expense_nombre, l.type_expense, true, true));
                }
                celda_tipo.append(select);
            } else {
                celda_tipo.text('—');
            }
            fila.append(celda_tipo);
            fila.append($('<td>').append($('<input type="number" class="form-control form-control-sm" name="cant" min="1" step="1" aria-label="Cantidad">').val(l.cant)));
            fila.append($('<td>').append($('<input type="text" class="form-control form-control-sm" name="price" inputmode="decimal" aria-label="Precio">').val(l.price)));
            fila.append($('<td>').append($('<input type="text" class="form-control form-control-sm" name="descuento" inputmode="decimal" aria-label="Descuento en dólares">').val(l.descuento)));
            var tarifa = $('<select class="form-control form-control-sm" name="codigo_porcentaje" aria-label="Tarifa de IVA">')
                .append($('<option>').val('').text('Elige la tarifa'));
            admitidas.forEach(function (t) {
                tarifa.append($('<option>').val(t.codigo).text(t.nombre));
            });
            tarifa.val(l.codigo_porcentaje);
            fila.append($('<td>').append(tarifa));
            fila.append($('<td>').append($('<input type="text" class="form-control form-control-sm" name="tarifa" inputmode="decimal" aria-label="Tarifa del IVA diferenciado">')
                .val(l.tarifa).prop('disabled', l.codigo_porcentaje !== '8').attr('placeholder', l.codigo_porcentaje === '8' ? '8.00' : '')));
            var calculada = calculadas[i] || {};
            fila.append($('<td class="text-right fp-base">').text(calculada.total ? '$' + calculada.total : '—'));
            fila.append($('<td class="text-right fp-iva">').text(calculada.total_iva ? '$' + calculada.total_iva : '—'));
            fila.append($('<td class="text-center">').append($('<button type="button" class="btn btn-danger btn-xs btn-flat" rel="remove" aria-label="Quitar la línea"><i class="fas fa-times"></i></button>')));
            cuerpo.append(fila);
        });
        cuerpo.find('select[name="type_expense"]').each(function () {
            form_compra.iniciar_tipo_gasto($(this));
        });
    },
    iniciar_tipo_gasto: function (select) {
        select.select2({
            theme: 'bootstrap4', language: 'es', allowClear: true, placeholder: 'Tipo de gasto (opcional)',
            ajax: {
                delay: 250, type: 'POST', url: pathname, headers: {'X-CSRFToken': csrftoken},
                data: function (params) {
                    return {term: params.term || '', action: 'search_type_expense'};
                },
                processResults: function (data) {
                    return {results: data.error ? [] : data};
                }
            }
        }).on('select2:select', function (e) {
            var i = parseInt($(this).closest('tr').attr('data-index'), 10);
            compra.lineas[i].type_expense = e.params.data.id;
            compra.lineas[i].type_expense_nombre = e.params.data.text;
            // Con ?tipo=gasto el sustento se precarga solo si el tipo de gasto elegido lo tiene guardado.
            var sustento = campo('cod_sustento');
            if (tipo_inicial === 'gasto' && !sustento.val() && e.params.data.cod_sustento
                && sustento.find('option[value="' + e.params.data.cod_sustento + '"]').length) {
                sustento.val(e.params.data.cod_sustento);
            }
            form_compra.programar_calculo();
        }).on('select2:clear', function () {
            var i = parseInt($(this).closest('tr').attr('data-index'), 10);
            compra.lineas[i].type_expense = null;
            compra.lineas[i].type_expense_nombre = '';
        });
    },
    // ------------------------------------------------------------------ cálculo en el servidor
    programar_calculo: function () {
        clearTimeout(temporizador_calculo);
        temporizador_calculo = setTimeout(function () {
            form_compra.calcular(false);
        }, 600);
    },
    calcular: function (avisar) {
        if (!select_provider.val() || compra.lineas.length === 0) {
            return;
        }
        this.enviar('calcular', function (data) {
            ultimo_calculo = data;
            form_compra.mostrar_resumen(data);
        }, function (data) {
            ultimo_calculo = null;
            $('#fp-resumen-error').text(data.error).removeClass('d-none');
            $('#fp-resumen-tarifas, #fp-resumen-totales, #fp-resumen-advertencias, #fp-resumen-faltantes').addClass('d-none');
            $('.fp-total-compra').text('—');
            if (avisar) {
                message_error(data.error);
            }
        });
    },
    mostrar_resumen: function (data) {
        $('#fp-resumen-error').addClass('d-none').text('');
        var tarifas = $('#fp-resumen-tarifas').removeClass('d-none').find('tbody').empty();
        data.por_tarifa.forEach(function (g) {
            $('<tr>').append($('<td>').text(g.nombre)).append($('<td class="text-right">').text('$' + g.base))
                .append($('<td class="text-right">').text(g.valor === null ? '—' : '$' + g.valor)).appendTo(tarifas);
        });
        var totales = $('#fp-resumen-totales').removeClass('d-none').empty();
        [['Subtotal sin impuestos', data.subtotal], ['Descuento', data.total_descuento],
            ['IVA calculado por líneas', data.total_iva_calculado], ['IVA de la compra', data.total_iva], ['ICE', data.total_ice],
            ['Propina', data.propina], ['Total con IVA', data.total]].forEach(function (par) {
            totales.append($('<dt class="col-sm-6">').text(par[0])).append($('<dd class="col-sm-6 text-right">').text('$' + par[1]));
        });
        $('.fp-total-compra').text('$' + data.total);
        var advertencias = $('#fp-resumen-advertencias').toggleClass('d-none', !data.advertencias.length).find('ul').empty();
        data.advertencias.forEach(function (a) {
            advertencias.append($('<li>').text(a.texto));
        });
        var faltantes = $('#fp-resumen-faltantes').toggleClass('d-none', !data.faltantes.length).find('ul').empty();
        data.faltantes.forEach(function (f) {
            faltantes.append($('<li>').text(f.texto));
        });
        (data.confirmaciones || []).forEach(function (codigo) {
            $('.fp-confirmacion[data-confirmacion="' + codigo + '"]').removeClass('d-none');
        });
        // Solo se actualizan los importes de cada línea: rehacer la tabla quitaría el foco a quien está escribiendo.
        $('#tblLineas tbody tr').each(function () {
            var calculada = data.lineas[parseInt($(this).attr('data-index'), 10)] || {};
            $(this).find('.fp-base').text(calculada.total ? '$' + calculada.total : '—');
            $(this).find('.fp-iva').text(calculada.total_iva ? '$' + calculada.total_iva : '—');
        });
    },
    guardar: function () {
        if (compra.lineas.length === 0) {
            message_error('Agrega al menos una línea a la compra.');
            return;
        }
        dialog_action({
            content: '¿Registrar la compra?',
            success: function () {
                form_compra.enviar('add', function () {
                    location.href = $('#frmForm').attr('data-url');
                }, function (data) {
                    if (data.confirmacion) {
                        $('.fp-confirmacion[data-confirmacion="' + data.confirmacion + '"]').removeClass('d-none');
                    }
                    message_error(data.error);
                });
            },
            cancel: function () {
            }
        });
    }
};

// Tipo de sujeto del proveedor: con RUC (tercer dígito 6 o 9 → sociedad) y cédula se calcula; con pasaporte o
// identificación del exterior se elige. El servidor lo vuelve a calcular.
function actualizar_sujeto_proveedor() {
    var tipo = $('#frmProvider [name="tipo_identificacion"]').val();
    var numero = ($('#frmProvider [name="ruc"]').val() || '').replace(/\s/g, '');
    var sujeto = $('#frmProvider [name="tipo_sujeto"]');
    if (tipo === '04') {
        sujeto.val(numero.length >= 3 && '69'.indexOf(numero.charAt(2)) >= 0 ? '02' : '01').prop('disabled', true);
    } else if (tipo === '05') {
        sujeto.val('01').prop('disabled', true);
    } else {
        sujeto.prop('disabled', false);
    }
}

$(function () {
    opciones = leer_json('fp-compra-opciones', opciones);
    tipo_inicial = leer_json('fp-compra-tipo-inicial', 'inventario');
    sustento_sugerido = leer_json('fp-compra-sustento-sugerido', '');
    select_provider = campo('provider');
    select_compra_modificada = campo('compra_modificada');
    input_search_product = $('#fp-buscar-producto');

    ['date_joined', 'end_credit', 'fecha_emision', 'fecha_doc_modificado'].forEach(function (id) {
        $('#' + id).datetimepicker({format: 'YYYY-MM-DD', useCurrent: false, locale: 'es', keepOpen: false});
        $('#' + id).on('change.datetimepicker', function () {
            form_compra.programar_calculo();
        });
    });

    select_provider.select2({
        theme: 'bootstrap4', language: 'es', allowClear: true, placeholder: 'Ingrese un nombre o ruc de proveedor',
        minimumInputLength: 1,
        ajax: {
            delay: 250, type: 'POST', url: pathname, headers: {'X-CSRFToken': csrftoken},
            data: function (params) {
                return {term: params.term, action: 'search_provider'};
            },
            processResults: function (data) {
                return {results: data.error ? [] : data};
            }
        }
    }).on('select2:select', function (e) {
        form_compra.al_elegir_proveedor(e.params.data);
    }).on('select2:clear', function () {
        form_compra.al_elegir_proveedor(null);
    });

    select_compra_modificada.select2({
        theme: 'bootstrap4', language: 'es', allowClear: true, placeholder: 'Busca la factura del proveedor',
        ajax: {
            delay: 250, type: 'POST', url: pathname, headers: {'X-CSRFToken': csrftoken},
            data: function (params) {
                return {term: params.term || '', provider: select_provider.val() || '', action: 'search_compra_modificada'};
            },
            processResults: function (data) {
                return {results: data.error ? [] : data};
            }
        }
    });

    $('#frmForm input[name="modo_comprobante"]').on('change', function () {
        form_compra.actualizar_modo();
    });
    campo('tipo_comprobante').on('change', function () {
        form_compra.actualizar_tipo();
        form_compra.validar_comprobante();
    });
    campo('estab').add(campo('pto_emi')).add(campo('secuencial')).on('change', function () {
        form_compra.validar_comprobante();
    });
    $('#frmForm').on('change', 'select[name="cod_sustento"], select[name="forma_pago"], select[name="parte_relacionada"], ' +
        'select[name="pago_loc_ext"], select[name="payment_type"], input[name="total_ice"], input[name="propina"], ' +
        'input[name="iva_factura"], input[name="autorizacion"]', function () {
        form_compra.programar_calculo();
    });

    campo('payment_type').on('change', function () {
        $('#fp-plazo-credito').toggleClass('d-none', $(this).val() !== 'credito');
    }).trigger('change');

    $('#fp-usar-sugerencia').on('click', function () {
        var sustento = campo('cod_sustento');
        if (sustento.find('option[value="' + sustento_sugerido + '"]').length) {
            sustento.val(sustento_sugerido);
            form_compra.programar_calculo();
        } else {
            message_error('El sustento sugerido no admite el tipo de comprobante elegido.');
        }
    });

    input_search_product.autocomplete({
        source: function (request, response) {
            $.ajax({
                url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
                data: {
                    'action': 'search_product', 'term': request.term,
                    'ids': JSON.stringify(compra.lineas.filter(function (l) { return l.tipo === 'producto'; })
                        .map(function (l) { return l.product; }))
                },
                success: function (data) {
                    response(data.error ? [] : data);
                }
            });
        },
        minLength: 2,
        delay: 300,
        select: function (event, ui) {
            event.preventDefault();
            form_compra.agregar_producto(ui.item);
            $(this).val('').focus();
        }
    });

    $('#fp-agregar-gasto').on('click', function () {
        form_compra.agregar_gasto();
    });

    $('#tblLineas tbody')
        .on('change', 'input, select[name="codigo_porcentaje"]', function () {
            var i = parseInt($(this).closest('tr').attr('data-index'), 10);
            var nombre = $(this).attr('name');
            if (nombre === 'type_expense' || isNaN(i)) {
                return;
            }
            compra.lineas[i][nombre] = $(this).val();
            if (nombre === 'codigo_porcentaje') {
                if ($(this).val() !== '8') {
                    compra.lineas[i].tarifa = '';
                }
                form_compra.render_lineas();
            }
            form_compra.programar_calculo();
        })
        .on('click', 'button[rel="remove"]', function () {
            var i = parseInt($(this).closest('tr').attr('data-index'), 10);
            compra.lineas.splice(i, 1);
            ultimo_calculo = null;
            form_compra.render_lineas();
            form_compra.programar_calculo();
        });

    $('#fp-calcular').on('click', function () {
        form_compra.calcular(true);
    });

    $('#frmForm').on('submit', function (e) {
        e.preventDefault();
        form_compra.guardar();
    });

    // Proveedor nuevo desde el modal (mismos campos y validación que la pantalla de proveedores).
    $('.btnAddProvider').on('click', function () {
        $('#myModalProvider').modal('show');
    });
    $('#frmProvider [name="tipo_identificacion"], #frmProvider [name="ruc"]').on('change keyup', actualizar_sujeto_proveedor);
    $('#myModalProvider').on('hidden.bs.modal', function () {
        document.getElementById('frmProvider').reset();
        $('#fp-proveedor-errores').addClass('d-none').text('');
        actualizar_sujeto_proveedor();
    });
    $('#frmProvider').on('submit', function (e) {
        e.preventDefault();
        var params = new FormData(this);
        params.append('action', 'create_provider');
        $.ajax({
            url: pathname, data: params, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            processData: false, contentType: false
        }).done(function (data) {
            if (data.error) {
                $('#fp-proveedor-errores').text(texto_errores(data.error)).css('white-space', 'pre-line').removeClass('d-none');
                return;
            }
            var opcion = new Option(data.text, data.id, true, true);
            select_provider.append(opcion).trigger('change');
            select_provider.trigger({type: 'select2:select', params: {data: data}});
            $('#myModalProvider').modal('hide');
        }).fail(function (jqXHR) {
            message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || 'No se pudo crear el proveedor.');
        });
    });

    form_compra.actualizar_modo();
    actualizar_sujeto_proveedor();
    if (tipo_inicial === 'gasto') {
        form_compra.agregar_gasto();
    }
});
