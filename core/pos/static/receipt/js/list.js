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
                {
                    targets: [1, 2, 3, 4, 5],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data || '—';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        return data ? 'Confirmada' : 'Por confirmar';
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