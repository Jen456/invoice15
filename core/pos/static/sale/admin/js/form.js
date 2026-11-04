var fvSale, fvClient;
var select_client, select_payment_type, select_receipt, select_medio_cobro;
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
        // Tarifa de cada producto (15 %, 5 %, 0 %, exento o no objeto); el servidor recalcula y manda. En centavos enteros y con
        // redondeo a la mitad hacia arriba, como calcular_linea_iva: la pantalla muestra el mismo total que se emite.
        var mitadArriba = function (numerador) { return Math.floor((numerador + 50) / 100); };
        var gravado = 0, cero = 0, descuentos = 0, ivas = 0;
        this.detail.products.forEach(function (value) {
            value.iva = value.tarifa !== undefined ? parseFloat(value.tarifa) / 100 : (value.with_tax ? parseFloat(tax) : 0);
            var tarifa = Math.round(value.iva * 100);
            var sub = Math.round(value.price_current * 100) * value.cant;
            var desc = mitadArriba(sub * (parseInt(value.dscto, 10) || 0));
            var base = sub - desc;
            var iva = mitadArriba(base * tarifa);
            value.price_with_vat = value.price_current + (value.price_current * value.iva);
            value.subtotal = sub / 100;
            value.total_dscto = desc / 100;
            value.total = base / 100;
            value.total_iva = iva / 100;
            if (tarifa > 0) { gravado += base; } else { cero += base; }
            descuentos += desc;
            ivas += iva;
        });
        this.detail.subtotal_0 = cero / 100;
        this.detail.subtotal_12 = gravado / 100;
        this.detail.total_dscto = descuentos / 100;
        this.detail.subtotal = (cero + gravado) / 100;
        this.detail.total_iva = ivas / 100;
        this.detail.total = (cero + gravado + ivas) / 100;

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
                {targets: [1], render: $.fn.dataTable.render.text()},
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
                        return '<span class="badge badge-secondary badge-pill">No inventariado</span>';
                    }
                },
                {
                    targets: [2],
                    render: function (data, type, row) {
                        var nombre = $('<div>').text(data).html();
                        return row.nombre_tarifa ? nombre + '<br><small class="text-muted">IVA ' + $('<div>').text(row.nombre_tarifa).html() + '</small>' : nombre;
                    }
                },
                {
                    targets: [-4],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="cant" aria-label="Cantidad" value="' + row.cant + '">';
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<input type="text" class="form-control" autocomplete="off" name="dscto_unitary" aria-label="Descuento en porcentaje" value="' + row.dscto + '">';
                    }
                },
                {
                    targets: [-3],
                    class: 'text-center',
                    render: function (data, type, row) {
                        // Precio de esta factura: no cambia el catálogo; el servidor lo valida y recalcula los importes.
                        if (sale.precioEditable()) {
                            return '<input type="text" inputmode="decimal" class="form-control fp-precio-linea" autocomplete="off" name="price_current" aria-label="Precio unitario sin IVA" value="' + parseFloat(data).toFixed(2) + '">';
                        }
                        return '$' + data.toFixed(2);
                    }
                },
                {
                    targets: [-1],
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
                // Al reutilizar una factura se conserva la cantidad original para revisarla, sin recortarla en silencio.
                if (data.fp_base) stock = Math.max(stock, data.cant);
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
                        min: 0,
                        max: 100,
                        step: 1,
                        decimals: 0,   // porcentaje entero, como lo guarda y valida el servidor
                        boostat: 5,
                        maxboostedstep: 10,
                        postfix: Number(data.total_dscto || 0).toFixed(2)
                    })
                    .on('keypress', function (e) {
                        var tecla = e.which || e.keyCode;
                        if (tecla === 44 || tecla === 46) {   // sin borrar el separador en silencio (2.5 no puede volverse 25)
                            message_error('El descuento es un porcentaje entero de 0 a 100, sin decimales.');
                            return false;
                        }
                        return validate_text_box({'event': e, 'type': 'numbers'});
                    });
                tr.find('input[name="price_current"]').on('keypress', function (e) {
                    return (e.which || e.keyCode) === 44 || validate_text_box({'event': e, 'type': 'decimals'});   // coma o punto
                });
            },
            initComplete: function (settings, json) {
                if (!$(this).parent().hasClass('dataTables_scroll')) { $(this).wrap('<div class="dataTables_scroll"></div>'); }
            }
        });
    },
    getProductsIds: function () {
        return this.detail.products.map(value => value.id);
    },
    precioEditable: function () {
        return $('.fp-sale-editor').attr('data-precio-editable') === '1';
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
                message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || (errorThrown + ' ' + textStatus));
            },
            complete: function () {
                input_search_product.val('').focus();
            }
        });
    },
    searchVoucherNumber: function () {
        if (this.consultaNumero) this.consultaNumero.abort();
        var version = this.versionNumero = (this.versionNumero || 0) + 1;
        var panel = $('.fp-punto-emision'), aviso = panel.find('.fp-punto-aviso');
        $('input[name="voucher_number"]').val('');
        panel.find('.fp-punto-proximo').text('Consultando…');
        this.consultaNumero = $.ajax({
            url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            data: {action: 'search_voucher_number', receipt: select_receipt.val(), punto: panel.find('[name="punto"]').val() || ''},
            success: function (r) {
                if (version !== sale.versionNumero) return;
                var mensaje = r.error || (r.pending && r.pending.mensaje);
                aviso.text(mensaje || '').prop('hidden', !mensaje);
                $('input[name="voucher_number"]').val(r.voucher_number || '');
                panel.find('.fp-punto-proximo').text(r.voucher_number_full || 'Por confirmar');
                if (r.punto) panel.find('.fp-punto-etiqueta').text(r.punto.etiqueta);
            },
            error: function (xhr, status) {
                if (status === 'abort' || version !== sale.versionNumero) return;
                panel.find('.fp-punto-proximo').text('Por confirmar');
                aviso.text((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo consultar el próximo número. Vuelve a elegir el punto para reintentar.').prop('hidden', false);
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
    },
    cargarProforma: function (datos) {
        // Factura de una proforma (core/proformas): comprobante 01, líneas con el precio y el descuento cotizados (sin
        // addProduct, que fusiona y suma cantidades), información adicional que se puede quitar, forma de pago y cliente
        // o prospecto. Todo se puede revisar antes de emitir; el servidor recalcula y manda.
        select_receipt.val('01').trigger('change');
        select_receipt.find('option').not('[value="01"]').prop('disabled', true);
        datos.lineas.forEach(function (linea) {
            sale.detail.products.push(linea);
        });
        sale.detail.additional_info = datos.info_adicional.slice();
        sale.listAdditionalInfo();
        if (datos.forma_pago) {
            $('select[name="payment_method"]').val(datos.forma_pago).trigger('change');
        }
        if (datos.cliente) {
            select_client.select2('trigger', 'select', {data: datos.cliente});
        } else if (datos.prospecto) {
            var prospecto = datos.prospecto, formulario = $('#frmClient');
            var correos = (prospecto.correo || '').split(',').map(function (c) { return c.trim(); }).filter(Boolean);
            var identificacion = (prospecto.identificacion || '').trim();
            var telefono = (prospecto.telefono || '').replace(/\D/g, '');
            formulario.find('input[name="names"]').val(prospecto.nombre);
            formulario.find('input[name="email"]').val(correos.length ? correos[0] : '');
            formulario.find('input[name="extra_emails"]').val(correos.slice(1).join(', '));
            formulario.find('input[name="dni"]').val(identificacion);
            formulario.find('input[name="mobile"]').val(telefono.length <= 10 ? telefono : '');
            formulario.find('[name="address"]').val(prospecto.direccion);
            if (/^\d{10}$/.test(identificacion)) {
                formulario.find('select[name="identification_type"]').val('05').trigger('change');
            } else if (/^\d{13}$/.test(identificacion)) {
                formulario.find('select[name="identification_type"]').val('04').trigger('change');
            }
            input_birthdate.datetimepicker('clear');   // sin fecha de nacimiento inventada
            if ($('.btnAddClient').length) {
                $('#myModalClient').modal('show');
            } else {   // sin add_client el alta no se ofrece
                message_error('La proforma es para un prospecto: elige un cliente registrado antes de emitir.');
            }
        }
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
                        callback: {
                            message: 'La identificación no es válida para el tipo elegido',
                            callback: function (input) {
                                return identificacion_valida(fvClient.form.querySelector('[name="identification_type"]').value, input.value);
                            },
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fvClient.form.querySelector('[name="dni"]').value,
                                    pattern: 'dni',
                                    empresa: (fvClient.form.querySelector('[name="empresa"]') || {}).value || '',
                                    action: 'validate_client'
                                };
                            },
                            // Sin mensaje fijo: el servidor dice si el cliente está repetido o si la empresa cambió en otra pestaña.
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                // Opcionales y repetibles: hay compradores sin teléfono ni correo, y empresas de un mismo grupo comparten ambos.
                mobile: {
                    validators: {
                        stringLength: {
                            min: 7
                        },
                        digits: {}
                    }
                },
                email: {
                    validators: {
                        stringLength: {
                            min: 5
                        },
                        regexp: {
                            regexp: /^([a-z0-9_\.-]+)@([\da-z\.-]+)\.([a-z\.]{2,6})$/i,
                            message: 'El formato email no es correcto'
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
                        date: {   // opcional: vacío es válido (ya no se inventa la fecha de hoy)
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
            fpClienteRapido.guardar();
        });
});

document.addEventListener('DOMContentLoaded', function (e) {
    function validateChange() {
        var cash = parseFloat(input_cash.val());
        if (select_payment_type.val() === 'efectivo' && select_medio_cobro.val() === 'efectivo') {
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
            if (sale.validarBase && !sale.validarBase()) return false;
            if (sale.detail.products.length === 0) {
                message_error('Debe tener al menos un item en el detalle de la venta');
                return false;
            }
            var customer = select_client.select2('data')[0];
            if (select_receipt.val() === '01') {
                if (customer.identification_type.id === '07' && sale.detail.total > 50.00) {
                    message_error('Una factura a consumidor final no puede superar USD 50,00: registra los datos del comprador.');
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
                    if (request.en_proceso || !request.print_url) {
                        // El SRI aún autoriza la factura: quedó guardada; se consulta desde el listado.
                        alert_sweetalert({'message': request.mensaje || 'Venta guardada.', 'timer': 9000, 'callback': function () {
                            location.href = list_url;
                        }});
                        return;
                    }
                    dialog_action({
                        'content': (request.mensaje ? request.mensaje + '<br>' : '') + '¿Desea Imprimir el Comprobante?',
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
    select_medio_cobro = $('select[name="medio_cobro"]');
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
        .on('change', 'input[name="price_current"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            var producto = sale.detail.products[tr.row];
            var texto = String($(this).val()).replace(',', '.').trim();
            if (!/^\d{1,6}(\.\d{1,2})?$/.test(texto)) {
                message_error('El precio va de 0 a 999999,99, con hasta 2 decimales.');
                $(this).val(producto.price_current.toFixed(2));
                return;
            }
            producto.price_current = parseFloat(texto);
            $(this).val(producto.price_current.toFixed(2));
            sale.calculateInvoice();
            $('td:last', tblProducts.row(tr.row).node()).html('$' + producto.total.toFixed(2));
            $('input[name="dscto_unitary"]', tblProducts.row(tr.row).node()).closest('.bootstrap-touchspin')
                .find('.bootstrap-touchspin-postfix').children().html(producto.total_dscto.toFixed(2));
        })
        .on('change', 'input[name="dscto_unitary"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            sale.detail.products[tr.row].dscto = parseInt($(this).val(), 10) || 0;
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
        placeholder: 'Busca por nombre o identificación',
        minimumInputLength: 1,
    })
        .on('select2:select', function (e) {
            fvSale.revalidateField('client');
        })
        .on('select2:clear', function (e) {
            fvSale.revalidateField('client');
        });

    $('.btnAddClient').on('click', function () {
        $('#myModalClient').modal('show');
    });

    $('#frmClient input[name="dni"]').on('keypress', function (e) {
        return es_identificacion_extranjera($('#frmClient select[name="identification_type"]').val()) || validate_text_box({'event': e, 'type': 'numbers'});
    });

    $('#frmClient select[name="identification_type"]').on('change', function () {
        if ($('#frmClient input[name="dni"]').val()) {
            fvClient.revalidateField('dni');
        }
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

    // Cambio explícito del punto de emisión dentro del formulario: se vuelve a pedir el próximo número de ese punto.
    $('select[name="punto"]').on('change', function () {
        sale.searchVoucherNumber();
    });

    // Condición de pago (contado / crédito) y medio de cobro (core/cobros): «Efectivo recibido» y «Cambio» solo con
    // efectivo; con otro medio van en 0 y el servidor exige comprobante o nota. A crédito no hay cobro al emitir.
    function aplicarCondicionYMedio() {
        var contado = select_payment_type.val() === 'efectivo';
        var efectivo = contado && select_medio_cobro.val() === 'efectivo';
        sale.setOptionsFields([{'index': 0, 'enable': efectivo}, {'index': 1, 'enable': efectivo}, {'index': 2, 'enable': !contado}]);
        $('.fp-cobro').toggle(contado).find('input,select,textarea').prop('disabled', !contado);
        $('.fp-cobro-efectivo-aviso').toggle(efectivo);
        if (efectivo) {
            fvSale.enableValidator('cash');
            fvSale.enableValidator('change');
        } else {
            input_cash.val('0.00');
            input_change.val('0.00');
            fvSale.disableValidator('cash');
            fvSale.disableValidator('change');
        }
        if (contado) { fvSale.disableValidator('end_credit'); } else { fvSale.enableValidator('end_credit'); }
    }

    select_payment_type.on('change', aplicarCondicionYMedio);
    select_medio_cobro.on('change', aplicarCondicionYMedio);

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
        if (e.which !== 13) return;
        if (e.target === input_search_product[0]) {
            e.preventDefault();
            sale.searchProductBarcode();
        } else if ($(e.target).closest('#frmForm').length && $(e.target).is('input:not([type=file]):not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit])')) {
            // Evita la emisión implícita desde un campo; conserva Enter en notas y botones.
            e.preventDefault();
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

    var nodoProforma = document.getElementById('fp-proforma-precarga');
    if (nodoProforma) {
        sale.cargarProforma(JSON.parse(nodoProforma.textContent));
    }
});
