var fv;
var tblProducts, tblSearchProducts;
var input_dscto_massive, input_date_range, input_search_product;

var promotions = {
    detail: {
        products: [],
    },
    calculateDscto: function () {
        this.detail.products.forEach(function (value, index, array) {
            value.total_dscto = value.pvp * (value.dscto / 100);
            var multiplier = 100;
            value.total_dscto = Math.floor(value.total_dscto * multiplier) / multiplier;
            value.price_final = value.pvp - value.total_dscto;
        });
    },
    listProducts: function () {
        this.calculateDscto();
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
                {data: "pvp"},
                {data: "dscto"},
                {data: "total_dscto"},
                {data: "price_final"},
            ],
            columnDefs: [
                {
                    targets: [-3],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="dscto" value="' + row.dscto + '">';
                    }
                },
                {
                    targets: [-1, -2, -4],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
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
                var frm = $(row).closest('tr');

                frm.find('input[name="dscto"]')
                    .TouchSpin({
                        min: 0.01,
                        max: 100,
                        step: 0.01,
                        decimals: 2,
                        boostat: 5,
                        prefix: '%',
                        maxboostedstep: 10
                    })
                    .on('keypress', function (e) {
                        return validate_text_box({'event': e, 'type': 'decimals'});
                    });

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    getProductsIds: function () {
        return this.detail.products.map(value => value.id);
    },
    addProduct: function (item) {
        this.detail.products.push(item);
        this.listProducts();
    },
};

document.addEventListener('DOMContentLoaded', function (e) {
    fv = FormValidation.formValidation(document.getElementById('frmForm'), {
            locale: 'es_ES',
            localization: FormValidation.locales.es_ES,
            plugins: {
                trigger: new FormValidation.plugins.Trigger(),
                submitButton: new FormValidation.plugins.SubmitButton(),
                bootstrap: new FormValidation.plugins.Bootstrap(),
                icon: new FormValidation.plugins.Icon({
                    valid: 'fa fa-check',
                    invalid: 'fa fa-times',
                    validating: 'fa fa-refresh',
                }),
            },
            fields: {
                date_range: {
                    validators: {
                        notEmpty: {},
                    }
                },
            },
        }
    )
        .on('core.element.validated', function (e) {
            if (e.valid) {
                const groupEle = FormValidation.utils.closest(e.element, '.form-group');
                if (groupEle) {
                    FormValidation.utils.classSet(groupEle, {
                        'has-success': false,
                    });
                }
                FormValidation.utils.classSet(e.element, {
                    'is-valid': false,
                });
            }
            const iconPlugin = fv.getPlugin('icon');
            const iconElement = iconPlugin && iconPlugin.icons.has(e.element) ? iconPlugin.icons.get(e.element) : null;
            iconElement && (iconElement.style.display = 'none');
        })
        .on('core.validator.validated', function (e) {
            if (!e.result.valid) {
                const messages = [].slice.call(fv.form.querySelectorAll('[data-field="' + e.field + '"][data-validator]'));
                messages.forEach((messageEle) => {
                    const validator = messageEle.getAttribute('data-validator');
                    messageEle.style.display = validator === e.validator ? 'block' : 'none';
                });
            }
        })
        .on('core.form.valid', function () {
            if (promotions.detail.products.length === 0) {
                message_error('Debe tener al menos un item en el detalle');
                return false;
            }
            var params = new FormData(fv.form);
            params.append('products', JSON.stringify(promotions.detail.products));
            params.append('start_date', input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'));
            params.append('end_date', input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'));
            var args = {
                'params': params,
                'form': fv.form
            };
            submit_with_formdata(args);
        });
});

$(function () {

    input_search_product = $('input[name="search_product"]');
    input_dscto_massive = $('input[name="dscto_massive"]');
    input_date_range = $('input[name="date_range"]');

    input_date_range
        .daterangepicker({
            language: 'auto',
            locale: {
                format: 'YYYY-MM-DD',
            },
        })
        .on('hide.daterangepicker', function (ev, picker) {
            fv.revalidateField('date_range');
        });

    $('.drp-buttons').hide();

    // Products

    input_search_product.autocomplete({
        source: function (request, response) {
            $.ajax({
                url: pathname,
                data: {
                    'action': 'search_product',
                    'term': request.term,
                    'ids': JSON.stringify(promotions.getProductsIds()),
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
            ui.item.dscto = 0.00;
            promotions.addProduct(ui.item);
            $(this).val('').focus();
        }
    });

    $('.btnClearProducts').on('click', function () {
        input_search_product.val('').focus();
    });

    $('#tblProducts tbody')
        .off()
        .on('change', 'input[name="dscto"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            promotions.detail.products[tr.row].dscto = parseFloat($(this).val());
            promotions.calculateDscto();
            $('td:eq(-2)', tblProducts.row(tr.row).node()).html('$' + promotions.detail.products[tr.row].total_dscto.toFixed(2));
            $('td:eq(-1)', tblProducts.row(tr.row).node()).html('$' + promotions.detail.products[tr.row].price_final.toFixed(2));
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            promotions.detail.products.splice(tr.row, 1);
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
                    'ids': JSON.stringify(promotions.getProductsIds()),
                },
                dataSrc: ""
            },
            columns: [
                {data: "code"},
                {data: "full_name"},
                {data: "pvp"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var content = '<div class="checkbox">';
                        content += '<label><input type="checkbox" class="form-control-checkbox" name="choose" value=""></label>';
                        content += '</div>';
                        return content;
                    }
                }
            ],
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
        $('input[name="chooseallproducts"]').prop('checked', false);
        $('#myModalSearchProducts').modal('show');
    });

    $('#myModalSearchProducts').on('hide.bs.modal', function () {
        var products = tblSearchProducts.rows().data().toArray().filter(function (item, key) {
            return item.choose;
        });
        var dscto_massive = parseFloat(input_dscto_massive.val());
        products.forEach(function (value, index, array) {
            value.dscto = dscto_massive;
            promotions.detail.products.push(value);
        });
        promotions.listProducts();
    })

    $('#tblSearchProducts tbody')
        .off()
        .on('click', 'a[rel="add"]', function () {
            var row = tblSearchProducts.row($(this).parents('tr')).data();
            row.dscto = 0.01;
            promotions.addProduct(row);
            tblSearchProducts.row($(this).parents('tr')).remove().draw();
        })
        .on('change', 'input[name="choose"]', function () {
            var row = tblSearchProducts.row($(this).parents('tr')).data();
            row.choose = this.checked;
        });

    $('.btnRemoveAllProducts').on('click', function () {
        if (promotions.detail.products.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                promotions.detail.products = [];
                promotions.listProducts();
            },
            'cancel': function () {

            }
        });
    });

    input_dscto_massive
        .TouchSpin({
            min: 0.01,
            max: 1000000,
            step: 0.01,
            decimals: 2,
            boostat: 5,
            maxboostedstep: 10,
            prefix: '%'
        })
        .on('change touchspin.on.min touchspin.on.max', function () {
            var dscto_massive = parseFloat($(this).val());
            promotions.detail.products = [];
            tblProducts.rows().data().toArray().forEach(function (value, index, array) {
                value.dscto = dscto_massive;
                promotions.detail.products.push(value);
            });
            promotions.listProducts();
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'decimals'});
        });

    $('input[name="chooseallproducts"]')
        .on('change', function () {
            var state = this.checked;
            var cells = tblSearchProducts.cells().nodes();
            $(cells).find('input[name="choose"]').prop('checked', state).change();
            tblSearchProducts.rows().data().toArray().forEach(function (value, index, array) {
                value.choose = state;
            });
        });

    $('i[data-field="input_search_product"]').hide();
    $('i[data-field="dscto_massive"]').hide();
});
