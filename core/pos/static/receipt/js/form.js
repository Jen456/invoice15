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
                voucher_type: {
                    validators: {
                        notEmpty: {
                            message: 'Seleccione un item'
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    voucher_type: fv.form.querySelector('[name="voucher_type"]').value,
                                    establishment_code: fv.form.querySelector('[name="establishment_code"]').value,
                                    issuing_point_code: fv.form.querySelector('[name="issuing_point_code"]').value,
                                    action: 'validate_data'
                                };
                            },
                            message: 'El comprobante ya se encuentra registrado',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                establishment_code: {
                    validators: {
                        notEmpty: {},
                        digits: {},
                    }
                },
                issuing_point_code: {
                    validators: {
                        notEmpty: {},
                        digits: {},
                    }
                },
                sequence: {
                    validators: {
                        notEmpty: {},
                        digits: {},
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
            var args = {
                'params': new FormData(fv.form),
                'form': fv.form
            };
            submit_with_formdata(args);
        });
});

$(function () {
    $('.select2').select2({
        theme: 'bootstrap4',
        language: "es"
    });

    $('select[name="voucher_type"]')
        .on('change', function () {
            fv.revalidateField('voucher_type');
        });

    $('input[name="establishment_code"]')
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    $('input[name="issuing_point_code"]')
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    $('input[name="sequence"]')
        .TouchSpin({
            min: 0,
            max: 999999999,
            step: 1
        })
        .on('change touchspin.on.min touchspin.on.max', function () {
            fv.revalidateField('sequence');
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    $('i[data-field="sequence"]').hide();
});
