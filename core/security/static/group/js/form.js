var tblPermissions = null;

var group = {
    listPermissions: function () {
        tblPermissions = $('#tblPermissions').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            paging: false,
            ordering: false,
            info: false,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search_permissions'
                },
                dataSrc: ""
            },
            columns: [
                {data: "id"},
                {data: "name"},
                {data: "module_type"},
                {data: "url"},
                {data: "state"},
                {data: "permissions"},
            ],
            columnDefs: [
                {
                    targets: [-4],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (!$.isEmptyObject(row.module_type)) {
                            return row.module_type.name;
                        }
                        return '---';
                    }
                },
                {
                    targets: [-2],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return '<div class="d-flex justify-content-center"><div class="form-check"><input class="form-check-input" name="chk_state" type="checkbox" value=""></div></div>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-left',
                    render: function (data, type, row) {
                        var inputs = '';
                        if (row.permissions) {
                            row.permissions.forEach(function (value, index, array) {
                                inputs += '<div class="form-check form-check-inline"><input class="form-check-input" type="checkbox" data-id="' + value.id + '" name="chk_permission">';
                                inputs += '<label class="form-check-label">' + value.codename + '</label></div>';
                            });
                        }
                        return inputs;
                    }
                },
            ],
            rowCallback: function (row, data, index) {
                var tr = $(row).closest('tr');
                tr.find('input[name="chk_state"]').prop('checked', data.checked);
                data.permissions.forEach(function (value, index, array) {
                    var input = tr.find('input[name="chk_permission"][data-id="' + value.id + '"]');
                    input.prop('disabled', !data.checked);
                    input.prop('checked', value.checked)
                });
            },
            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    },
    getPermissions: function () {
        var objec_list = Object.assign([], tblPermissions.rows().data().toArray()).filter(value => value.checked === 1);
        objec_list.forEach(function (value, index, array) {
            value.permissions = value.permissions.filter(value1 => value1.checked === 1);
        });
        return objec_list;
    }
};

document.addEventListener('DOMContentLoaded', function (e) {
    const fv = FormValidation.formValidation(document.getElementById('frmForm'), {
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
            var params = new FormData(fv.form);
            params.append('items', JSON.stringify(group.getPermissions()));
            var args = {
                'params': params,
                'form': fv.form
            };
            submit_with_formdata(args);
        });
});

$(function () {

    group.listPermissions();

    $('#tblPermissions tbody')
        .off()
        .on('change', 'input[name="chk_state"]', function () {
            var checked = this.checked;
            var tr = tblPermissions.cell($(this).closest('td, li')).index();
            var row = tblPermissions.row(tr.row).data();
            var node = tblPermissions.row(tr.row).node();
            row.checked = checked ? 1 : 0;
            $('td:eq(-1)', node).find('input').prop('disabled', !checked).prop('checked', checked);
            row.permissions.forEach(function (value, index, array) {
                value.checked = checked ? 1 : 0;
            });
        })
        .on('change', 'input[name="chk_permission"]', function () {
            var tr = tblPermissions.cell($(this).closest('td, li')).index();
            var row = tblPermissions.row(tr.row).data();
            var index = row.permissions.findIndex(value => value.id === $(this).data('id'));
            if (index > -1) {
                row.permissions[index].checked = this.checked ? 1 : 0;
            }
        });

    $('input[name="chk-select-all"]').on('change', function () {
        var checked = this.checked;
        if (tblPermissions) {
            var cells = tblPermissions.cells().nodes();
            $(cells).find('input[name="chk_state"]').prop('checked', checked).trigger('change');
        }
    });
});





