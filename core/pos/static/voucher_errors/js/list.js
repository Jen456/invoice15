var tblReceiptStates;
var input_date_range;
var select_receipt;
var receipt_states = {
    list: function (all) {
        var parameters = {
            'action': 'search',
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
            'receipt': select_receipt.val()
        };
        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }
        tblReceiptStates = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            order: [[0, 'desc'], [1, 'asc']],
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
                {data: "datetime_joined"},
                {data: "reference"},
                {data: "receipt.name"},
                {data: "stage.name"},
                {data: "environment_type.name"},
                {data: "errors"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-3, -4, -5, -6, -7],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data;
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a class="btn btn-warning btn-xs" rel="errors"><i class="fas fa-exclamation-triangle"></i></a>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a href="' + pathname + 'delete/' + row.id + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                    }
                },
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    formatRow: function (items) {
        // var content = '<div class="card p-3 mt-2"><div class="row"><div class="col-lg-12"><table class="table table-bordered" style="width: 100%;"><thead class="thead-dark"><tr><th style="width: 10%;">Key</th><th style="width: 90%;">Valor</th></tr></thead><tbody>';
        // Object.keys(items.errors).forEach(function (key) {
        //     var item = items.errors[key];
        //     if (typeof item === "object") {
        //         item = JSON.stringify(item);
        //     }
        //     content += '<tr><td>' + key + '</td><td>' + item + '</td></tr>';
        // });
        // content += '</tbody></table></div></div></div>';
        // return content;
        return JSON.stringify(items.errors);
    }
};

$(function () {

    select_receipt = $('select[name="receipt"]');
    input_date_range = $('input[name="date_range"]');

    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es"
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
            receipt_states.list(false);
        });

    $('.drp-buttons').hide();

    receipt_states.list(false);

    $('.btnSearchAll').on('click', function () {
        receipt_states.list(true);
    });

    select_receipt.on('change', function () {
        receipt_states.list(false);
    });

    $('#data tbody')
        .off()
        .on('click', 'a[rel="errors"]', function () {
            var cell = tblReceiptStates.cell($(this).closest('td, li')).index();
            var data = tblReceiptStates.row(cell.row).data();
            var tr = $(this).closest('tr');
            var row = tblReceiptStates.row(tr);
            if (row.child.isShown()) {
                row.child.hide();
                tr.removeClass('shown');
            } else {
                row.child(receipt_states.formatRow(data)).show();
                tr.addClass('shown');
            }
        });
});