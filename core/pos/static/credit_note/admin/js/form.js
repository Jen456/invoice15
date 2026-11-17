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
    // Precios CON IVA (contrato «precios con IVA» §1 y §2): una factura guardada con precio con IVA (todas sus líneas traen
    // `con_iva_incluido`) se devuelve con el mismo cálculo que hará el servidor (static/js/fp-importes.js) sobre la cantidad
    // devuelta: precio con IVA × cantidad − descuento = total con IVA, y de ahí la base y el IVA. Una factura anterior al
    // cambio se calcula y se muestra como siempre (precio sin IVA). El servidor recalcula y manda: cantidad devuelta es lo
    // único que lee de esta pantalla (precio, descripción, descuento y tarifa salen de la factura).
    conIva: function () {
        return !this.detail.products.some(function (l) { return l.con_iva_incluido !== true; });
    },
    importes: function (linea) {
        if (linea.con_iva_incluido !== true) return null;
        return fpImportes.lineaSegura({precio_con_iva: linea.precio_con_iva, cant: linea.quantity, dscto: linea.dscto,
            tarifa: linea.tarifa});
    },
    texto: function (x) {
        return $('<div>').text(x === null || x === undefined ? '' : String(x)).html();
    },
    textoPrecio: function (row) {
        if (!this.conIva()) return '$' + row.price.toFixed(2);
        var c = fpImportes.centavos(String(row.precio_con_iva));
        return c === null ? '—' : '$' + fpImportes.dinero(c);
    },
    textoDescuento: function (row) {
        // El descuento es el de la factura (el servidor no lo toma de esta pantalla): se muestra, no se edita.
        var porcentaje = Number(row.dscto) || 0;
        if (!porcentaje) return 'Sin descuento';
        var valor = this.conIva() ? (row.descuento_con_iva || '0.00') + ' con IVA' : (row.total_dscto || 0).toFixed(2) + ' sin IVA';
        return this.texto(porcentaje) + ' %<br><small class="text-muted">−$' + this.texto(valor) + '</small>';
    },
    textoTotal: function (row) {
        if (!this.conIva()) return '$' + (row.total || 0).toFixed(2);
        return row.total_con_iva ? '$' + this.texto(row.total_con_iva) : '—';
    },
    refrescarFila: function (indice) {
        var linea = this.detail.products[indice], nodo = $(tblProducts.row(indice).node());
        nodo.find('.fp-nc-dscto').html(this.textoDescuento(linea));
        nodo.find('td:last').html(this.textoTotal(linea));
    },
    listProducts: function () {
        this.calculateInvoice();
        var conIva = this.conIva(), encabezados = $('#tblProducts thead th');
        encabezados.eq(4).text(conIva ? 'P. unitario con IVA' : 'P./Unitario (sin IVA)');
        encabezados.eq(6).text(conIva ? 'Total con IVA' : 'Total (sin IVA)');
        $('#fp-nc-rotulo-dscto').text(conIva ? ' (CON IVA)' : ' (SIN IVA)');
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
                {data: "dscto"},
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
                    targets: [1],
                    render: function (data, type, row) {
                        // Solo presentación: la descripción escrita en la línea de la factura (precios con IVA), si la tiene.
                        var nombre = row.product ? row.product.short_name : '';
                        if (typeof row.descripcion === 'string' && row.descripcion.trim() && row.descripcion !== (row.product || {}).name) {
                            return credit_note.texto(row.descripcion) + '<br><small class="text-muted">Producto: ' + credit_note.texto(nombre) + '</small>';
                        }
                        return credit_note.texto(nombre);
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
                    targets: [-3],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return credit_note.textoPrecio(row);
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<span class="fp-nc-dscto">' + credit_note.textoDescuento(row) + '</span>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return credit_note.textoTotal(row);
                    }
                }
            ],
            rowCallback: function (row, data, index) {
                var tr = $(row).closest('tr');
                tr.find('input[name="quantity"]')
                    .TouchSpin({
                        min: 1,
                        // Lo que aún se puede acreditar de la línea (vendido menos lo ya acreditado), que es lo que admite el servidor.
                        max: data.disponible !== undefined ? data.disponible : data.cant
                    })
                    .on('keypress', function (e) {
                        return validate_text_box({'event': e, 'type': 'numbers'});
                    });

                tr.find('input[name="quantity"]').prop('disabled', data.state === 0);
            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    calculateInvoice: function () {
        var tax = this.detail.iva / 100;
        // Tarifa de la línea de la factura (15 %, 5 %, 0 %, exento o no objeto); el servidor recalcula y manda.
        var redondear = function (valor) { return Math.round((valor + Number.EPSILON) * 100) / 100; };
        var nuevas = [], anteriores = [];
        this.detail.products.forEach(function (value, index, array) {
            var r = credit_note.importes(value);
            value.iva = value.tarifa !== undefined ? parseFloat(value.tarifa) / 100 : (value.product.with_tax ? parseFloat(tax) : 0);
            if (r) {
                // Línea con precio con IVA: total con IVA exacto; base e IVA derivados (centavos enteros, mitad hacia arriba).
                value.total_con_iva = fpImportes.dinero(r.total);
                value.descuento_con_iva = fpImportes.dinero(r.descuento);
                value.base = fpImportes.numero(r.base);
                value.total_iva = fpImportes.numero(r.iva);
                value.total_dscto = fpImportes.numero(r.descuento);
                value.total = fpImportes.numero(r.total);
                if (value.state === 1) nuevas.push(r);
                return;
            }
            // Línea anterior al cambio: el cálculo de siempre, sobre el precio sin IVA.
            value.price_with_vat = value.price + (value.price * value.iva);
            value.subtotal = redondear(value.price * value.quantity);
            value.total_dscto = redondear(value.subtotal * parseFloat((value.dscto / 100)));
            value.total = value.subtotal - value.total_dscto;
            value.base = value.total;
            value.total_iva = redondear(value.total * value.iva);
            if (value.state === 1) anteriores.push(value);
        });
        var t = fpImportes.totales(nuevas);
        var sumar = function (lista, campo) { return lista.reduce(function (a, b) { return a + (b[campo] || 0); }, 0); };
        this.detail.subtotal_0 = fpImportes.numero(t.base_0) + sumar(anteriores.filter(value => !value.iva), 'base');
        this.detail.subtotal_12 = fpImportes.numero(t.base_gravada) + sumar(anteriores.filter(value => value.iva > 0), 'base');
        this.detail.total_dscto = fpImportes.numero(t.descuento) + sumar(anteriores, 'total_dscto');
        this.detail.subtotal = parseFloat(this.detail.subtotal_0) + parseFloat(this.detail.subtotal_12);
        this.detail.total_iva = fpImportes.numero(t.iva) + sumar(anteriores, 'total_iva');
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
            // Solo las líneas marcadas: el servidor acredita cada línea que recibe con su cantidad.
            params.append('products', JSON.stringify(credit_note.detail.products.filter(value => value.state === 1)));
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
            object.detail.forEach(function (linea) { linea.disponible = linea.quantity; });   // lo que queda por acreditar
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
            credit_note.refrescarFila(tr.row);
        })
        .on('change', 'input[name="quantity"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            var cantidad = parseInt($(this).val(), 10);
            credit_note.detail.products[tr.row].quantity = isNaN(cantidad) ? 1 : cantidad;
            credit_note.calculateInvoice();
            credit_note.refrescarFila(tr.row);
        })
        .on('click', 'a[rel="remove"]', function () {
            var tr = tblProducts.cell($(this).closest('td, li')).index();
            credit_note.detail.products.splice(tr.row, 1);
            tblProducts.row(tr.row).remove().draw();
            credit_note.calculateInvoice();
        });
});