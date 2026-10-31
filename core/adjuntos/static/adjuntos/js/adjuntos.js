/* Comprobantes de pago adjuntos: modal compartido (templates/adjuntos/_modal.html). fpAdjuntos.abrir(tipo, id).
   Permisos, plan y validación del archivo los decide el servidor (/adjuntos/api/). Texto de terceros siempre como texto. */
(function () {
    'use strict';
    var API = '/adjuntos/api/';
    var estado = {tipo: null, id: null, datos: null, cambios: false, subiendo: false};
    var $ = window.jQuery;

    function csrf() {
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        if (m) return decodeURIComponent(m[1]);
        var campo = document.querySelector('[name=csrfmiddlewaretoken]');
        if (campo) return campo.value;
        return typeof window.csrftoken === 'string' ? window.csrftoken : '';
    }

    function nodo(tag, text, attrs) {
        var el = document.createElement(tag);
        if (text !== undefined && text !== null) el.textContent = String(text);
        Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, String(attrs[k])); });
        return el;
    }

    function el(id) { return document.getElementById(id); }

    function mostrar(id, texto) {
        var caja = el(id);
        if (!caja) return;
        if (!texto) { caja.hidden = true; caja.textContent = ''; return; }
        caja.textContent = texto;
        caja.hidden = false;
        if (id === 'fpAdjuntosError') caja.focus();
    }

    function leer(respuesta) {
        return respuesta.json().catch(function () {
            throw new Error('La respuesta no pudo leerse. Revisa tu conexión y vuelve a intentarlo.');
        }).then(function (datos) {
            if (!respuesta.ok) throw new Error(datos.error || 'No se pudo completar la solicitud.');
            return datos;
        });
    }

    function dinero(valor) { return valor ? '$' + valor : '—'; }

    function filaAdjunto(a, permisos) {
        var tr = nodo('tr', null, a.eliminado ? {class: 'fp-adjuntos-eliminado'} : {});
        tr.appendChild(nodo('td', a.clase.name));
        var celdaArchivo = nodo('td');
        if (a.eliminado) {
            celdaArchivo.appendChild(nodo('span', a.nombre));
        } else {
            celdaArchivo.appendChild(nodo('a', a.nombre, {href: a.url, target: '_blank', rel: 'noopener'}));
        }
        celdaArchivo.appendChild(nodo('small', ' ' + a.tamano_texto, {class: 'text-muted'}));
        if (a.descripcion) celdaArchivo.appendChild(nodo('div', a.descripcion, {class: 'small text-muted'}));
        tr.appendChild(celdaArchivo);
        tr.appendChild(nodo('td', a.referencia || '—'));
        tr.appendChild(nodo('td', a.fecha || '—'));
        tr.appendChild(nodo('td', dinero(a.importe), {class: 'text-right'}));
        var subido = nodo('td');
        subido.appendChild(nodo('span', a.subido_por || '—'));
        subido.appendChild(nodo('div', a.subido_en, {class: 'small text-muted'}));
        if (a.eliminado) subido.appendChild(nodo('div', 'Quitado el ' + a.eliminado_en + (a.eliminado_por ? ' por ' + a.eliminado_por : '') + (a.eliminado_motivo ? ': ' + a.eliminado_motivo : ''), {class: 'small'}));
        tr.appendChild(subido);
        var opciones = nodo('td', null, {class: 'text-nowrap'});
        if (a.eliminado) {
            opciones.appendChild(nodo('span', 'Quitado', {class: 'badge badge-secondary'}));
        } else {
            opciones.appendChild(nodo('a', 'Descargar', {href: a.url_descarga, class: 'btn btn-outline-secondary btn-xs btn-flat mr-1', title: 'Descargar ' + a.nombre}));
            if (permisos.quitar) {
                var quitar = nodo('button', 'Quitar', {type: 'button', class: 'btn btn-danger btn-xs btn-flat', 'data-quitar': a.id});
                opciones.appendChild(quitar);
            }
        }
        tr.appendChild(opciones);
        return tr;
    }

    function dibujar(datos) {
        estado.datos = datos;
        var d = datos.documento;
        var doc = el('fpAdjuntosDocumento');
        doc.textContent = '';
        doc.appendChild(nodo('strong', d.titulo));
        doc.appendChild(nodo('span', ' · ' + d.tercero + (d.fecha ? ' · ' + d.fecha : '') + (d.importe ? ' · $' + d.importe : '') + ' · ' + d.medio));
        if (d.requiere && !datos.adjuntos.some(function (a) { return !a.eliminado; })) {
            doc.appendChild(nodo('div', 'Este documento se pagó por un medio bancario y todavía no tiene comprobante.', {class: 'small font-weight-bold'}));
        }
        mostrar('fpAdjuntosBloqueo', datos.bloqueo);
        var lista = el('fpAdjuntosLista');
        lista.textContent = '';
        if (!datos.adjuntos.length) {
            var vacio = nodo('tr');
            vacio.appendChild(nodo('td', 'Sin comprobantes adjuntos.', {colspan: 7, class: 'text-muted'}));
            lista.appendChild(vacio);
        }
        datos.adjuntos.forEach(function (a) { lista.appendChild(filaAdjunto(a, datos.permisos)); });
        var form = el('fpAdjuntosForm');
        form.hidden = !datos.permisos.subir;
        if (datos.permisos.subir) {
            var clase = el('fpAdjClase');
            clase.textContent = '';
            datos.clases.forEach(function (c) { clase.appendChild(nodo('option', c.name, {value: c.id})); });
            clase.value = d.clase_sugerida || 'transferencia';
            el('fpAdjReferencia').value = '';
            el('fpAdjFecha').value = d.fecha || '';
            el('fpAdjImporte').value = d.importe || '';
            el('fpAdjDescripcion').value = '';
            el('fpAdjArchivo').value = '';
            el('fpAdjLimites').textContent = datos.limites.formatos + ', hasta ' + Math.round(datos.limites.max_bytes / 1048576) + ' MB por archivo y ' + datos.limites.max_por_documento + ' por documento.';
        }
    }

    function cargar() {
        mostrar('fpAdjuntosError', '');
        mostrar('fpAdjuntosAviso', '');
        return fetch(API + estado.tipo + '/' + estado.id + '/', {credentials: 'same-origin'}).then(leer).then(dibujar).catch(function (e) {
            el('fpAdjuntosLista').textContent = '';
            el('fpAdjuntosForm').hidden = true;
            mostrar('fpAdjuntosError', e.message);
        });
    }

    function subirUno(archivo) {
        var datos = new FormData();
        datos.append('archivo', archivo, archivo.name);
        ['clase', 'referencia', 'fecha', 'importe', 'descripcion'].forEach(function (campo) {
            datos.append(campo, el('fpAdjuntosForm').elements[campo].value);
        });
        return fetch(API + estado.tipo + '/' + estado.id + '/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: datos}).then(leer);
    }

    function subir(evento) {
        evento.preventDefault();
        if (estado.subiendo) return;
        var archivos = Array.prototype.slice.call(el('fpAdjArchivo').files || []);
        if (!archivos.length) { mostrar('fpAdjuntosError', 'Elige el archivo del comprobante.'); return; }
        estado.subiendo = true;
        mostrar('fpAdjuntosError', '');
        var progreso = el('fpAdjuntosProgreso'), hechos = 0, avisos = [], errores = [];
        var cadena = Promise.resolve();
        archivos.forEach(function (archivo, i) {
            cadena = cadena.then(function () {
                progreso.textContent = 'Subiendo ' + (i + 1) + ' de ' + archivos.length + '…';
                return subirUno(archivo).then(function (r) {
                    hechos += 1;
                    estado.cambios = true;
                    if (r.tambien_en && r.tambien_en.length) {
                        avisos.push(archivo.name + ' también está adjunto en: ' + r.tambien_en.map(function (t) { return t.titulo; }).join(', ') + '.');
                    }
                }).catch(function (e) { errores.push(archivo.name + ': ' + e.message); });
            });
        });
        cadena.then(function () {
            estado.subiendo = false;
            progreso.textContent = '';
            return cargar().then(function () {
                if (hechos) mostrar('fpAdjuntosAviso', (hechos === 1 ? 'Comprobante adjuntado.' : hechos + ' comprobantes adjuntados.') + (avisos.length ? ' ' + avisos.join(' ') : ''));
                if (errores.length) mostrar('fpAdjuntosError', errores.join(' '));
            });
        });
    }

    function quitar(id) {
        function enviar(motivo) {
            var datos = new FormData();
            datos.append('motivo', motivo || '');
            fetch(API + 'quitar/' + id + '/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: datos})
                .then(leer).then(function () { estado.cambios = true; return cargar(); })
                .then(function () { mostrar('fpAdjuntosAviso', 'Comprobante quitado. Queda registrado quién lo quitó y cuándo.'); })
                .catch(function (e) { mostrar('fpAdjuntosError', e.message); });
        }
        if ($ && $.confirm) {
            $.confirm({
                title: 'Quitar comprobante', theme: 'material', type: 'red', icon: 'fas fa-paperclip', columnClass: 'small', typeAnimated: true,
                content: '<p>El archivo se conserva en el historial con tu usuario y la fecha.</p><label for="fpAdjMotivo">Motivo (opcional)</label><input id="fpAdjMotivo" class="form-control" maxlength="300" autocomplete="off">',
                buttons: {
                    si: {text: 'Quitar', btnClass: 'btn-red', action: function () { enviar(this.$content.find('#fpAdjMotivo').val()); }},
                    no: {text: 'Cancelar', btnClass: 'btn-primary', action: function () {}}
                }
            });
        } else if (window.confirm('¿Quitar este comprobante? Queda registrado en el historial.')) {
            enviar('');
        }
    }

    function abrir(tipo, id) {
        var modal = el('fpAdjuntosModal');
        if (!modal) { window.alert('Esta pantalla no incluye el modal de comprobantes (templates/adjuntos/_modal.html).'); return; }
        estado.tipo = String(tipo);
        estado.id = parseInt(id, 10);
        estado.cambios = false;
        el('fpAdjuntosDocumento').textContent = '';
        el('fpAdjuntosLista').innerHTML = '<tr><td colspan="7" class="text-muted">Cargando…</td></tr>';
        el('fpAdjuntosForm').hidden = true;
        if ($) $(modal).modal('show');
        cargar();
    }

    function preparar() {
        var modal = el('fpAdjuntosModal');
        if (!modal) return;
        el('fpAdjuntosForm').addEventListener('submit', subir);
        el('fpAdjuntosLista').addEventListener('click', function (evento) {
            var boton = evento.target.closest && evento.target.closest('[data-quitar]');
            if (boton) quitar(boton.getAttribute('data-quitar'));
        });
        document.addEventListener('click', function (evento) {
            var disparador = evento.target.closest && evento.target.closest('[data-adjuntos-tipo]');
            if (!disparador) return;
            evento.preventDefault();
            abrir(disparador.getAttribute('data-adjuntos-tipo'), disparador.getAttribute('data-adjuntos-id'));
        });
        if ($) {
            // Modales apilados (Bootstrap 4): este modal se abre encima del de abonos o de pagos.
            $(modal).on('show.bs.modal', function () {
                var z = 1050 + 10 * $('.modal.show').length;
                modal.style.zIndex = z;
                setTimeout(function () { $('.modal-backdrop').not('.fp-adjuntos-backdrop').last().addClass('fp-adjuntos-backdrop').css('z-index', z - 5); }, 0);
            }).on('hidden.bs.modal', function () {
                $('.fp-adjuntos-backdrop').remove();
                if ($('.modal.show').length) $('body').addClass('modal-open');
                document.dispatchEvent(new CustomEvent('fp-adjuntos:cerrado', {detail: {tipo: estado.tipo, id: estado.id, cambios: estado.cambios}}));
            });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', preparar); else preparar();
    window.fpAdjuntos = {abrir: abrir};
})();
