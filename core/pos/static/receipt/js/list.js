var receipt = {
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
            // Solo consulta: la numeración se configura en el asistente (/configuracion/facturacion/).
            columns: [
                {"data": "voucher_type.name"},
                {"data": "environment_type.name"},
                {"data": "establishment_code"},
                {"data": "issuing_point_code"},
                {"data": "last_number_full"},
                {"data": "next_number_full"},
                {"data": "confirmed"},
            ],
            columnDefs: [
                {targets: [0], render: $.fn.dataTable.render.text()},
                {
                    targets: [1, 2, 3, 4, 5],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return $.fn.dataTable.render.text().display(data || '—');
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (type !== 'display') { return data ? 'Confirmada' : 'Por confirmar'; }
                        return '<span class="badge fpa-badge">' + (data ? 'Confirmada' : 'Por confirmar') + '</span>';
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
    receipt.list();
});