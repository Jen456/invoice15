// Gasto sin comprobante (espec-etapa2-compras §6.F): medio de pago obligatorio y sin valor inicial; referencia
// obligatoria con cheque. El servidor repite estas reglas (ExpensesForm).
var fv;

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
                description: {
                    validators: {}
                },
                type_expense: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un tipo de gasto'
                        }
                    }
                },
                date_joined: {
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
                valor: {
                    validators: {
                        notEmpty: {},
                        numeric: {decimalSeparator: '.'}
                    }
                },
                medio_pago: {
                    validators: {
                        notEmpty: {message: 'Elige el medio de pago'}
                    }
                },
                referencia: {
                    validators: {
                        stringLength: {max: 100},
                        callback: {
                            message: 'Escribe el número del cheque',
                            callback: function (input) {
                                return fv.form.querySelector('[name="medio_pago"]').value !== 'cheque' || input.value.trim() !== '';
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
            if (!fv.form.reportValidity()) return;
            var args = {
                'params': new FormData(fv.form),
                'form': fv.form
            };
            if (fv.form.elements.action.value === 'add') args.params.set('nota_respaldo', fv.form.elements.description.value);
            submit_with_formdata(args);
        });
});

$(function () {
    $('input[name="date_joined"]').on('change', function () {
        fv.revalidateField('date_joined');
    });

    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es"
    });

    $('select[name="type_expense"]')
        .on('change', function () {
            fv.revalidateField('type_expense');
        });

    $('select[name="medio_pago"]').on('change', function () {
        if (this.value === 'cheque') document.getElementById('fpGastoAdicional').open = true;
        fv.revalidateField('referencia');
    });

    $('i[data-field="valor"]').hide();

    var archivo = document.getElementById('id_comprobante');
    if (archivo) {
        var mensaje = document.getElementById('fpGastoArchivoEstado');
        var quitar = document.getElementById('fpGastoQuitarArchivo');
        archivo.addEventListener('change', function () {
            var seleccionado = archivo.files[0];
            var error = seleccionado && seleccionado.size > Number(archivo.dataset.maxBytes);
            archivo.setCustomValidity(error ? 'El archivo supera los 8 MB. Elige uno más pequeño.' : '');
            mensaje.textContent = error ? archivo.validationMessage : (seleccionado ? 'Seleccionado: ' + seleccionado.name + '. Se enviará al guardar.' : '');
            mensaje.classList.toggle('text-danger', Boolean(error));
            archivo.setAttribute('aria-invalid', error ? 'true' : 'false');
            quitar.hidden = !seleccionado;
        });
        quitar.addEventListener('click', function () {
            archivo.value = '';
            archivo.dispatchEvent(new Event('change'));
            archivo.focus();
        });
    }
});

