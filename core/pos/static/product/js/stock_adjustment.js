var input_search_product;
var tblProducts;
var tblSearchProducts;

var inventory = {
    detail: {
        products: []
    },
    addProduct: function (item) {
        this.detail.products.push(item);
        this.listProducts();
    },
    listProducts: function () {
        tblProducts = $('#tblProducts').DataTable({
            autoWidth: false,
            destroy: true,
            data: this.detail.products,
            ordering: false,
            lengthChange: false,
            searching: false,
            paginate: false,
            columns: [
                {data: "id"},
                {data: "code"},
                {data: "full_name"},
                {data: "stock"},
                {data: "newstock"},
            ],
            columnDefs: [
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="newstock" value="' + row.newstock + '">';
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data;
                    }
                },
                {
                    targets: [0],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a rel="remove" class="btn btn-danger btn-flat btn-xs"><i class="fas fa-times"></i></a>';
                    }
                },
            ],
            rowCallback: function (row, data, index) {
                var tr = $(row).closest('tr');
                tr.find('input[name="newstock"]')
                    .TouchSpin({
                        min: 0,
                        max: 10000000
                    })
                    .on('keypress', function (e) {
                        return validate_text_box({'event': e, 'type': 'numbers'});
                    });
            },
            initComplete: function (settings, json) {

            },
        });
    },
    getProductsIds: function () {
        return this.detail.products.map(value => value.id);
    },
};

$(function () {

    input_search_product = $('input[name="search_product"]');

    input_search_product.autocomplete({
        source: function (request, response) {
            $.ajax({
                url: pathname,
                data: {
                    'action': 'search_product',
                    'term': request.term,
                    'ids': JSON.stringify(inventory.getProductsIds()),
                },
                dataType: "json",
                type: "POST",
                headers: {
                    'X-CSRFToken': csrftoken
                },
                beforeSend: function () {

                },
                success: function (data) {
                    response(data);
                }
            });
        },
        min_length: 3,
        delay: 300,
        select: function (event, ui) {
            event.preventDefault();
            $(this).blur();
            ui.item.newstock = ui.item.stock;
            inventory.addProduct(ui.item);
            $(this).val('').focus();
        }
    });

    $('.btnClearProducts').on('click', function () {
        input_search_product.val('').focus();
    });

    $('#tblProducts tbody')
        .off()
        .on('change', 'input[name="newstock"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            inventory.detail.products[tr.row].newstock = parseInt($(this).val());
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            inventory.detail.products.splice(tr.row, 1);
            tblProducts.row(tr.row).remove().draw();
            $('.tooltip').remove();
        });

    $('.btnSearchProducts').on('click', function () {
        tblSearchProducts = $('#tblSearchProducts').DataTable({
            autoWidth: false,
            destroy: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search_product',
                    'term': input_search_product.val(),
                    'ids': JSON.stringify(inventory.getProductsIds()),
                },
                dataSrc: ""
            },
            columns: [
                {data: "code"},
                {data: "full_name"},
                {data: "stock"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (row.stock > 0) {
                            return '<span class="badge badge-success badge-pill">' + data + '</span>'
                        }
                        return '<span class="badge badge-warning badge-pill">' + data + '</span>'
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<a rel="add" class="btn btn-success btn-flat btn-xs"><i class="fas fa-plus"></i></a>'
                    }
                }
            ],
            rowCallback: function (row, data, index) {
                var tr = $(row).closest('tr');
                if (data.stock === 0) {
                    $(tr).css({'background': '#dc3345', 'color': 'white'});
                }
            },
        });
        $('#myModalSearchProducts').modal('show');
    });

    $('#tblSearchProducts tbody')
        .off()
        .on('click', 'a[rel="add"]', function () {
            var tr = tblSearchProducts.cell($(this).closest('td, li')).index();
            var row = tblSearchProducts.row(tr.row).data();
            row.newstock = row.stock;
            inventory.addProduct(row);
            tblSearchProducts.row(tblSearchProducts.row(tr.row).node()).remove().draw();
        });

    $('.btnRemoveAllProducts').on('click', function () {
        if (inventory.detail.products.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                inventory.detail.products = [];
                inventory.listProducts();
            },
            'cancel': function () {

            }
        });
    });

    inventory.listProducts();

    $('.btnCreate').on('click', function () {
        if (inventory.detail.products.length === 0) {
            message_error('Debe tener al menos un producto en su detalle');
            return false;
        }
        var params = new FormData();
        params.append('action', 'create');
        params.append('products', JSON.stringify(inventory.detail.products));
        var args = {
            'params': params,
            'success': function (request) {
                location.href = $('.btnRefresh').attr('href');
            }
        };
        submit_with_formdata(args);
    });

    $('i[data-field="input_search_product"]').hide();
})