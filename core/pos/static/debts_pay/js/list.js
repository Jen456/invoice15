// Cuentas por pagar (espec-etapa2-compras §6.E): base de cálculo, pagado, abonado y saldo; pagos con medio de pago y
// referencia y abonos por retención o nota de crédito. Solo los pagos se borran, y solo con delete_debts_pay (el
// servidor responde 403 sin él). Texto escapado: la razón social puede venir del XML de un tercero.
var tblPaymentsDebtsPay, tblDebtsPay;
var input_date_range;
var puede_borrar = false;

function dinero(valor) {
    return valor === null || valor === undefined ? '—' : '$' + valor;
}

function centavos(valor) {
    return Math.round(Number(valor || 0) * 100);
}

var debts_pay = {
    list: function (all) {
        var parameters = {
            'action': 'search',
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
        };
        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }
        tblDebtsPay = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: parameters,
                dataSrc: ""
            },
            columns: [
                {data: "purchase.numero_comprobante", render: $.fn.dataTable.render.text()},
                {data: "purchase.provider.name", render: $.fn.dataTable.render.text()},
                {data: "date_joined", class: 'text-center'},
                {data: "end_date", class: 'text-center'},
                {data: "debt", class: 'text-right', render: function (data) { return '$' + Number(data).toFixed(2); }},
                {
                    data: "base_calculo.id",
                    class: 'text-center',
                    render: function (data) {
                        return data === 'subtotal' ? '<span class="badge badge-secondary">Calculada sin IVA</span>' : 'Total con IVA';
                    }
                },
                {data: "pagado", class: 'text-right', render: function (data) { return dinero(data); }},
                {data: "abonado", class: 'text-right', render: function (data) { return dinero(data); }},
                {
                    data: "saldo",
                    class: 'text-right',
                    render: function (data, type, row) {
                        if (row.saldo_a_favor) {
                            return '<span class="badge badge-info">Saldo a favor</span> $' + Math.abs(Number(data)).toFixed(2);
                        }
                        return '$' + Number(data).toFixed(2);
                    }
                },
                {
                    data: "state",
                    orderable: false,
                    class: 'text-center',
                    render: function (data) {
                        if (data) {
                            return '<span class="badge badge-danger badge-pill">Adeuda</span>';
                        }
                        return '<span class="badge badge-success badge-pill">Pagado</span>';
                    }
                },
                {
                    data: "id",
                    orderable: false,
                    class: 'text-center',
                    render: function (data, type, row) {
                        var buttons = '<a rel="payments" data-toggle="tooltip" title="Pagos y abonos" class="btn bg-blue btn-xs btn-flat"><i class="fas fa-dollar-sign"></i></a> ';
                        if (puede_borrar) {
                            buttons += '<a href="' + pathname + 'delete/' + parseInt(row.id, 10) + '/" data-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-xs btn-flat"><i class="fas fa-trash"></i></a>';
                        }
                        return buttons;
                    }
                },
            ],
            initComplete: function (settings, json) {
                $('[data-toggle="tooltip"]').tooltip();
                $(this).wrap('<div class="dataTables_scroll"><div/>');
                var total = json.reduce(function (suma, fila) { return suma + Math.max(centavos(fila.saldo), 0); }, 0);
                $('.total').text('$' + (total / 100).toFixed(2));
            }
        });
    }
};

$(function () {

    try {
        puede_borrar = JSON.parse(document.getElementById('fp-cxp-puede-borrar').textContent) === true;
    } catch (e) {
        puede_borrar = false;
    }

    input_date_range = $('input[name="date_range"]');

    input_date_range
        .daterangepicker({
                language: 'auto',
                startDate: new Date(),
                locale: {
                    format: 'YYYY-MM-DD',
                },
                autoApply: true,
            }
        )
        .on('change.daterangepicker apply.daterangepicker', function (ev, picker) {
            debts_pay.list(false);
        });

    $('.drp-buttons').hide();

    debts_pay.list(false);

    $('.btnSearchAll').on('click', function () {
        debts_pay.list(true);
    });

    $('#data tbody')
        .off()
        .on('click', 'a[rel="payments"]', function () {
            $('.tooltip').remove();
            var tr = tblDebtsPay.cell($(this).closest('td, li')).index(),
                row = tblDebtsPay.row(tr.row).data();
            tblPaymentsDebtsPay = $('#tblPayments').DataTable({
                autoWidth: false,
                destroy: true,
                searching: false,
                ajax: {
                    url: pathname,
                    type: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    },
                    data: function (d) {
                        d.action = 'search_pays';
                        d.id = row.id;
                    },
                    dataSrc: ""
                },
                columns: [
                    {data: "index"},
                    {
                        data: "tipo",
                        render: function (data) {
                            return {'pago': 'Pago', 'retencion': 'Retención emitida', 'nota_credito': 'Nota de crédito'}[data] || '';
                        }
                    },
                    {data: "date_joined"},
                    {data: "valor", class: 'text-right', render: function (data) { return dinero(data); }},
                    {data: "medio_pago.name", render: $.fn.dataTable.render.text()},
                    {data: "referencia", render: $.fn.dataTable.render.text()},
                    {data: "description", render: $.fn.dataTable.render.text()},
                    {
                        data: "puede_borrar",
                        class: 'text-center',
                        orderable: false,
                        render: function (data, type, row) {
                            // Comprobantes de pago del pago (core/adjuntos): permisos y plan los decide el servidor.
                            var botones = row.tipo === 'pago' ? '<button type="button" class="btn btn-outline-secondary btn-xs btn-flat mr-1" data-adjuntos-tipo="pago" data-adjuntos-id="' + parseInt(row.id, 10) + '" title="Comprobantes de pago" aria-label="Comprobantes de pago"><i class="fas fa-paperclip" aria-hidden="true"></i></button>' : '';
                            if (row.tipo === 'pago' && data) {
                                botones += '<a rel="delete" class="btn btn-danger btn-xs btn-flat" title="Eliminar el pago"><i class="fas fa-times"></i></a>';
                            }
                            return botones;
                        }
                    }
                ],
                initComplete: function (settings, json) {
                    $(this).wrap('<div class="dataTables_scroll"><div/>');
                }
            });
            $('#myModalPayments').modal('show');
        });

    $('#tblPayments tbody')
        .off()
        .on('click', 'a[rel="delete"]', function () {
            $('.tooltip').remove();
            var tr = tblPaymentsDebtsPay.cell($(this).closest('td, li')).index(),
                row = tblPaymentsDebtsPay.row(tr.row).data();
            var params = new FormData();
            params.append('id', row.id);
            params.append('action', 'delete_pay');
            var args = {
                'params': params,
                'content': '¿Estas seguro de eliminar el pago? Queda registrado.',
                'success': function (request) {
                    tblPaymentsDebtsPay.ajax.reload();
                }
            };
            submit_with_formdata(args);
        });

    $('#myModalPayments').on('hidden.bs.modal', function () {
        tblDebtsPay.ajax.reload();
    });
});
