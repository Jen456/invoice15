var fvSale, fvClient;
var select_client, select_payment_type, select_receipt;
var input_birthdate, input_cash, input_change, input_search_product, input_end_credit, input_sale, input_time_limit, input_date_joined;
var tblSearchProducts, tblProducts;

var sale = {
    detail: {
        subtotal_0: 0.00,
        subtotal_12: 0.00,
        subtotal: 0.00,
        iva: 0.00,
        total_iva: 0.00,
        total_dscto: 0.00,
        total: 0.00,
        cash: 0.00,
        change: 0.00,
        products: [],
        additional_info: [],
    },
    calculateInvoice: function () {
        var tax = this.detail.iva / 100;
        this.detail.products.forEach(function (value, index, array) {
            value.iva = parseFloat(tax);
            value.price_with_vat = value.price_current + (value.price_current * value.iva);
            value.subtotal = value.price_current * value.cant;
            value.total_dscto = value.subtotal * parseFloat((value.dscto / 100));
            value.total_iva = (value.subtotal - value.total_dscto) * value.iva;
            value.total = value.subtotal - value.total_dscto;
        });
        this.detail.subtotal_0 = this.detail.products.filter(value => !value.with_tax).reduce((a, b) => a + (b.total || 0), 0);
        this.detail.subtotal_12 = this.detail.products.filter(value => value.with_tax).reduce((a, b) => a + (b.total || 0), 0);
        this.detail.total_dscto = this.detail.products.reduce((a, b) => a + (b.total_dscto || 0), 0);
        this.detail.subtotal = parseFloat(this.detail.subtotal_0) + parseFloat(this.detail.subtotal_12);
        this.detail.total_iva = this.detail.products.filter(value => value.with_tax).reduce((a, b) => a + (b.total_iva || 0), 0);
        this.detail.total = this.detail.subtotal + this.detail.total_iva;
        this.detail.total = parseFloat(this.detail.total.toFixed(2));

        $('input[name="subtotal_0"]').val(this.detail.subtotal_0.toFixed(2));
        $('input[name="subtotal_12"]').val(this.detail.subtotal_12.toFixed(2));
        $('input[name="iva"]').val(this.detail.iva.toFixed(2));
        $('input[name="total_iva"]').val(this.detail.total_iva.toFixed(2));
        $('input[name="total_dscto"]').val(this.detail.total_dscto.toFixed(2));
        $('input[name="total"]').val(this.detail.total.toFixed(2));
        if (select_payment_type.val() === 'efectivo') {
            input_cash.trigger('change');
        }
    },
    listProducts: function () {
        this.calculateInvoice();
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
                {data: "name"},
                {data: "stock"},
                {data: "cant"},
                {data: "price_current"},
                {data: "total_dscto"},
                {data: "total"},
            ],
            columnDefs: [
                {
                    targets: [-5],
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
                    targets: [-4],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="cant" value="' + row.cant + '">';
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="dscto_unitary" value="' + row.dscto + '">';
                    }
                },
                {
                    targets: [-1, -3],
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
                var tr = $(row).closest('tr');
                var stock = data.inventoried ? data.stock : 1000000;
                tr.find('input[name="cant"]')
                    .TouchSpin({
                        min: 1,
                        max: stock
                    })
                    .on('keypress', function (e) {
                        return validate_text_box({'event': e, 'type': 'numbers'});
                    });

                tr.find('input[name="dscto_unitary"]')
                    .TouchSpin({
                        min: 0.00,
                        max: 100,
                        step: 0.01,
                        decimals: 2,
                        boostat: 5,
                        maxboostedstep: 10,
                        postfix: "0.00"
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
        var index = this.detail.products.findIndex(value => value.code === item.code);
        if (index === -1) {
            this.detail.products.push(item);
        } else {
            var product = this.detail.products[index];
            if ((product.cant + 1 <= product.stock) || !product.inventoried) {
                product.cant += 1;
            }
        }
        this.listProducts();
    },
    searchProductBarcode: function () {
        var code = input_search_product.val();
        $.ajax({
            url: pathname,
            data: {
                'action': 'search_product_code',
                'code': code
            },
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            dataType: 'json',
            success: function (request) {
                if (!request.hasOwnProperty('error')) {
                    if (!$.isEmptyObject(request)) {
                        request.cant = 1;
                        sale.addProduct(request);
                    } else {
                        message_error('Producto no encontrado con el código ' + code);
                    }
                    return false;
                }
                message_error(request.error);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error(errorThrown + ' ' + textStatus);
            },
            complete: function () {
                input_search_product.val('').focus();
            }
        });
    },
    searchVoucherNumber: function () {
        $.ajax({
            url: pathname,
            data: {
                'action': 'search_voucher_number',
                'receipt': select_receipt.val()
            },
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            dataType: 'json',
            success: function (request) {
                if (!request.hasOwnProperty('error')) {
                    $('input[name="voucher_number"]').val(request.voucher_number);
                    return false;
                }
                message_error(request.error);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error(errorThrown + ' ' + textStatus);
            },
            complete: function () {

            }
        });
    },
    setOptionsFields: function (inputs) {
        inputs.forEach(function (value, index, array) {
            if (value.enable) {
                $(input_sale[value.index]).show();
            } else {
                $(input_sale[value.index]).hide();
            }
        });
    },
    listAdditionalInfo: function () {
        tblAdditionalInfo = $('#tblAdditionalInfo').DataTable({
            autoWidth: false,
            destroy: true,
            data: this.detail.additional_info,
            ordering: false,
            lengthChange: false,
            searching: false,
            paginate: false,
            info: false,
            columns: [
                {data: "name"},
                {data: "name"},
                {data: "value"},
            ],
            columnDefs: [
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" placeholder="Ingrese un nombre" autocomplete="off" name="additional_info_name" value="' + row.name + '">';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" placeholder="Ingrese un valor" autocomplete="off" name="additional_info_value" value="' + row.value + '">';
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

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    }
};

document.addEventListener('DOMContentLoaded', function (e) {
    fvClient = FormValidation.formValidation(document.getElementById('frmClient'), {
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
                names: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 2,
                        },
                    }
                },
                dni: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 10
                        },
                        digits: {},
                        callback: {
                            message: 'El número de cedula o ruc es incorrecto',
                            callback: function (input) {
                                return validate_dni_ruc(input.value);
                            },
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fvClient.form.querySelector('[name="dni"]').value,
                                    pattern: 'dni',
                                    action: 'validate_client'
                                };
                            },
                            message: 'El número de cédula ya se encuentra registrado',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                mobile: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 7
                        },
                        digits: {},
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fvClient.form.querySelector('[name="mobile"]').value,
                                    pattern: 'mobile',
                                    action: 'validate_client'
                                };
                            },
                            message: 'El número de teléfono ya se encuentra registrado',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                email: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 5
                        },
                        regexp: {
                            regexp: /^([a-z0-9_\.-]+)@([\da-z\.-]+)\.([a-z\.]{2,6})$/i,
                            message: 'El formato email no es correcto'
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fvClient.form.querySelector('[name="email"]').value,
                                    pattern: 'email',
                                    action: 'validate_client'
                                };
                            },
                            message: 'El email ya se encuentra registrado',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                address: {
                    validators: {
                        stringLength: {
                            min: 4,
                        }
                    }
                },
                image: {
                    validators: {
                        file: {
                            extension: 'jpeg,jpg,png',
                            type: 'image/jpeg,image/png',
                            maxFiles: 1,
                            message: 'Introduce una imagen válida'
                        }
                    }
                },
                birthdate: {
                    validators: {
                        notEmpty: {
                            message: 'La fecha es obligatoria'
                        },
                        date: {
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    },
                },
                identification_type: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un item'
                        }
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
            const iconPlugin = fvClient.getPlugin('icon');
            const iconElement = iconPlugin && iconPlugin.icons.has(e.element) ? iconPlugin.icons.get(e.element) : null;
            iconElement && (iconElement.style.display = 'none');
        })
        .on('core.validator.validated', function (e) {
            if (!e.result.valid) {
                const messages = [].slice.call(fvClient.form.querySelectorAll('[data-field="' + e.field + '"][data-validator]'));
                messages.forEach((messageEle) => {
                    const validator = messageEle.getAttribute('data-validator');
                    messageEle.style.display = validator === e.validator ? 'block' : 'none';
                });
            }
        })
        .on('core.form.valid', function () {
            var params = new FormData(fvClient.form);
            params.append('action', 'create_client');
            var args = {
                'params': params,
                'success': function (request) {
                    select_client.select2('trigger', 'select', {data: request});
                    fvSale.revalidateField('client');
                    $('#myModalClient').modal('hide');
                }
            };
            submit_with_formdata(args);
        });
});

document.addEventListener('DOMContentLoaded', function (e) {
    function validateChange() {
        var cash = parseFloat(input_cash.val());
        if (select_payment_type.val() === 'efectivo') {
            if (cash < sale.detail.total) {
                input_change.val('0.00');
                return {valid: false, message: 'El efectivo debe ser mayor o igual al total a pagar'};
            }
        }
        var change = cash - sale.detail.total;
        input_change.val(change.toFixed(2));
        return {valid: true};
    }

    fvSale = FormValidation.formValidation(document.getElementById('frmForm'), {
            locale: 'es_ES',
            localization: FormValidation.locales.es_ES,
            plugins: {
                trigger: new FormValidation.plugins.Trigger(),
                submitButton: new FormValidation.plugins.SubmitButton(),
                bootstrap: new FormValidation.plugins.Bootstrap(),
                // excluded: new FormValidation.plugins.Excluded(),
                icon: new FormValidation.plugins.Icon({
                    valid: 'fa fa-check',
                    invalid: 'fa fa-times',
                    validating: 'fa fa-refresh',
                }),
            },
            fields: {
                client: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un cliente'
                        },
                    }
                },
                date_joined: {
                    validators: {
                        notEmpty: {
                            enabled: false,
                            message: 'La fecha es obligatoria'
                        },
                        date: {
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    }
                },
                voucher_number: {
                    validators: {
                        notEmpty: {}
                    }
                },
                end_credit: {
                    validators: {
                        notEmpty: {
                            enabled: false,
                            message: 'La fecha es obligatoria'
                        },
                        date: {
                            format: 'YYYY-MM-DD',
                            message: 'La fecha no es válida'
                        }
                    }
                },
                payment_type: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un tipo de pago'
                        },
                    }
                },
                payment_method: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un método de pago'
                        },
                    }
                },
                time_limit: {
                    validators: {
                        notEmpty: {},
                        digits: {}
                    }
                },
                cash: {
                    validators: {
                        notEmpty: {},
                        numeric: {
                            message: 'El valor no es un número',
                            thousandsSeparator: '',
                            decimalSeparator: '.'
                        }
                    }
                },
                change: {
                    validators: {
                        notEmpty: {},
                        callback: {
                            //message: 'El cambio no puede ser negativo',
                            callback: function (input) {
                                return validateChange();
                            }
                        }
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
            const iconPlugin = fvSale.getPlugin('icon');
            const iconElement = iconPlugin && iconPlugin.icons.has(e.element) ? iconPlugin.icons.get(e.element) : null;
            iconElement && (iconElement.style.display = 'none');
        })
        .on('core.validator.validated', function (e) {
            if (!e.result.valid) {
                const messages = [].slice.call(fvSale.form.querySelectorAll('[data-field="' + e.field + '"][data-validator]'));
                messages.forEach((messageEle) => {
                    const validator = messageEle.getAttribute('data-validator');
                    messageEle.style.display = validator === e.validator ? 'block' : 'none';
                });
            }
        })
        .on('core.form.valid', function () {
            if (sale.detail.products.length === 0) {
                message_error('Debe tener al menos un item en el detalle de la venta');
                return false;
            }
            var customer = select_client.select2('data')[0];
            if (select_receipt.val() === '1') {
                if (customer.identification_type.id === '07' && sale.detail.total >= 50.00) {
                    message_error('No se puede facturar un monto de 50 dólares con un cliente consumidor final');
                    return false;
                }
                if (customer.identification_type.id === '07' && select_payment_type.val() === 'credito') {
                    message_error('No se puede facturar a crédito con un cliente consumidor final');
                    return false;
                }
            }
            var list_url = $(fvSale.form).attr('data-url');
            var params = new FormData(fvSale.form);
            ['input_search_product', 'cant', 'price_current', 'dscto_unitary'].forEach(function (value) {
                params.delete(value);
            });
            params.append('products', JSON.stringify(sale.detail.products));
            params.append('additional_info', JSON.stringify(sale.detail.additional_info.filter(value => !$.isEmptyObject(value.name) && !$.isEmptyObject(value.value))));
            var args = {
                'params': params,
                'success': function (request) {
                    dialog_action({
                        'content': '¿Desea Imprimir el Comprobante?',
                        'success': function () {
                            console.log(request);
                            window.open(request.print_url, '_blank');
                            location.href = list_url;
                        },
                        'cancel': function () {
                            location.href = list_url;
                        }
                    });
                }
            };
            submit_with_formdata(args);
        });
});

$(function () {
    input_search_product = $('input[name="search_product"]');
    select_client = $('select[name="client"]');
    select_receipt = $('select[name="receipt"]');
    input_birthdate = $('input[name="birthdate"]');
    input_date_joined = $('input[name="date_joined"]');
    input_end_credit = $('input[name="end_credit"]');
    select_payment_type = $('select[name="payment_type"]');
    input_cash = $('input[name="cash"]');
    input_change = $('input[name="change"]');
    input_sale = $('.input_sale');
    input_time_limit = $('input[name="time_limit"]');

    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es",
    });

    // Product

    input_search_product.autocomplete({
        source: function (request, response) {
            $.ajax({
                url: pathname,
                data: {
                    'action': 'search_product',
                    'term': request.term,
                    'ids': JSON.stringify(sale.getProductsIds()),
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
            if (ui.item.stock === 0 && ui.item.inventoried) {
                message_error('El stock de este producto esta en 0');
                return false;
            }
            ui.item.cant = 1;
            sale.addProduct(ui.item);
            $(this).val('').focus();
        }
    });

    $('.btnClearProducts').on('click', function () {
        input_search_product.val('').focus();
    });

    $('#tblProducts tbody')
        .off()
        .on('change', 'input[name="cant"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            sale.detail.products[tr.row].cant = parseInt($(this).val());
            sale.calculateInvoice();
            $('td:last', tblProducts.row(tr.row).node()).html('$' + sale.detail.products[tr.row].total.toFixed(2));
        })
        .on('change', 'input[name="dscto_unitary"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            sale.detail.products[tr.row].dscto = parseFloat($(this).val());
            sale.calculateInvoice();
            var parent = $(this).closest('.bootstrap-touchspin');
            parent.find('.bootstrap-touchspin-postfix').children().html(sale.detail.products[tr.row].total_dscto.toFixed(2));
            $('td:last', tblProducts.row(tr.row).node()).html('$' + sale.detail.products[tr.row].total.toFixed(2));
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            sale.detail.products.splice(tr.row, 1);
            tblProducts.row(tr.row).remove().draw();
            sale.calculateInvoice();
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
                    'ids': JSON.stringify(sale.getProductsIds()),
                },
                dataSrc: ""
            },
            columns: [
                {data: "code"},
                {data: "short_name"},
                {data: "pvp"},
                {data: "price_promotion"},
                {data: "stock"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-3, -4],
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
                        return '<a rel="add" class="btn btn-success btn-flat btn-xs"><i class="fas fa-plus"></i></a>';
                    }
                }
            ],
            rowCallback: function (row, data, index) {

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
        $('#myModalSearchProducts').modal('show');
    });

    $('#tblSearchProducts tbody')
        .off()
        .on('click', 'a[rel="add"]', function () {
            var row = tblSearchProducts.row($(this).parents('tr')).data();
            row.cant = 1;
            sale.addProduct(row);
            tblSearchProducts.row($(this).parents('tr')).remove().draw();
        });

    $('.btnRemoveAllProducts').on('click', function () {
        if (sale.detail.products.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                sale.detail.products = [];
                sale.listProducts();
            },
            'cancel': function () {

            }
        });
    });

    // Client

    select_client.select2({
        theme: "bootstrap4",
        language: 'es',
        allowClear: true,
        ajax: {
            delay: 250,
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            url: pathname,
            data: function (params) {
                return {
                    term: params.term,
                    action: 'search_client'
                };
            },
            processResults: function (data) {
                return {
                    results: data
                };
            },
        },
        placeholder: 'Ingrese un nombre o número de cedula de un cliente',
        minimumInputLength: 1,
    })
        .on('select2:select', function (e) {
            fvSale.revalidateField('client');
        })
        .on('select2:clear', function (e) {
            fvSale.revalidateField('client');
        });

    $('.btnAddClient').on('click', function () {
        input_birthdate.datetimepicker('date', new Date());
        $('#myModalClient').modal('show');
    });

    $('#myModalClient').on('hidden.bs.modal', function () {
        fvClient.resetForm(true);
    });

    $('input[name="dni"]').on('keypress', function (e) {
        return validate_text_box({'event': e, 'type': 'numbers'});
    });

    $('input[name="mobile"]').on('keypress', function (e) {
        return validate_text_box({'event': e, 'type': 'numbers'});
    });

    input_birthdate.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
    });

    input_birthdate.on('change.datetimepicker', function (e) {
        fvClient.revalidateField('birthdate');
    });

    // Sale

    select_receipt.on('change', function () {
        $('.content-electronic-billing').find('input,select').prop('disabled', $(this).val() !== '01');
        sale.searchVoucherNumber();
    });

    select_payment_type
        .on('change', function () {
            var id = $(this).val();
            switch (id) {
                case "efectivo":
                    sale.setOptionsFields([{'index': 0, 'enable': true}, {'index': 1, 'enable': true}, {'index': 2, 'enable': false}]);
                    fvSale.enableValidator('cash');
                    fvSale.enableValidator('change');
                    fvSale.disableValidator('end_credit');
                    break;
                case "credito":
                    fvSale.disableValidator('cash');
                    fvSale.disableValidator('change');
                    fvSale.enableValidator('end_credit');
                    sale.setOptionsFields([{'index': 0, 'enable': false}, {'index': 1, 'enable': false}, {'index': 2, 'enable': true}]);
                    break;
            }
        });

    input_cash
        .TouchSpin({
            min: 0.00,
            max: 100000000,
            step: 0.01,
            decimals: 2,
            boostat: 5,
            maxboostedstep: 10
        })
        .off('change')
        .on('change touchspin.on.min touchspin.on.max', function () {
            fvSale.revalidateField('cash');
            fvSale.revalidateField('change');
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'decimals'});
        });

    input_date_joined.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
    });

    input_date_joined.on('change.datetimepicker', function (e) {
        fvSale.revalidateField('date_joined');
        input_end_credit.datetimepicker('minDate', e.date);
        input_end_credit.datetimepicker('date', e.date);
    });

    input_end_credit.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
        minDate: new Date()
    });

    input_end_credit.datetimepicker('date', input_end_credit.val());

    input_end_credit.on('change.datetimepicker', function (e) {
        fvSale.revalidateField('end_credit');
    });

    input_time_limit
        .TouchSpin({
            min: 0,
            max: 1000,
            step: 1
        })
        .on('change touchspin.on.min touchspin.on.max', function () {
            fvSale.revalidateField('time_limit');
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    // Barcode

    $(document).on('keypress', function (e) {
        if (e.which === 13) {
            e.preventDefault();
            sale.searchProductBarcode();
        }
    });

    // Additional Info

    $('.btnAdditionalInfo').on('click', function () {
        $('#myModalAdditionalInfo').modal('show');
    });

    $('.btnCreateAdditionalInfo').on('click', function () {
        sale.detail.additional_info.push({'name': '', 'value': ''});
        sale.listAdditionalInfo();
    });

    $('.btnRemoveAdditionalInfo').on('click', function () {
        if (sale.detail.additional_info.length === 0) return false;
        dialog_action({
            'content': '¿Estas seguro de eliminar todos los items de tu detalle?',
            'success': function () {
                sale.detail.additional_info = [];
                sale.listAdditionalInfo();
            },
            'cancel': function () {

            }
        });
    });

    $('#tblAdditionalInfo tbody')
        .off()
        .on('keyup', 'input[name="additional_info_name"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info[tr.row].name = $(this).val();
            console.log(sale.detail.additional_info);
        })
        .on('keyup', 'input[name="additional_info_value"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info[tr.row].value = $(this).val();
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblAdditionalInfo.cell($(this).closest('td, li')).index();
            sale.detail.additional_info.splice(tr.row, 1);
            tblAdditionalInfo.row(tr.row).remove().draw();
        });

    sale.searchVoucherNumber();

    $('i[data-field="client"]').hide();
    $('i[data-field="cash"]').hide();
    $('i[data-field="input_search_product"]').hide();
    $('i[data-field="time_limit"]').hide();
});