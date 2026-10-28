// Listado de compras (espec-etapa2-compras §6.A). Toda columna de texto se escapa (render.text o esc): la razón social y
// las descripciones pueden venir del XML de un tercero. Los importes llegan como texto ("135.00") o null.
var tblPurchase;
var input_date_range;
var permisos_compras = {};

function esc(valor) {
    return $('<div>').text(valor === null || valor === undefined ? '' : String(valor)).html();
}

function dinero(valor) {
    return valor === null || valor === undefined ? '—' : '$' + valor;
}

var purchase = {
    filtros: function (all) {
        var parameters = {
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
            'fecha': $('#fp-compras-fecha').val(),
            'incompletas': $('#fp-compras-incompletas').is(':checked') ? '1' : ''
        };
        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }
        return parameters;
    },
    totales: function (parameters) {
        $.ajax({
            url: pathname,
            type: 'POST',
            headers: {'X-CSRFToken': csrftoken},
            data: $.extend({'action': 'totales'}, parameters),
            dataType: 'json'
        }).done(function (data) {
            if (data.error) {
                return;
            }
            $('.fp-total-completas').text('$' + data.completas.total);
            $('.fp-total-incompletas').text(data.incompletas.cantidad > 0
                ? data.incompletas.cantidad + ' compras con datos incompletos — subtotal registrado $' + data.incompletas.subtotal
                : '');
        });
    },
    list: function (all) {
        var parameters = this.filtros(all);
        purchase.totales(parameters);
        tblPurchase = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            order: [[5, 'desc']],
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: $.extend({'action': 'search'}, parameters),
                dataSrc: ""
            },
            columns: [
                {data: "numero_comprobante", render: $.fn.dataTable.render.text()},
                {data: "tipo_comprobante.name", render: $.fn.dataTable.render.text()},
                {data: "provider.name", render: $.fn.dataTable.render.text()},
                {data: "provider.ruc", render: $.fn.dataTable.render.text()},
                {data: "fecha_emision", render: function (data) { return data ? data : '—'; }},
                {data: "date_joined"},
                {
                    data: "payment_type.name",
                    class: 'text-center',
                    render: function (data, type, row) {
                        var clase = row.payment_type.id === 'credito' ? 'badge-warning' : 'badge-success';
                        return '<span class="badge ' + clase + ' badge-pill">' + esc(data) + '</span>';
                    }
                },
                {
                    data: "subtotal",
                    class: 'text-right',
                    render: function (data) { return '$' + Number(data).toFixed(2); }
                },
                {data: "total_iva", class: 'text-right', render: function (data) { return dinero(data); }},
                {data: "total", class: 'text-right', render: function (data) { return dinero(data); }},
                {
                    data: "datos_incompletos",
                    class: 'text-center',
                    render: function (data, type, row) {
                        var insignias = '';
                        if (row.datos_incompletos && row.version_datos === 1) {
                            insignias += '<span class="badge badge-secondary">Compra anterior · sin IVA</span> ';
                        } else if (row.datos_incompletos) {
                            insignias += '<span class="badge badge-warning">Datos incompletos</span> ';
                        }
                        if (row.fuera_plazo_ats) {
                            insignias += '<span class="badge badge-danger">Fuera del plazo del ATS</span>';
                        }
                        return insignias || '<span class="text-muted">Completa</span>';
                    }
                },
                {
                    data: "id",
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        var id = parseInt(row.id, 10);
                        var tipo = row.tipo_comprobante.id;
                        var buttons = '<a class="btn btn-success btn-xs btn-flat" rel="detail" data-toggle="tooltip" title="Detalle"><i class="fas fa-folder-open"></i></a> ';
                        if (permisos_compras.puede_completar) {
                            var texto = row.datos_incompletos ? 'Completar datos' : 'Editar datos del comprobante';
                            buttons += '<a href="/pos/purchase/complete/' + id + '/" class="btn btn-warning btn-xs btn-flat" title="' + texto + '"><i class="fas fa-edit"></i> ' + texto + '</a> ';
                        }
                        if (['', '01', '03'].indexOf(tipo) >= 0) {
                            // Comprobante de retención sobre la factura de esta compra (core/comprobantes).
                            buttons += '<a href="/comprobantes/retenciones/nueva/' + id + '/" data-toggle="tooltip" title="Emitir retención" class="btn btn-info btn-xs btn-flat fp-retencion-compra"><i class="fas fa-file-invoice-dollar"></i> Retención</a> ';
                        }
                        if (['', '03'].indexOf(tipo) >= 0) {
                            // Liquidación de compra cuando el vendedor no puede emitir factura (core/comprobantes).
                            buttons += '<a href="/comprobantes/liquidaciones/nueva/' + id + '/" data-toggle="tooltip" title="Emitir liquidación de compra" class="btn btn-info btn-xs btn-flat fp-retencion-compra"><i class="fas fa-file-signature"></i> Liquidación</a> ';
                        }
                        if (permisos_compras.puede_eliminar) {
                            buttons += '<a href="' + pathname + 'delete/' + id + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                        }
                        return buttons;
                    }
                },
            ],
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    fila: function (etiqueta, valor) {
        $('#fp-compra-cabecera')
            .append($('<dt class="col-sm-4">').text(etiqueta))
            .append($('<dd class="col-sm-8">').text(valor === null || valor === undefined || valor === '' ? '—' : valor));
    },
    detalle: function (id) {
        $.ajax({
            url: pathname,
            type: 'POST',
            headers: {'X-CSRFToken': csrftoken},
            data: {'action': 'detalle', 'id': id},
            dataType: 'json'
        }).done(function (data) {
            if (data.error) {
                message_error(data.error);
                return;
            }
            var c = data.compra;
            $('#fp-compra-cabecera').empty();
            purchase.fila('Compra', '#' + c.id + ' · ' + c.numero_comprobante);
            purchase.fila('Tipo de comprobante', c.tipo_comprobante.name);
            purchase.fila('Proveedor', c.provider.name + ' (' + c.provider.ruc + ')');
            purchase.fila('Sustento tributario', c.cod_sustento.name);
            purchase.fila('Autorización', c.autorizacion);
            purchase.fila('Fecha de emisión', c.fecha_emision);
            purchase.fila('Fecha de registro', c.date_joined);
            purchase.fila('Forma de pago (ATS)', c.forma_pago.name);
            purchase.fila('Origen', c.origen.name);
            purchase.fila('Base 0 % / gravada / 5 %', [dinero(c.base_0), dinero(c.base_gravada), dinero(c.base_5)].join(' / '));
            purchase.fila('No objeto / exenta', [dinero(c.base_no_objeto), dinero(c.base_exenta)].join(' / '));
            purchase.fila('IVA · ICE · propina', [dinero(c.total_iva), dinero(c.total_ice), dinero(c.propina)].join(' · '));
            purchase.fila('Total', dinero(c.total));
            if (c.doc_modificado) {
                purchase.fila('Documento modificado', c.doc_modificado.tipo + ' ' + c.doc_modificado.numero + ' · ' + (c.doc_modificado.fecha || ''));
            }
            var faltantes = $('#fp-compra-faltantes');
            faltantes.find('ul').empty();
            (c.faltantes || []).forEach(function (f) {
                faltantes.find('ul').append($('<li>').text(f.texto));
            });
            faltantes.toggleClass('d-none', !(c.faltantes || []).length);
            var cuerpo = $('#tblProducts tbody').empty();
            data.lineas.forEach(function (l) {
                var nombre = l.product ? l.product.full_name : l.descripcion;
                if (l.type_expense) {
                    nombre += ' · ' + l.type_expense.name;
                }
                $('<tr>')
                    .append($('<td>').text(nombre))
                    .append($('<td>').text(l.nombre_tarifa))
                    .append($('<td class="text-right">').text(l.cant))
                    .append($('<td class="text-right">').text('$' + Number(l.price).toFixed(2)))
                    .append($('<td class="text-right">').text(dinero(l.total_dscto)))
                    .append($('<td class="text-right">').text(l.total === null ? '$' + Number(l.subtotal).toFixed(2) : dinero(l.total)))
                    .append($('<td class="text-right">').text(dinero(l.total_iva)))
                    .appendTo(cuerpo);
            });
            var tarifas = $('#fp-compra-tarifas tbody').empty();
            data.por_tarifa.forEach(function (g) {
                $('<tr>').append($('<td>').text(g.nombre)).append($('<td class="text-right">').text(dinero(g.base)))
                    .append($('<td class="text-right">').text(dinero(g.valor))).appendTo(tarifas);
            });
            var cuenta = $('#fp-compra-cuenta').empty();
            if (data.cuenta_por_pagar) {
                var cxp = data.cuenta_por_pagar;
                cuenta.append($('<h6 class="font-weight-bold">').text('Cuenta por pagar'));
                cuenta.append($('<p>').text('Deuda ' + dinero(cxp.debt) + ' · pagado ' + dinero(cxp.pagado) + ' · saldo ' + dinero(cxp.saldo) + ' · ' + cxp.base_calculo.name));
                var lista = $('<ul>').appendTo(cuenta);
                cxp.abonos.forEach(function (a) {
                    lista.append($('<li>').text((a.tipo === 'retencion' ? 'Retención ' : 'Nota de crédito ') + a.numero + ' · ' + a.fecha + ' · ' + dinero(a.valor)));
                });
            }
            var vinculos = $('#fp-compra-vinculos').empty();
            if (data.retencion) {
                vinculos.append($('<p>').text('Retención ' + data.retencion.numero + ' · ' + data.retencion.estado));
            }
            if (data.liquidacion) {
                vinculos.append($('<p>').text('Liquidación de compra ' + data.liquidacion.numero + ' · ' + data.liquidacion.estado));
            }
            if (data.documento_importado) {
                vinculos.append($('<p>').append($('<a>').attr('href', data.documento_importado.url).text('Ver el XML importado de esta compra')));
            }
            $('#myModalDetails').modal('show');
        });
    }
};

$(function () {

    try {
        permisos_compras = JSON.parse(document.getElementById('fp-compras-permisos').textContent);
    } catch (e) {
        permisos_compras = {};
    }

    input_date_range = $('input[name="date_range"]');

    input_date_range
        .daterangepicker({
                language: 'auto',
                startDate: new Date(),
                locale: {
                    format: 'YYYY-MM-DD',
                },
                autoApply: true,
            }
        )
        .on('change.daterangepicker apply.daterangepicker', function (ev, picker) {
            purchase.list(false);
        });

    $('.drp-buttons').hide();

    purchase.list(false);

    $('.btnSearchAll').on('click', function () {
        purchase.list(true);
    });

    $('#fp-compras-fecha, #fp-compras-incompletas').on('change', function () {
        purchase.list(false);
    });

    $('#data tbody')
        .off()
        .on('click', 'a[rel="detail"]', function () {
            $('.tooltip').remove();
            var tr = tblPurchase.cell($(this).closest('td, li')).index(),
                row = tblPurchase.row(tr.row).data();
            purchase.detalle(row.id);
        });
});
