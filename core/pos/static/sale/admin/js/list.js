var tblSale;
var input_date_range;
var fpaPermisos = null;

// Etapa 2 (O2): escape del texto que se inserta en HTML y permisos del rol (json_script de la plantilla).
function fpaTexto(x) {
    return $('<div>').text(x === null || x === undefined ? '' : String(x)).html();
}

function fpaPermiso(codigo) {
    if (fpaPermisos === null) {
        var nodo = document.getElementById('fpa-permisos');
        fpaPermisos = nodo ? JSON.parse(nodo.textContent) : {};
    }
    return fpaPermisos[codigo] === true;
}

function fpaFechaCorta(iso) {
    var partes = String(iso || '').split('-');
    return partes.length === 3 ? partes[2] + '/' + partes[1] + '/' + partes[0] : '';
}

function fpaConsumidorFinal(row) {
    return row.client.identification_type.id === '07' || row.client.dni === '9999999999999';
}

function fpaAnulableEnSri(row) {
    // Desde el 01/01/2026 el SRI no permite anular facturas a consumidor final (el servidor lo vuelve a comprobar).
    var emision = row.emission_date || row.authorization_date || row.date_joined;
    return !fpaConsumidorFinal(row) || emision < '2026-01-01';
}
var sale = {
    list: function (all) {
        var parameters = {
            'action': 'search',
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
        };
        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }
        tblSale = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: parameters,
                dataSrc: ""
            },
            order: [[0, "desc"], [5, "desc"]],
            columns: [
                {data: "id"},
                {data: "voucher_number_full"},
                {data: "date_joined"},
                {data: "client.user.names"},
                {data: "receipt.name"},
                {data: "status.name"},
                {data: "subtotal"},
                {data: "total_iva"},
                {data: "total_dscto"},
                {data: "total"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [1, 2, 3],
                    render: $.fn.dataTable.render.text()
                },
                {
                    targets: [-6],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var name = fpaTexto(row.status.name);
                        if (row.anulado_sri) {
                            return '<span class="badge badge-secondary badge-pill">Anulada en el SRI (' + fpaTexto(fpaFechaCorta(row.anulado_sri.fecha)) + ')</span>';
                        }
                        if (row.receipt.voucher_type.id === '08') {
                            return '<span class="badge badge-secondary badge-pill">Sin facturación</span>';
                        }
                        switch (row.status.id) {
                            case "without_authorizing":
                                return '<span class="badge badge-warning badge-pill">' + name + '</span>';
                            case "in_process":
                                return '<span class="badge badge-info badge-pill">' + name + '</span>';
                            case "returned":
                            case "not_authorized":
                                return '<span class="badge badge-danger badge-pill">' + name + '</span>';
                            case "authorized":
                            case "authorized_and_sent_by_email":
                                return '<span class="badge badge-success badge-pill">' + name + '</span>';
                            case "sequential_registered_error":
                            case "canceled":
                                return '<span class="badge badge-danger badge-pill">' + name + '</span>';
                        }
                    }
                },
                {
                    targets: [-7],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return fpaTexto(String(data).toUpperCase());
                    }
                },
                {
                    targets: [-2, -3, -4, -5],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var buttons = '<div class="btn-group" role="group">';
                        buttons += '<div class="btn-group" role="group">';
                        buttons += '<button type="button" class="btn btn-secondary btn-sm dropdown-toggle" data-toggle="dropdown" aria-expanded="false"><i class="fas fa-list"></i> Opciones</button>';
                        buttons += '<div class="dropdown-menu dropdown-menu-right">';
                        buttons += '<a class="dropdown-item" rel="detail"><i class="fas fa-folder-open"></i> Detalle de productos</a>';
                        // Comprobantes de pago de la factura (core/adjuntos): transferencia, depósito o voucher del cobro de contado.
                        buttons += '<a class="dropdown-item" data-adjuntos-tipo="venta" data-adjuntos-id="' + parseInt(row.id, 10) + '"><i class="fas fa-paperclip"></i> Comprobantes de pago</a>';
                        buttons += '<a target="_blank" href="' + pathname + 'print/invoice/' + row.id + '/" class="dropdown-item"><i class="fas fa-ticket-alt"></i> Imprimir factura ticket</a> ';
                        // RIDE A4 (versión completa): existe desde que el SRI autoriza la factura (también si luego se anuló).
                        if (row.receipt.voucher_type.id === '01') {
                            if (['authorized', 'authorized_and_sent_by_email', 'canceled'].includes(row.status.id)) {
                                buttons += '<a target="_blank" href="' + pathname + 'print/a4/' + row.id + '/" class="dropdown-item"><i class="fa-solid fa-file-pdf"></i> Imprimir factura A4' + (row.status.id === 'canceled' ? ' (anulada)' : '') + '</a>';
                            } else {
                                buttons += '<span class="dropdown-item disabled" aria-disabled="true"><i class="fa-solid fa-file-pdf"></i> Factura A4: disponible cuando el SRI la autorice</span>';
                            }
                        }
                        if (row.status.id === 'in_process') {
                            buttons += '<a rel="generate_invoice" class="dropdown-item"><i class="fas fa-sync-alt"></i> Consultar autorización en el SRI</a>';
                        } else if (['without_authorizing', 'returned', 'not_authorized'].includes(row.status.id) && row.receipt.voucher_type.id === '01') {
                            buttons += '<a rel="generate_invoice" class="dropdown-item"><i class="fas fa-clipboard-check"></i> Enviar al SRI</a>';
                        } else if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id) && row.anulado_sri) {
                            // Etapa 2 (O2): anulada en el SRI: sin correo, sin NC/ND/guía ni retención recibida.
                            buttons += '<a href="' + row.xml_authorized + '" target="_blank" class="dropdown-item"><i class="fas fa-file-code"></i> Descargar xml</a>';
                        } else if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id)) {
                            buttons += '<a rel="send_invoice_by_email" class="dropdown-item"><i class="fas fa-envelope"></i> Enviar comprobantes por email</a>';
                            buttons += '<a href="' + row.xml_authorized + '" target="_blank" class="dropdown-item"><i class="fas fa-file-code"></i> Descargar xml</a>';
                            if (row.client.identification_type.id !== '07' && row.receipt.voucher_type.id === '01') {
                                buttons += '<a rel="create_credit_note" class="dropdown-item"><i class="fas fa-minus-circle"></i> Crear nota de credito</a>';
                                // Nota de débito (intereses, gastos de cobranza) sobre la factura autorizada (core/comprobantes).
                                buttons += '<a href="/comprobantes/notas-debito/nueva/' + row.id + '/" class="dropdown-item"><i class="fas fa-plus-circle"></i> Crear nota de débito</a>';
                                // Guía de remisión del traslado de lo vendido (core/comprobantes).
                                buttons += '<a href="/comprobantes/guias/nueva/' + row.id + '/" class="dropdown-item fp-guia-opcion"><i class="fas fa-truck" aria-hidden="true"></i> Crear guía de remisión</a>';
                            }
                        }
                        // Etapa 2 (O2): retención recibida y marca «Anulado en el SRI» (autorizada o cubierta por NC, sin anular).
                        if (!row.anulado_sri && row.receipt.voucher_type.id === '01'
                            && ['authorized', 'authorized_and_sent_by_email', 'canceled'].includes(row.status.id)) {
                            var id = parseInt(row.id, 10);
                            if (fpaPermiso('add_retencionrecibida') && !fpaConsumidorFinal(row)) {
                                buttons += '<a href="/comprobantes/retenciones-recibidas/add/' + id + '/" class="dropdown-item"><i class="fas fa-hand-holding-usd"></i> Registrar retención recibida</a>';
                            }
                            if (fpaPermiso('change_anulado_sri_sale') && fpaAnulableEnSri(row)) {
                                buttons += '<a href="/comprobantes/anulados/factura/' + id + '/update/" class="dropdown-item"><i class="fas fa-ban"></i> Marcar como anulada en el SRI</a>';
                            }
                        }
                        buttons += '</div></div></div>';
                        return buttons;
                    }
                },
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                // $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    }
}

$(function () {

    input_date_range = $('input[name="date_range"]');

    $('#data tbody')
        .off()
        .on('click', 'a[rel="detail"]', function () {
            $('.tooltip').remove();
            var tr = tblSale.cell($(this).closest('td, li')).index();
            var row = tblSale.row(tr.row).data();
            $('#tblProducts').DataTable({
                autoWidth: false,
                destroy: true,
                ajax: {
                    url: pathname,
                    type: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    },
                    data: {
                        'action': 'search_detail_products',
                        'id': row.id
                    },
                    dataSrc: ""
                },
                columns: [
                    {data: "product.short_name"},
                    {data: "price"},
                    {data: "cant"},
                    {data: "total_dscto"},
                    {data: "total"},
                ],
                columnDefs: [
                    {
                        targets: [-1, -2, -4],
                        class: 'text-center',
                        render: function (data, type, row) {
                            return '$' + data.toFixed(2);
                        }
                    },
                    {
                        targets: [-3],
                        class: 'text-center',
                        render: function (data, type, row) {
                            return data;
                        }
                    }
                ],
                initComplete: function (settings, json) {
                    $(this).wrap('<div class="dataTables_scroll"><div/>');
                }
            });
            $('#myModalDetails').modal('show');
        })
        .on('click', 'a[rel="generate_invoice"]', function () {
            $('.tooltip').remove();
            var tr = tblSale.cell($(this).closest('td, li')).index();
            var row = tblSale.row(tr.row).data();
            var params = new FormData();
            params.append('action', 'generate_invoice');
            params.append('id', row.id);
            var args = {
                'params': params,
                'content': row.status.id === 'in_process' ? '¿Consultar en el SRI la autorización de esta factura?' : '¿Enviar esta factura al SRI?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': request.mensaje || 'Factura autorizada por el SRI',
                        'timer': request.en_proceso ? 9000 : 2500,
                        'callback': function () {
                            tblSale.ajax.reload();
                        }
                    })
                }
            };
            submit_with_formdata(args);
        })
        .on('click', 'a[rel="send_invoice_by_email"]', function () {
            $('.tooltip').remove();
            var tr = tblSale.cell($(this).closest('td, li')).index();
            var row = tblSale.row(tr.row).data();
            var params = new FormData();
            params.append('action', 'send_invoice_by_email');
            params.append('id', row.id);
            var args = {
                'params': params,
                'content': '¿Estas seguro de enviar la factura pdf/xml por email?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': request.mensaje || 'Se envió la factura (PDF y XML) por correo',
                        'timer': 2000,
                        'callback': function () {
                            tblSale.ajax.reload();
                        }
                    })
                }
            };
            submit_with_formdata(args);
        })
        .on('click', 'a[rel="create_credit_note"]', function () {
            $('.tooltip').remove();
            var tr = tblSale.cell($(this).closest('td, li')).index();
            var row = tblSale.row(tr.row).data();
            var params = new FormData();
            params.append('action', 'create_credit_note');
            params.append('id', row.id);
            var args = {
                'params': params,
                'content': '¿Estas seguro de generar la nota de credito?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': request.mensaje || 'Nota de crédito autorizada por el SRI',
                        'timer': request.en_proceso ? 9000 : 2500,
                        'callback': function () {
                            tblSale.ajax.reload();
                        }
                    })
                }
            };
            submit_with_formdata(args);
        });

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
            sale.list(false);
        });

    $('.drp-buttons').hide();

    sale.list(false);

    $('.btnSearchAll').on('click', function () {
        sale.list(true);
    });
});
