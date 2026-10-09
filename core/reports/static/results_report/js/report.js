var input_date_range;
var report = {
    list: function (all) {
        var parameters = {
            'action': 'search_report',
            'start_date': input_date_range.data('daterangepicker').startDate.format('YYYY-MM-DD'),
            'end_date': input_date_range.data('daterangepicker').endDate.format('YYYY-MM-DD'),
        };

        if (all) {
            parameters['start_date'] = '';
            parameters['end_date'] = '';
        }

        $.ajax({
            url: pathname,
            type: 'POST',
            headers: {
                'X-CSRFToken': csrftoken
            },
            data: parameters,
            dataType: 'json',
            success: function (request) {
                if (!request.hasOwnProperty('error')) {
                    fpaGrafico.pastel('container', request.map(function (r) { return r.name; }), request.map(function (r) { return r.y; }), {formato: 'dolares', titulo: 'Compras, ventas y gastos del período'});
                    return false;
                }
                message_error(request.error);
            },
            error: function (jqXHR, textStatus, errorThrown) {
                message_error(errorThrown + ' ' + textStatus);
            }
        });
    }
};

$(function () {

    input_date_range = $('input[name="date_range"]');

    input_date_range
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

    $('.btnSearchAll').on('click', function () {
        report.list(true);
    });

    report.list(false);
});