var tblPaymentsCtasCollect, tblCtasCollect;

// Etapa 2 (O2): escapa el texto que se inserta en HTML armado a mano.
function fpaTexto(x) {
    return $('<div>').text(x === null || x === undefined ? '' : String(x)).html();
}
var date_current;
var input_date_range;
var ctas_collect = {
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
        tblCtasCollect = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: parameters,
                dataSrc: ""
            },
            columns: [
                {data: "documento.numero"},
                {data: "sale.client.user.names"},
                {data: "date_joined"},
                {data: "end_date"},
                {data: "debt"},
                {data: "saldo"},
                {data: "estado.id"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    // Etapa 2 (O2): número del documento (factura o «ND 001-002-…»), escapado.
                    targets: [0],
                    render: function (data, type, row) {
                        var numero = fpaTexto(row.documento.numero);
                        return row.documento.tipo === 'nota_debito' ? 'ND ' + numero : numero;
                    }
                },
                {
                    targets: [1],
                    class: 'text-center',
                    render: $.fn.dataTable.render.text()
                },
                {
                    targets: [-6, -5],
                    class: 'text-center',
                    render: $.fn.dataTable.render.text()
                },
                {
                    targets: [-3, -4],
                    orderable: false,
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-2],
                    orderable: false,
                    class: 'text-center',
                    render: function (data, type, row) {
                        var clases = {'pendiente': 'badge-danger', 'pagada': 'badge-success', 'anulada': 'badge-secondary'};
                        return '<span class="badge ' + (clases[row.estado.id] || 'badge-light') + ' badge-pill">' + fpaTexto(row.estado.name) + '</span>';
                    }
                },
                {
                    targets: [-1],
                    orderable: false,
                    class: 'text-center',
                    render: function (data, type, row) {
                        var buttons = '<a rel="payments" data-toggle="tooltip" title="Abonos" class="btn bg-blue btn-xs btn-flat"><i class="fas fa-dollar-sign"></i></a> ';
                        buttons += '<a href="' + pathname + 'delete/' + parseInt(row.id, 10) + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                        return buttons;
                    }
                },
            ],
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
                var total = json.reduce((a, b) => a + (b.saldo || 0), 0);
                $('.total').html('$' + total.toFixed(2));
            }
        });
    }
};

$(function () {

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
            ctas_collect.list(false);
        });

    $('.drp-buttons').hide();

    ctas_collect.list(false);

    $('.btnSearchAll').on('click', function () {
        ctas_collect.list(true);
    });

    $('#data tbody')
        .off()
        .on('click', 'a[rel="payments"]', function () {
            $('.tooltip').remove();
            var tr = tblCtasCollect.cell($(this).closest('td, li')).index(),
                row = tblCtasCollect.row(tr.row).data();
            tblPaymentsCtasCollect = $('#tblPayments').DataTable({
                autoWidth: false,
                destroy: true,
                searching: false,
                ajax: {
                    url: pathname,
                    type: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    },
                    data: function (d) {
                        d.action = 'search_pays';
                        d.id = row.id;
                    },
                    dataSrc: ""
                },
                columns: [
                    {data: "index"},
                    {data: "date_joined"},
                    {data: "tipo.name"},
                    {data: "medio_pago.name"},
                    {data: "referencia"},
                    {data: "valor_texto"},
                    {data: "description"},
                    {data: "id"},
                ],
                columnDefs: [
                    {
                        // Etapa 2 (O2): todo texto de terceros va escapado.
                        targets: [1, 2, 3, 4, 6],
                        render: $.fn.dataTable.render.text()
                    },
                    {
                        targets: [-3],
                        class: 'text-center',
                        render: function (data, type, row) {
                            return '$' + fpaTexto(data);
                        }
                    },
                    {
                        targets: [-1],
                        class: 'text-center',
                        render: function (data, type, row) {
                            if (row.anulado) {
                                return '<span class="badge badge-secondary">Anulado</span>';
                            }
                            if (row.tipo.id !== 'cobro') {
                                return '';
                            }
                            return '<a rel="delete" class="btn btn-danger btn-xs btn-flat" title="Eliminar cobro"><i class="fas fa-times"></i></a>';
                        }
                    }
                ],
                rowCallback: function (row, data, index) {
                    if (data.anulado) {
                        $(row).css('text-decoration', 'line-through').addClass('text-muted');
                    }
                },
                initComplete: function (settings, json) {
                    $(this).wrap('<div class="dataTables_scroll"><div/>');
                }
            });
            $('#myModalPayments').modal('show');
        });

    $('#tblPayments tbody')
        .off()
        .on('click', 'a[rel="delete"]', function () {
            $('.tooltip').remove();
            var tr = tblPaymentsCtasCollect.cell($(this).closest('td, li')).index(),
                row = tblPaymentsCtasCollect.row(tr.row).data();
            var params = new FormData();
            params.append('id', row.id);
            params.append('action', 'delete_pay');
            var args = {
                'params': params,
                'content': '¿Eliminar este cobro? Queda registrado en la auditoría.',
                'success': function (request) {
                    tblPaymentsCtasCollect.ajax.reload();
                }
            };
            submit_with_formdata(args);
        });

    $('#myModalPayments').on('hidden.bs.modal', function () {
        tblCtasCollect.ajax.reload();
    });
});
