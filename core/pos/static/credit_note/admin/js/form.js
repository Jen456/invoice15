var fv;
var select_sale;
var input_date_joined;
var tblProducts;

var credit_note = {
    detail: {
        subtotal_0: 0.00,
        subtotal_12: 0.00,
        subtotal: 0.00,
        iva: 0.00,
        total_iva: 0.00,
        total_dscto: 0.00,
        total: 0.00,
        products: [],
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
                {data: "product.short_name"},
                {data: "cant"},
                {data: "quantity"},
                {data: "price"},
                {data: "total_dscto"},
                {data: "total"},
            ],
            columnDefs: [
                {
                    targets: [0],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<div class="form-check"><label class="form-check-label"><input type="checkbox" name="state" class="form-control-checkbox" value=""></label></div>';
                    }
                },
                {
                    targets: [-4],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="quantity" value="' + row.quantity + '">';
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
                }
            ],
            rowCallback: function (row, data, index) {
                var tr = $(row).closest('tr');
                tr.find('input[name="quantity"]')
                    .TouchSpin({
                        min: 1,
                        max: data.cant
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

                tr.find('input[name="quantity"]').prop('disabled', data.state === 0);
                tr.find('input[name="dscto_unitary"]').prop('disabled', data.state === 0);

            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    calculateInvoice: function () {
        var tax = this.detail.iva / 100;
        var products = this.detail.products.filter(value => value.state === 1);
        products.forEach(function (value, index, array) {
            value.iva = parseFloat(tax);
            value.price_with_vat = value.price + (value.price * value.iva);
            value.subtotal = value.price * value.quantity;
            value.total_dscto = value.subtotal * parseFloat((value.dscto / 100));
            value.total_iva = (value.subtotal - value.total_dscto) * value.iva;
            value.total = value.subtotal - value.total_dscto;
        });
        this.detail.subtotal_0 = products.filter(value => !value.product.with_tax).reduce((a, b) => a + (b.total || 0), 0);
        this.detail.subtotal_12 = products.filter(value => value.product.with_tax).reduce((a, b) => a + (b.total || 0), 0);
        this.detail.total_dscto = this.detail.products.reduce((a, b) => a + (b.total_dscto || 0), 0);
        this.detail.subtotal = parseFloat(this.detail.subtotal_0) + parseFloat(this.detail.subtotal_12);
        this.detail.total_iva = products.filter(value => value.product.with_tax).reduce((a, b) => a + (b.total_iva || 0), 0);
        this.detail.total = this.detail.subtotal + this.detail.total_iva;
        this.detail.total = parseFloat(this.detail.total.toFixed(2));

        $('input[name="subtotal_0"]').val(this.detail.subtotal_0.toFixed(2));
        $('input[name="subtotal_12"]').val(this.detail.subtotal_12.toFixed(2));
        $('input[name="iva"]').val(this.detail.iva.toFixed(2));
        $('input[name="total_iva"]').val(this.detail.total_iva.toFixed(2));
        $('input[name="total_dscto"]').val(this.detail.total_dscto.toFixed(2));
        $('input[name="total"]').val(this.detail.total.toFixed(2));
    }
};

document.addEventListener('DOMContentLoaded', function (e) {
    fv = FormValidation.formValidation(document.getElementById('frmForm'), {
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
                sale: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione una venta'
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
                motive: {
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
            if (credit_note.detail.products.filter(value => value.state === 1).length === 0) {
                message_error('Debe tener al menos un item activo en el detalle de la nota de credito');
                return false;
            }
            var params = new FormData(fv.form);
            ['quantity', 'dscto_unitary'].forEach(function (value) {
                params.delete(value)
            });
            params.append('products', JSON.stringify(credit_note.detail.products));
            var args = {
                'params': params,
                'form': fv.form
            };
            submit_with_formdata(args);
        });
});

$(function () {
    select_sale = $('select[name="sale"]');
    input_date_joined = $('input[name="date_joined"]');

    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es",
    });

    // Form

    $('input[name="chk-select-all"]').on('change', function () {
        var checked = this.checked;
        if (tblProducts) {
            var cells = tblProducts.cells().nodes();
            $(cells).find('input[name="state"]').prop('checked', checked).trigger('change');
        }
    });

    select_sale.select2({
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
                    action: 'search_sale'
                };
            },
            processResults: function (data) {
                return {
                    results: data
                };
            },
        },
        placeholder: 'Ingrese un número de factura o nombre de un cliente',
        minimumInputLength: 1,
    })
        .on('select2:select', function (e) {
            var object = e.params.data;
            credit_note.detail.products = object.detail;
            credit_note.listProducts();
            input_date_joined.datetimepicker('minDate', object.date_joined);
            input_date_joined.datetimepicker('date', object.date_joined);
            $('input[name="chk-select-all"]').prop('checked', 'checked').trigger('change');
            fv.revalidateField('sale');
        })
        .on('select2:clear', function (e) {
            fv.revalidateField('sale');
            credit_note.detail.products = [];
            credit_note.listProducts();
            $('input[name="chk-select-all"]').prop('checked', '');
        });

    input_date_joined.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
    });

    input_date_joined.datetimepicker('date', input_date_joined.val());

    input_date_joined.on('change.datetimepicker', function (e) {
        fv.revalidateField('date_joined');
    });

    // Product

    $('#tblProducts tbody')
        .off()
        .on('change', 'input[name="state"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            credit_note.detail.products[tr.row].state = this.checked ? 1 : 0;
            $('td', tblProducts.row(tr.row).node()).find('input[type="text"]').prop('disabled', !this.checked);
            credit_note.calculateInvoice();
            $('td:last', tblProducts.row(tr.row).node()).html('$' + credit_note.detail.products[tr.row].total.toFixed(2));
        })
        .on('change', 'input[name="quantity"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            credit_note.detail.products[tr.row].quantity = parseInt($(this).val());
            credit_note.calculateInvoice();
            $('td:last', tblProducts.row(tr.row).node()).html('$' + credit_note.detail.products[tr.row].total.toFixed(2));
        })
        .on('change', 'input[name="dscto_unitary"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            credit_note.detail.products[tr.row].dscto = parseFloat($(this).val());
            credit_note.calculateInvoice();
            var parent = $(this).closest('.bootstrap-touchspin');
            parent.find('.bootstrap-touchspin-postfix').children().html(credit_note.detail.products[tr.row].total_dscto.toFixed(2));
            $('td:last', tblProducts.row(tr.row).node()).html('$' + credit_note.detail.products[tr.row].total.toFixed(2));
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            credit_note.detail.products.splice(tr.row, 1);
            tblProducts.row(tr.row).remove().draw();
            credit_note.calculateInvoice();
        });
});