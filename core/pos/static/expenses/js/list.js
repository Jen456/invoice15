// Gastos sin comprobante (espec-etapa2-compras §6.F): medio de pago («Sin dato» en los anteriores) y referencia.
// Texto escapado con render.text.
var input_date_range;
var expenses = {
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
        $('#data').DataTable({
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
            columns: [
                {data: "id"},
                {data: "type_expense.name", render: $.fn.dataTable.render.text()},
                {data: "date_joined"},
                {data: "valor"},
                {data: "medio_pago.name", render: $.fn.dataTable.render.text()},
                {data: "referencia", render: $.fn.dataTable.render.text()},
                {data: "description", render: $.fn.dataTable.render.text()},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-5],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var id = parseInt(row.id, 10);
                        // Comprobantes de pago del gasto (core/adjuntos).
                        var buttons = '<button type="button" class="btn btn-outline-secondary btn-xs btn-flat mr-1" data-adjuntos-tipo="gasto" data-adjuntos-id="' + parseInt(row.id, 10) + '" title="Comprobantes de pago" aria-label="Comprobantes de pago"><i class="fas fa-paperclip" aria-hidden="true"></i></button>' + ' ';
                        buttons += '<a href="' + pathname + 'update/' + id + '/" data-toggle="tooltip" title="Editar" class="btn btn-warning btn-xs btn-flat"><i class="fas fa-edit"></i></a> ';
                        buttons += '<a href="' + pathname + 'delete/' + id + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                        return buttons;
                    }
                },
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
                var total = json.reduce((a, b) => a + Math.round((b.valor || 0) * 100), 0);
                $('.total').text('$' + (total / 100).toFixed(2));
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
            expenses.list(false);
        });

    $('.drp-buttons').hide();

    expenses.list(false);

    $('.btnSearchAll').on('click', function () {
        expenses.list(true);
    });
});