/* Acciones de una proforma (lista y ficha). Los botones salen SOLO de `acciones[]` del servidor. Todo dato que entra en
   el HTML que se arma aquí pasa por fpAcciones.escapar, que también escapa comillas porque va dentro de atributos
   (title, aria-label, href, data-*); $('<div>').text(x).html() no las escapa. Los mensajes se muestran como texto. */
var fpAcciones = {
    config: {url_lista: '/proformas/'},
    despues: function () { location.reload(); },
    actual: null,
    etiquetas: {
        ver: 'Ver', pdf: 'PDF', editar: 'Editar', duplicar: 'Duplicar', enviar_correo: 'Enviar por correo',
        marcar_enviada: 'Marcar como enviada', aceptar: 'Marcar aceptada', rechazar: 'Marcar rechazada', anular: 'Anular',
        facturar: 'Facturar (revisar antes de emitir)', eliminar: 'Eliminar borrador'
    },
    iconos: {
        ver: 'fas fa-eye', pdf: 'fas fa-file-pdf', editar: 'fas fa-edit', duplicar: 'fas fa-copy',
        enviar_correo: 'fas fa-envelope', marcar_enviada: 'fas fa-paper-plane', aceptar: 'fas fa-check',
        rechazar: 'fas fa-times', anular: 'fas fa-ban', facturar: 'fas fa-file-invoice-dollar', eliminar: 'fas fa-trash'
    },
    clases: {
        facturar: 'btn-primary', eliminar: 'btn-danger', anular: 'btn-outline-danger', rechazar: 'btn-outline-danger',
        aceptar: 'btn-success'
    },
    enlaces: {ver: 'ver', pdf: 'pdf', editar: 'editar', facturar: 'facturar', eliminar: 'eliminar'},
    escapar: function (x) {
        return String(x === null || x === undefined ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
    claseEstado: function (id) {
        return {
            borrador: 'badge-secondary', enviada: 'badge-info', aceptada: 'badge-success', rechazada: 'badge-danger',
            vencida: 'badge-warning', facturada: 'badge-primary', anulada: 'badge-dark'
        }[id] || 'badge-light';
    },
    botones: function (p, completos) {
        var esc = fpAcciones.escapar;
        var html = '<div class="fp-acciones btn-group-sm">';
        p.acciones.forEach(function (accion) {
            var etiqueta = esc(fpAcciones.etiquetas[accion] || accion);
            var clase = 'btn btn-flat mb-1 ' + (fpAcciones.clases[accion] || 'btn-outline-secondary');
            var contenido = '<i class="' + fpAcciones.iconos[accion] + '" aria-hidden="true"></i>' + (completos ? ' ' + etiqueta : '');
            var enlace = fpAcciones.enlaces[accion] ? p.urls[fpAcciones.enlaces[accion]] : null;
            if (enlace) {
                html += '<a href="' + esc(enlace) + '" class="' + clase + '" title="' + etiqueta + '" aria-label="' + etiqueta + '"' +
                    (accion === 'pdf' ? ' target="_blank" rel="noopener"' : '') + '>' + contenido + '</a> ';
            } else {
                html += '<button type="button" class="' + clase + '" data-accion="' + esc(accion) + '" data-id="' + esc(p.id) +
                    '" title="' + etiqueta + '" aria-label="' + etiqueta + '">' + contenido + '</button> ';
            }
        });
        if (p.facturar_bloqueado) {
            html += '<button type="button" class="btn btn-flat btn-outline-secondary mb-1" disabled title="' + esc(p.facturar_bloqueado) +
                '" aria-label="Facturar: ' + esc(p.facturar_bloqueado) + '"><i class="fas fa-file-invoice-dollar" aria-hidden="true"></i>' +
                (completos ? ' Facturar' : '') + '</button>';
            if (completos) {
                html += '<p class="small text-muted mb-0">' + esc(p.facturar_bloqueado) + '</p>';
            }
        }
        return html + '</div>';
    },
    error: function (jqXHR) {
        var datos = jqXHR.responseJSON || {};
        message_error(datos.error || 'No se pudo completar la acción.');
    },
    enviar: function (datos, exito) {
        $.ajax({
            url: fpAcciones.config.url_lista, type: 'POST', data: datos, dataType: 'json',
            headers: {'X-CSRFToken': csrftoken},
            beforeSend: function () { loading({'text': '...'}); },
            success: function (respuesta) {
                if (respuesta.error) {
                    message_error(respuesta.error);
                    return;
                }
                exito(respuesta);
            },
            error: fpAcciones.error,
            complete: function () { $.LoadingOverlay('hide'); }
        });
    },
    avisar: function (texto, despues, aviso) {
        Swal.fire({icon: aviso ? 'warning' : 'success', title: aviso ? 'Revisa este aviso' : 'Operación completada', text: texto, confirmButtonText: 'Continuar'}).then(despues || function () {});
    },
    ejecutar: function (accion, p) {
        fpAcciones.actual = p;
        if (accion === 'enviar_correo') {
            $('#fp-modal-correo .fp-numero').text(p.numero);
            $('#fp-destinatarios').val(p.cliente.correo || '');
            $('#fp-mensaje').val('');
            $('#fp-modal-correo').modal('show');
            return;
        }
        if (accion === 'rechazar' || accion === 'anular') {
            $('#fp-modal-motivo').data('accion', accion);
            $('#fp-modal-motivo .fp-titulo-motivo').text(accion === 'anular' ? 'Anular la proforma' : 'Marcar rechazada la proforma');
            $('#fp-modal-motivo .fp-numero').text(p.numero);
            $('#fp-motivo').val('');
            $('#fp-modal-motivo').modal('show');
            return;
        }
        var texto = {
            duplicar: 'Se creará un borrador nuevo con la fecha de hoy. ¿Continuar?',
            marcar_enviada: '¿Marcar la proforma como enviada al cliente?',
            aceptar: '¿Marcar la proforma como aceptada por el cliente?'
        }[accion];
        if (!texto) {
            return;
        }
        dialog_action({
            'content': fpAcciones.escapar(texto),
            'success': function () {
                fpAcciones.enviar({action: accion, id: p.id}, function (respuesta) {
                    if (accion === 'duplicar') {
                        var avisos = (respuesta.avisos || []).join(' ');
                        fpAcciones.avisar(respuesta.mensaje + (avisos ? ' ' + avisos : ''), function () {
                            location.href = respuesta.url_editar;
                        }, avisos !== '');
                        return;
                    }
                    fpAcciones.avisar(respuesta.mensaje, fpAcciones.despues, respuesta.aviso);
                });
            },
            'cancel': function () {}
        });
    },
    iniciar: function (buscar) {
        var nodo = document.getElementById('fp-proforma-config');
        if (nodo) {
            $.extend(fpAcciones.config, JSON.parse(nodo.textContent));
        }
        $(document).on('click', '[data-accion]', function () {
            var p = buscar($(this).data('id'));
            if (p) {
                fpAcciones.ejecutar($(this).data('accion'), p);
            }
        });
        $('#fp-form-correo').on('submit', function (e) {
            e.preventDefault();
            var p = fpAcciones.actual;
            fpAcciones.enviar({
                action: 'enviar_correo', id: p.id, destinatarios: $('#fp-destinatarios').val(), mensaje: $('#fp-mensaje').val()
            }, function (respuesta) {
                $('#fp-modal-correo').modal('hide');
                fpAcciones.avisar(respuesta.mensaje, fpAcciones.despues, respuesta.aviso);
            });
        });
        $('#fp-form-motivo').on('submit', function (e) {
            e.preventDefault();
            var p = fpAcciones.actual;
            fpAcciones.enviar({
                action: $('#fp-modal-motivo').data('accion'), id: p.id, motivo: $('#fp-motivo').val()
            }, function (respuesta) {
                $('#fp-modal-motivo').modal('hide');
                fpAcciones.avisar(respuesta.mensaje, fpAcciones.despues, respuesta.aviso);
            });
        });
    }
};
