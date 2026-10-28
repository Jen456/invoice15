// Proveedores (espec-etapa2-compras §6.D): tipo de identificación e insignia «Datos incompletos» con lo que falta para el
// ATS. Texto escapado: la razón social puede venir del XML de un tercero.
function esc(valor) {
    return $('<div>').text(valor === null || valor === undefined ? '' : String(valor)).html();
}

var provider = {
    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search'
                },
                dataSrc: ""
            },
            columns: [
                {data: "id"},
                {data: "name", render: $.fn.dataTable.render.text()},
                {data: "tipo_identificacion.name", render: $.fn.dataTable.render.text()},
                {data: "ruc", render: $.fn.dataTable.render.text()},
                {data: "mobile", render: $.fn.dataTable.render.text()},
                {data: "email", render: $.fn.dataTable.render.text()},
                {data: "address", render: $.fn.dataTable.render.text()},
                {
                    data: "datos_completos",
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (data) {
                            return '<span class="text-muted">Completos</span>';
                        }
                        var faltan = (row.faltantes || []).map(function (f) { return f.texto; }).join('; ');
                        return '<span class="badge badge-warning" title="' + esc(faltan) + '">Datos incompletos</span>' +
                            '<br><small>' + esc(faltan) + '</small>';
                    }
                },
                {
                    data: "id",
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        var id = parseInt(row.id, 10);
                        var buttons = '<a href="' + pathname + 'update/' + id + '/" data-toggle="tooltip" title="Editar" class="btn btn-warning btn-xs btn-flat"><i class="fas fa-edit"></i></a> ';
                        buttons += '<a href="' + pathname + 'delete/' + id + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash-alt"></i></a>';
                        return buttons;
                    }
                },
            ],
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    }
};

$(function () {
    provider.list();
});
