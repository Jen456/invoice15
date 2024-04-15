var tblSale;
var input_date_range;
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
                {data: "voucher_number_full"},
                {data: "date_joined"},
                {data: "payment_type.name"},
                {data: "status.name"},
                {data: "subtotal"},
                {data: "total_iva"},
                {data: "total_dscto"},
                {data: "total"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [0, 1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data;
                    }
                },
                {
                    targets: [-7],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data.toUpperCase();
                    }
                },
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
                        if (['authorized', 'authorized_and_sent_by_email'].includes(row.status.id)) {
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
