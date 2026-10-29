/* Lista de proformas. Toda columna de texto usa $.fn.dataTable.render.text(); los render que arman HTML escapan cada dato. */
var tblProformas;
var fpLista = {
    filas: {},
    filtros: function () {
        return {
            action: 'search', estado: $('#fp-estado').val(), desde: $('#fp-desde').val(), hasta: $('#fp-hasta').val(),
            q: $('#fp-q').val()
        };
    },
    listar: function () {
        var texto = $.fn.dataTable.render.text();
        tblProformas = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            responsive: true,
            deferRender: true,
            order: [],
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: function () { return fpLista.filtros(); },
                dataSrc: function (filas) {
                    fpLista.filas = {};
                    filas.forEach(function (p) { fpLista.filas[p.id] = p; });
                    return filas;
                },
                error: fpAcciones.error
            },
            columns: [
                {data: 'numero', render: $.fn.dataTable.render.text()},
                {data: 'cliente.nombre', render: $.fn.dataTable.render.text()},
                {data: 'cliente.identificacion', render: $.fn.dataTable.render.text()},
                {data: 'vendedor.nombre', defaultContent: '', render: $.fn.dataTable.render.text()},
                {data: 'fecha', render: texto},
                {data: 'valida_hasta', render: texto},
                {data: 'total', className: 'text-right', render: texto},
                {
                    data: 'estado.nombre', render: $.fn.dataTable.render.text(),
                    createdCell: function (td, dato, p) {
                        $(td).empty().append($('<span class="badge">').addClass(fpAcciones.claseEstado(p.estado.id)).text(dato));
                    }
                },
                {
                    data: 'venta.numero', defaultContent: '', render: $.fn.dataTable.render.text(),
                    createdCell: function (td, dato, p) {
                        if (p.venta && p.venta.sin_validez_tributaria) {
                            $(td).append(' ').append($('<span class="badge badge-warning">').text('PRUEBAS · sin validez tributaria'));
                        }
                    }
                },
                {
                    data: 'id', orderable: false, className: 'text-center',
                    render: function (dato, tipo, p) { return fpAcciones.botones(p, false); }
                }
            ]
        });
    }
};

$(function () {
    fpAcciones.despues = function () { tblProformas.ajax.reload(null, false); };
    fpAcciones.iniciar(function (id) { return fpLista.filas[id]; });
    fpLista.listar();
    $('#fp-filtros').on('submit', function (e) {
        e.preventDefault();
        tblProformas.ajax.reload();
    });
    $('#fp-ver-todas').on('click', function () {
        $('#fp-filtros')[0].reset();
        tblProformas.ajax.reload();
    });
});
