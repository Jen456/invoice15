var tblCreditNote;
var input_date_range;
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
                    targets: [-6],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var name = row.status.name;
                        switch (row.status.id) {
                            case "without_authorizing":
                                return '<span class="badge badge-warning badge-pill">' + name + '</span>';
                            case "authorized":
                            case "authorized_and_sent_by_email":
                                return '<span class="badge badge-success badge-pill">' + name + '</span> ';
                            case "sequential_registered_error":
                            case "canceled":
                                return '<span class="badge badge-danger badge-pill">' + name + '</span>';
                        }
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
                        if (row.status.id === 'without_authorizing') {
                            buttons += '<a rel="generate_invoice" class="dropdown-item"><i class="fas fa-clipboard-check"></i> Generar factura electrónica</a>';
                        } else if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id)) {
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
                'content': '¿Estas seguro de generar la factura electrónica?',
                'success': function (request) {
                    alert_sweetalert({
                        'message': 'Factura generada correctamente',
                        'timer': 2000,
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
                        'message': 'Se ha enviado la factura pdf/xml por email',
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
