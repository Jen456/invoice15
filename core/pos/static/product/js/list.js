var tblProducts;
var product = {
    list: function () {
        tblProducts = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search'
                },
                dataSrc: ""
            },
            columns: [
                {data: "id"},
                {data: "name"},
                {data: "code"},
                {data: "category.name"},
                {data: "inventoried"},
                {data: "image"},
                {data: "barcode"},
                {data: "price"},
                {data: "pvp"},
                {data: "price_promotion"},
                {data: "stock"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-8],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (row.inventoried) {
                            return 'Si';
                        }
                        return 'No';
                    }
                },
                {
                    targets: [-7],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a rel="image" class="btn btn-secondary btn-xs btn-flat"><i class="fas fa-file-image"></i></a>';
                    }
                },
                {
                    targets: [-6],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a rel="barcode" class="btn btn-success btn-xs btn-flat"><i class="fas fa-barcode"></i></a>';
                    }
                },
                {
                    targets: [-4, -5, -3],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (row.inventoried) {
                            if (row.stock > 0) {
                                return '<span class="badge badge-success badge-pill">' + row.stock + '</span>';
                            }
                            return '<span class="badge badge-danger badge-pill">' + row.stock + '</span>';
                        }
                        return '<span class="badge badge-secondary badge-pill">Sin stock</span>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var buttons = '<a href="' + pathname + 'update/' + row.id + '/" data-toggle="tooltip" title="Editar" class="btn btn-warning btn-xs btn-flat"><i class="fas fa-edit"></i></a> ';
                        buttons += '<a href="' + pathname + 'delete/' + row.id + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                        return buttons;
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
    }
};

$(function () {
    product.list();

    $('#data').addClass('table-sm');

    $('#data tbody')
        .off()
        .on('click', 'a[rel="image"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            var data = tblProducts.row(tr.row).data();
            load_image({'url': data.image});
        })
        .on('click', 'a[rel="barcode"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            var data = tblProducts.row(tr.row).data();
            load_image({'url': data.barcode});
        });
})