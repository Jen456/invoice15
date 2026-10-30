// Proveedor con los datos del ATS (espec-etapa2-compras §6.D). La validación definitiva es la del servidor
// (proveedores.validar_proveedor); aquí la identificación se revisa según el tipo elegido. La parte relacionada no tiene
// valor inicial (DC12). El tipo de sujeto se calcula con RUC o cédula y se elige con pasaporte o identificación del exterior.
var btnSearchRUCInSRI;
var input_ruc, select_tipo, select_sujeto;
var fv;

var provider = {
    searchRUCInSRI: function () {
        $.ajax({
            url: pathname,
            data: {
                'action': 'search_ruc_in_sri',
                'ruc': input_ruc.val()
            },
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            dataType: 'json',
            success: function (request) {
                if (!request.hasOwnProperty('error')) {
                    $('input[name="name"]').val(request.razonSocial);
                    var detalles = $('#details').empty();
                    Object.entries(request).forEach(([key, value]) => {
                        detalles.append($('<dt>').text(key.toUpperCase()));
                        detalles.append($('<dd>').text(typeof (value) == "object" ? JSON.stringify(value) : value));
                    });
                    $('#myModalSRI').modal('show');
                    return false;
                }
                message_error(request.error);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error((jqXHR.responseJSON && jqXHR.responseJSON.error) || (errorThrown + ' ' + textStatus));
            }
        });
    },
    actualizarTipo: function () {
        var tipo = select_tipo.val();
        var numero = (input_ruc.val() || '').replace(/\s/g, '');
        if (tipo === '04') {
            select_sujeto.val(numero.length >= 3 && '69'.indexOf(numero.charAt(2)) >= 0 ? '02' : '01').prop('disabled', true);
        } else if (tipo === '05') {
            select_sujeto.val('01').prop('disabled', true);
        } else {
            select_sujeto.prop('disabled', false);
        }
        btnSearchRUCInSRI.prop('disabled', !(tipo === '04' && numero.length === 13));
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
                excluded: new FormValidation.plugins.Excluded(),
                icon: new FormValidation.plugins.Icon({
                    valid: 'fa fa-check',
                    invalid: 'fa fa-times',
                    validating: 'fa fa-refresh',
                }),
            },
            fields: {
                name: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 2,
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fv.form.querySelector('[name="name"]').value,
                                    pattern: 'name',
                                    action: 'validate_data'
                                };
                            },
                            message: 'El nombre ya se encuentra registrado',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        }
                    }
                },
                tipo_identificacion: {
                    validators: {
                        notEmpty: {message: 'Elige el tipo de identificación'}
                    }
                },
                ruc: {
                    validators: {
                        notEmpty: {},
                        callback: {
                            message: 'La identificación no corresponde al tipo elegido',
                            callback: function (input) {
                                var tipo = fv.form.querySelector('[name="tipo_identificacion"]').value;
                                return !tipo || identificacion_valida(tipo, input.value);
                            },
                        },
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fv.form.querySelector('[name="ruc"]').value,
                                    pattern: 'ruc',
                                    action: 'validate_data'
                                };
                            },
                            message: 'La identificación ya se encuentra registrada',
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrftoken
                            },
                        },
                    }
                },
                tipo_sujeto: {
                    validators: {
                        callback: {
                            message: 'Elige si es persona natural o sociedad',
                            callback: function (input) {
                                var tipo = fv.form.querySelector('[name="tipo_identificacion"]').value;
                                return !es_identificacion_extranjera(tipo) || input.value !== '';
                            }
                        }
                    }
                },
                parte_relacionada: {
                    validators: {
                        notEmpty: {message: 'Indica si es parte relacionada'}
                    }
                },
                mobile: {
                    validators: {
                        notEmpty: {},
                        stringLength: {
                            min: 10
                        },
                        digits: {},
                        remote: {
                            url: pathname,
                            data: function () {
                                return {
                                    parameter: fv.form.querySelector('[name="mobile"]').value,
                                    pattern: 'mobile',
                                    action: 'validate_data'
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
                                    parameter: fv.form.querySelector('[name="email"]').value,
                                    pattern: 'email',
                                    action: 'validate_data'
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
                    validators: {}
                }
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
                'form': fv.form,
                'success': function (request) {
                    var destino = $(fv.form).attr('data-url');
                    var avisos = (request.advertencias || []).map(function (a) { return a.texto; }).join('\n');
                    if (!avisos) {
                        location.href = destino;
                        return;
                    }
                    alert_sweetalert({
                        'title': 'Proveedor guardado', 'type': 'warning', 'message': avisos,
                        'callback': function () { location.href = destino; }
                    });
                }
            };
            submit_with_formdata(args);
        });
});

$(function () {

    btnSearchRUCInSRI = $('.btnSearchRUCInSRI');
    input_ruc = $('input[name="ruc"]');
    select_tipo = $('select[name="tipo_identificacion"]');
    select_sujeto = $('select[name="tipo_sujeto"]');

    input_ruc
        .on('keyup change', function () {
            provider.actualizarTipo();
        })
        .on('keypress', function (e) {
            return es_identificacion_extranjera(select_tipo.val()) || validate_text_box({'event': e, 'type': 'numbers'});
        });

    select_tipo.on('change', function () {
        provider.actualizarTipo();
        if (input_ruc.val()) {
            fv.revalidateField('ruc');
        }
        fv.revalidateField('tipo_sujeto');
    });

    $('input[name="mobile"]').on('keypress', function (e) {
        return validate_text_box({'event': e, 'type': 'numbers'});
    });

    btnSearchRUCInSRI.on('click', function () {
        provider.searchRUCInSRI();
    });

    provider.actualizarTipo();

    $('i[data-field="search_ruc_sri"]').hide();
});
