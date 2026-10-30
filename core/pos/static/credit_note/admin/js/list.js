var tblCreditNote;
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
var credit_note = {
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
        tblCreditNote = $('#data').DataTable({
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
            order: [[0, "desc"], [1, "desc"]],
            columns: [
                {data: "id"},
                {data: "voucher_number_full"},
                {data: "date_joined"},
                {data: "sale.voucher_number"},
                {data: "sale.client.user.names"},
                {data: "status.name"},
                {data: "subtotal"},
                {data: "total_iva"},
                {data: "total_dscto"},
                {data: "total"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [1, 2, 3, 4],
                    render: $.fn.dataTable.render.text()
                },
                {
                    targets: [-6],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var name = fpaTexto(row.status.name);
                        // Etapa 2 (O2): ajuste de la cuenta por cobrar, saldo a favor y marca de anulada.
                        var cxc = '';
                        if (row.cxc_ajuste) {
                            cxc = '<br><small class="text-muted">Cuenta por cobrar: ' + fpaTexto(row.cxc_ajuste.name) + '</small>';
                        }
                        if (row.excedente_cxc && row.excedente_cxc !== '0.00') {
                            cxc += '<br><small class="text-warning">Saldo a favor del cliente: $' + fpaTexto(row.excedente_cxc) + '</small>';
                        }
                        if (row.anulado_sri) {
                            return '<span class="badge badge-secondary badge-pill">Anulada en el SRI (' + fpaTexto(fpaFechaCorta(row.anulado_sri.fecha)) + ')</span>' + cxc;
                        }
                        switch (row.status.id) {
                            case "without_authorizing":
                                return '<span class="badge badge-warning badge-pill">' + name + '</span>' + cxc;
                            case "in_process":
                                return '<span class="badge badge-info badge-pill">' + name + '</span>' + cxc;
                            case "returned":
                            case "not_authorized":
                                return '<span class="badge badge-danger badge-pill">' + name + '</span>' + cxc;
                            case "authorized":
                            case "authorized_and_sent_by_email":
                                return '<span class="badge badge-success badge-pill">' + name + '</span> ' + cxc;
                            case "sequential_registered_error":
                            case "canceled":
                                return '<span class="badge badge-danger badge-pill">' + name + '</span>' + cxc;
                        }
                        return name + cxc;
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
                        if (row.status.id === 'in_process') {
                            buttons += '<a rel="generate_invoice" class="dropdown-item"><i class="fas fa-sync-alt"></i> Consultar autorización en el SRI</a>';
                        } else if (['without_authorizing', 'returned', 'not_authorized'].includes(row.status.id)) {
                            buttons += '<a rel="generate_invoice" class="dropdown-item"><i class="fas fa-clipboard-check"></i> Enviar al SRI</a>';
                        } else if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id) && row.anulado_sri) {
                            // Etapa 2 (O2): anulada en el SRI: sin correo; los documentos siguen disponibles.
                            buttons += '<a href="' + row.pdf_authorized + '" target="_blank" class="dropdown-item"><i class="fa-solid fa-file-pdf"></i> Imprimir pdf</a>';
                            buttons += '<a href="' + row.xml_authorized + '" target="_blank" class="dropdown-item"><i class="fas fa-file-code"></i> Descargar xml</a>';
                        } else if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id)) {
                            if (fpaPermiso('change_anulado_sri_creditnote')) {
                                buttons += '<a href="/comprobantes/anulados/nota-credito/' + parseInt(row.id, 10) + '/update/" class="dropdown-item"><i class="fas fa-ban"></i> Marcar como anulada en el SRI</a>';
                            }
                            buttons += '<a rel="send_invoice_by_email" class="dropdown-item"><i class="fas fa-envelope"></i> Enviar comprobantes por email</a>';
                            buttons += '<a href="' + row.pdf_authorized + '" target="_blank" class="dropdown-item"><i class="fa-solid fa-file-pdf"></i> Imprimir pdf</a>';
                            buttons += '<a href="' + row.xml_authorized + '" target="_blank" class="dropdown-item"><i class="fas fa-file-code"></i> Descargar xml</a>';
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
                var total = json.reduce((a, b) => a + (b.total || 0), 0);
                $('.total').html('$' + total.toFixed(2));
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
            var tr = tblCreditNote.cell($(this).closest('td, li')).index();
            var row = tblCreditNote.row(tr.row).data();
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
                    {data: "price_with_vat"},
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
            var tr = tblCreditNote.cell($(this).closest('td, li')).index();
            var row = tblCreditNote.row(tr.row).data();
            var params = new FormData();
            params.append('action', 'generate_invoice');
            params.append('id', row.id);
            var args = {
                'params': params,
                'content': row.status.id === 'in_process' ? '¿Consultar en el SRI la autorización de esta nota de crédito?' : '¿Enviar esta nota de crédito al SRI?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': request.mensaje || 'Nota de crédito autorizada por el SRI',
                        'timer': request.en_proceso ? 9000 : 2500,
                        'callback': function () {
                            tblCreditNote.ajax.reload();
                        }
                    })
                }
            };
            submit_with_formdata(args);
        })
        .on('click', 'a[rel="send_invoice_by_email"]', function () {
            $('.tooltip').remove();
            var tr = tblCreditNote.cell($(this).closest('td, li')).index();
            var row = tblCreditNote.row(tr.row).data();
            var params = new FormData();
            params.append('action', 'send_invoice_by_email');
            params.append('id', row.id);
            var args = {
                'params': params,
                'content': '¿Estas seguro de enviar la factura pdf/xml por email?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': request.mensaje || 'Se envió la nota de crédito (PDF y XML) por correo',
                        'timer': 2000,
                        'callback': function () {
                            tblCreditNote.ajax.reload();
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
        .on('apply.daterangepicker', function (ev, picker) {
            credit_note.list(false);
        });

    $('.drp-buttons').hide();

    credit_note.list(false);

    $('.btnSearchAll').on('click', function () {
        credit_note.list(true);
    });
});
