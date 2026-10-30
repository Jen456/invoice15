// Reporte de compras (espec-etapa2-compras §6.I): columnas del listado más el sustento; el pie separa el total con IVA de
// las compras completas (las notas de crédito restan) del subtotal registrado de las incompletas. Texto escapado.
var input_date_range;
var current_date;
var tblReport;
var columns = [];

function esc(valor) {
    return $('<div>').text(valor === null || valor === undefined ? '' : String(valor)).html();
}

function dinero(valor) {
    return valor === null || valor === undefined ? '—' : '$' + valor;
}

var report = {
    totales: function (parameters) {
        $.ajax({
            url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            data: $.extend({}, parameters, {'action': 'totales'})
        }).done(function (data) {
            if (data.error) {
                return;
            }
            $('.fp-total-completas').text('$' + data.completas.total + ' (' + data.completas.cantidad + ' compras completas)');
            $('.fp-total-incompletas').text('$' + data.incompletas.subtotal + ' (' + data.incompletas.cantidad + ' compras con datos incompletos)');
        });
    },
    initTable: function () {
        tblReport = $('#tblReport').DataTable({
            autoWidth: false,
            destroy: true,
        });
        tblReport.settings()[0].aoColumns.forEach(function (value, index, array) {
            columns.push(value.sWidthOrig);
        });
    },
    list: function (all) {
        var parameters = {
            'action': 'search_report',
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
            'fecha': $('#fp-reporte-fecha').val(),
        };
        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }
        report.totales(parameters);
        tblReport = $('#tblReport').DataTable({
            destroy: true,
            autoWidth: false,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: parameters,
                dataSrc: ''
            },
            order: [[0, 'asc']],
            paging: false,
            ordering: true,
            searching: false,
            dom: 'Bfrtip',
            buttons: [
                {
                    extend: 'excelHtml5',
                    text: ' <i class="fas fa-file-excel"></i> Descargar Excel',
                    titleAttr: 'Excel',
                    className: 'btn btn-success btn-flat btn-sm'
                },
                {
                    extend: 'pdfHtml5',
                    text: '<i class="fas fa-file-pdf"></i> Descargar Pdf',
                    titleAttr: 'PDF',
                    className: 'btn btn-danger btn-flat btn-sm',
                    download: 'open',
                    orientation: 'landscape',
                    pageSize: 'LEGAL',
                    customize: function (doc) {
                        doc.styles = {
                            header: {
                                fontSize: 18,
                                bold: true,
                                alignment: 'center'
                            },
                            subheader: {
                                fontSize: 13,
                                bold: true
                            },
                            quote: {
                                italics: true
                            },
                            small: {
                                fontSize: 8
                            },
                            tableHeader: {
                                bold: true,
                                fontSize: 11,
                                color: 'white',
                                fillColor: '#2d4154',
                                alignment: 'center'
                            }
                        };
                        doc.content[1].table.widths = columns;
                        doc.content[1].margin = [0, 35, 0, 0];
                        doc.content[1].layout = {};
                        doc['footer'] = (function (page, pages) {
                            return {
                                columns: [
                                    {
                                        alignment: 'left',
                                        text: ['Fecha de creación: ', {text: current_date}]
                                    },
                                    {
                                        alignment: 'right',
                                        text: ['página ', {text: page.toString()}, ' de ', {text: pages.toString()}]
                                    }
                                ],
                                margin: 20
                            }
                        });

                    }
                }
            ],
            columns: [
                {data: "numero_comprobante", render: $.fn.dataTable.render.text()},
                {data: "tipo_comprobante.name", render: $.fn.dataTable.render.text()},
                {data: "cod_sustento.id", render: $.fn.dataTable.render.text()},
                {data: "provider.name", render: $.fn.dataTable.render.text()},
                {data: "provider.ruc", render: $.fn.dataTable.render.text()},
                {data: "fecha_emision", render: function (data) { return data ? data : '—'; }},
                {data: "date_joined"},
                {data: "payment_type.name", render: $.fn.dataTable.render.text()},
                {
                    data: "subtotal", class: 'text-right',
                    render: function (data, type, row) {
                        return (row.signo === -1 ? '-$' : '$') + Number(data).toFixed(2);
                    }
                },
                {data: "total_iva", class: 'text-right', render: function (data) { return dinero(data); }},
                {
                    data: "total", class: 'text-right',
                    render: function (data, type, row) {
                        return data === null ? '—' : (row.signo === -1 ? '-$' : '$') + data;
                    }
                },
                {
                    data: "datos_incompletos", class: 'text-center',
                    render: function (data, type, row) {
                        var insignias = [];
                        if (row.datos_incompletos && row.version_datos === 1) {
                            insignias.push('Compra anterior · sin IVA');
                        } else if (row.datos_incompletos) {
                            insignias.push('Datos incompletos');
                        }
                        if (row.fuera_plazo_ats) {
                            insignias.push('Fuera del plazo del ATS');
                        }
                        return esc(insignias.join(' · ') || 'Completa');
                    }
                },
            ],

            initComplete: function (settings, json) {
                $(this).wrap('<div class="dataTables_scroll"><div/>');
            }
        });
    }
};

$(function () {

    current_date = new moment().format('YYYY-MM-DD');
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
            report.list(false);
        });

    $('.drp-buttons').hide();

    report.initTable();

    report.list(false);

    $('.btnSearchAll').on('click', function () {
        report.list(true);
    });

    $('#fp-reporte-fecha').on('change', function () {
        report.list(false);
    });
});
