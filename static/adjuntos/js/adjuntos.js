/* Interfaz core/adjuntos. API y permisos del servidor; no registra/revisa cobros.
   Cada lote conserva documento y metadatos. Nunca reintenta un POST automáticamente. */
(function () {
    'use strict';
    var API = '/adjuntos/api/', $ = window.jQuery;
    var estado = {tipo: null, id: null, datos: null, cambios: false, ocupado: false, version: 0, disparador: null, quitar: null};
    function el(id) { return document.getElementById(id); }
    function nodo(tag, texto, attrs) {
        var n = document.createElement(tag);
        if (texto !== undefined && texto !== null) n.textContent = String(texto);
        Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
        return n;
    }
    function csrf() {
        var campo = el('fpAdjuntosForm').querySelector('[name=csrfmiddlewaretoken]');
        if (campo && campo.value) return campo.value;
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : (typeof window.csrftoken === 'string' ? window.csrftoken : '');
    }
    function mostrar(id, texto) {
        var caja = el(id); caja.textContent = texto || ''; caja.hidden = !texto;
        if (texto && id === 'fpAdjuntosError') caja.focus();
    }
    async function leer(respuesta) {
        var datos;
        try { datos = await respuesta.json(); }
        catch (e) { throw new Error('No se pudo confirmar la respuesta. Consulta los archivos antes de volver a subir.'); }
        if (!respuesta.ok) throw new Error(datos.error || 'No se pudo completar la solicitud.');
        return datos;
    }
    function mensajeError(error, red) { return error instanceof TypeError ? red : (error.message || red); }
    function rutaArchivo(valor) {
        try {
            var u = new URL(valor, window.location.origin);
            return u.origin === window.location.origin && /^\/adjuntos\/\d+\/archivo\/$/.test(u.pathname) ? u.href : '';
        } catch (e) { return ''; }
    }
    function enlaceArchivo(a, descargar) {
        var ruta = rutaArchivo(descargar ? a.url_descarga : a.url);
        if (!ruta) return nodo('span', descargar ? 'Archivo no disponible' : a.nombre);
        return nodo('a', descargar ? 'Descargar' : a.nombre, {
            href: ruta, target: '_blank', rel: 'noopener', class: descargar ? 'btn btn-outline-secondary' : 'fp-adjuntos-file-name',
            'aria-label': (descargar ? 'Descargar ' : 'Abrir en otra pestaña: ') + a.nombre
        });
    }
    function ocupado(valor) {
        var modal = el('fpAdjuntosModal');
        // El botón enfocado se deshabilita: el foco queda en el diálogo para que Escape y Tab sigan funcionando.
        if (valor && modal.contains(document.activeElement)) { modal.focus(); }
        estado.ocupado = valor;
        el('fpAdjuntosCampos').disabled = valor;
        el('fpAdjuntosForm').setAttribute('aria-busy', String(valor));
        el('fpAdjuntosModal').querySelectorAll('[data-dismiss], [data-quitar], #fpAdjuntosQuitar button, #fpAdjMotivo, #fpAdjuntosRecargar, #fpAdjuntosCapturaCampos').forEach(function (n) { n.disabled = valor; });
        if (!valor && document.activeElement === modal) {
            var aviso = el('fpAdjuntosAviso');
            if (!aviso.hidden) { aviso.setAttribute('tabindex', '-1'); aviso.focus(); }
        }
    }
    function tarjeta(a, permisos) {
        var item = nodo('article', null, {class: 'fp-adjuntos-file' + (a.eliminado ? ' fp-adjuntos-eliminado' : '')});
        var head = nodo('div', null, {class: 'fp-adjuntos-file-head'});
        head.appendChild(nodo('i', null, {class: 'fas ' + (a.nota ? 'fa-note-sticky' : (a.tipo_mime === 'application/pdf' ? 'fa-file-pdf' : 'fa-file-image')), 'aria-hidden': 'true'}));
        var nombre = nodo('div'); nombre.appendChild(a.nota ? nodo('strong', 'Nota de respaldo') : enlaceArchivo(a, false));
        nombre.appendChild(nodo('small', a.clase.name + (a.tamano_texto ? ' · ' + a.tamano_texto : '')));
        head.appendChild(nombre);
        if (a.eliminado) head.appendChild(nodo('span', 'Quitado', {class: 'fp-adjuntos-tag'}));
        item.appendChild(head);
        var dl = nodo('dl', null, {class: 'fp-adjuntos-file-meta'});
        [['Referencia', a.referencia || 'Sin referencia'], ['Fecha del comprobante', a.fecha || 'Sin fecha'], ['Importe del comprobante', a.importe ? '$' + a.importe : 'Sin importe']].forEach(function (dato) {
            var grupo = nodo('div'); grupo.appendChild(nodo('dt', dato[0])); grupo.appendChild(nodo('dd', dato[1])); dl.appendChild(grupo);
        });
        item.appendChild(dl);
        if (a.descripcion) item.appendChild(nodo('p', a.descripcion, {class: 'fp-adjuntos-file-description'}));
        item.appendChild(nodo('p', 'Subido por ' + (a.subido_por || '—') + ' · ' + a.subido_en, {class: 'fp-adjuntos-muted'}));
        if (a.eliminado) item.appendChild(nodo('p', 'Quitado el ' + a.eliminado_en + (a.eliminado_por ? ' por ' + a.eliminado_por : '') + (a.eliminado_motivo ? '. Motivo: ' + a.eliminado_motivo : ''), {class: 'fp-adjuntos-file-history'}));
        var acciones = nodo('div', null, {class: 'fp-adjuntos-actions'});
        if (!a.nota) acciones.appendChild(enlaceArchivo(a, true));
        if (!a.eliminado && permisos.quitar) acciones.appendChild(nodo('button', 'Quitar', {type: 'button', class: 'btn btn-outline-danger', 'data-quitar': a.id, 'aria-label': 'Quitar ' + a.nombre}));
        item.appendChild(acciones);
        return item;
    }
    function dibujar(datos, inicial) {
        if (estado.datos && !inicial) {
            var firma = function (d) { return d.adjuntos.map(function (a) { return a.id + ':' + a.eliminado; }).join('|'); };
            if (firma(estado.datos) !== firma(datos)) estado.cambios = true;
        }
        estado.datos = datos;
        var d = datos.documento, doc = el('fpAdjuntosDocumento'), activos = datos.adjuntos.filter(function (a) { return !a.eliminado; });
        doc.textContent = '';
        doc.appendChild(nodo('strong', d.titulo));
        doc.appendChild(nodo('span', d.tercero || ''));
        doc.appendChild(nodo('small', [d.fecha, d.importe ? '$' + d.importe : '', d.medio].filter(Boolean).join(' · ')));
        if (d.requiere && !activos.length) doc.appendChild(nodo('p', 'Falta adjuntar el comprobante del medio de pago registrado.', {class: 'fp-adjuntos-doc-pendiente'}));
        mostrar('fpAdjuntosBloqueo', datos.bloqueo || (!datos.permisos.subir ? 'Puedes consultar los archivos. Tu acceso no permite adjuntar nuevos comprobantes.' : ''));
        var lista = el('fpAdjuntosLista'), historial = el('fpAdjuntosListaHistorial');
        lista.textContent = ''; historial.textContent = '';
        el('fpAdjuntosCuenta').textContent = activos.length + ' de ' + datos.limites.max_por_documento;
        if (!activos.length) lista.appendChild(nodo('p', 'Sin respaldos todavía. Guarda un archivo, una nota o usa un recibo pendiente.', {class: 'fp-adjuntos-empty'}));
        datos.adjuntos.forEach(function (a) { (a.eliminado ? historial : lista).appendChild(tarjeta(a, datos.permisos)); });
        var quitados = datos.adjuntos.length - activos.length;
        el('fpAdjuntosHistorial').hidden = !quitados;
        el('fpAdjuntosCuentaHistorial').textContent = '(' + quitados + ')';
        el('fpAdjuntosForm').hidden = !datos.permisos.subir;
        if (inicial && datos.permisos.subir) {
            var clase = el('fpAdjClase'); clase.textContent = '';
            datos.clases.forEach(function (c) { clase.appendChild(nodo('option', c.name, {value: c.id})); });
            clase.value = d.clase_sugerida || 'transferencia';
            el('fpAdjFecha').value = d.fecha || ''; el('fpAdjImporte').value = d.importe || '';
        }
        el('fpAdjLimites').textContent = datos.limites.formatos + ' · Hasta ' + Math.round(datos.limites.max_bytes / 1048576) + ' MB por archivo · Máximo ' + datos.limites.max_por_documento + ' por documento.';
        el('fpAdjuntosRecargar').hidden = true;
        var pendientes = datos.capturas_pendientes || [], selector = el('fpAdjuntosCaptura');
        selector.textContent = ''; selector.appendChild(nodo('option', 'Elige el recibo guardado', {value: ''}));
        pendientes.forEach(function (c) { selector.appendChild(nodo('option', c.numero + ' · ' + (c.archivo ? c.archivo.nombre : c.nota) + ' · ' + c.creado_en, {value: c.id})); });
        el('fpAdjuntosUsarCaptura').hidden = !datos.permisos.subir || !pendientes.length;
        el('fpAdjuntosCapturaDetalle').textContent = '';
    }
    async function cargar(inicial) {
        var version = estado.version, url = API + estado.tipo + '/' + estado.id + '/';
        try {
            var datos = await fetch(url, {credentials: 'same-origin', cache: 'no-store'}).then(leer);
            if (version !== estado.version) return false;
            dibujar(datos, inicial); return true;
        } catch (e) {
            if (version !== estado.version) return false;
            estado.datos = null;
            el('fpAdjuntosForm').hidden = true;
            el('fpAdjuntosLista').textContent = '';
            el('fpAdjuntosListaHistorial').textContent = '';
            el('fpAdjuntosHistorial').hidden = true;
            el('fpAdjuntosCuenta').textContent = '';
            mostrar('fpAdjuntosError', mensajeError(e, 'No se pudo consultar. Revisa tu conexión y vuelve a consultar.'));
            el('fpAdjuntosRecargar').hidden = false;
            return false;
        }
    }
    function cola() {
        var lista = el('fpAdjuntosCola'); lista.textContent = '';
        var archivos = Array.prototype.slice.call(el('fpAdjArchivo').files || []);
        archivos.forEach(function (a) {
            var li = nodo('li'); li.appendChild(nodo('span', a.name));
            li.appendChild(nodo('small', (a.size / 1048576).toFixed(2) + ' MB · Por subir'));
            lista.appendChild(li);
        });
    }
    async function subir(evento) {
        evento.preventDefault();
        if (estado.ocupado || !estado.datos || !estado.datos.permisos.subir) return;
        var archivos = Array.prototype.slice.call(el('fpAdjArchivo').files || []), limites = estado.datos.limites;
        var nota = el('fpAdjDescripcion').value.trim();
        if (!archivos.length && !nota) { mostrar('fpAdjuntosError', 'Adjunta el recibo o escribe una nota (o ambos).'); return; }
        if (!archivos.length) {
            var datosNota = new FormData(); datosNota.append('nota', nota);
            ['referencia', 'fecha', 'importe'].forEach(function (c) { datosNota.append(c, el('fpAdjuntosForm').elements[c].value); });
            ocupado(true); mostrar('fpAdjuntosError', ''); mostrar('fpAdjuntosAviso', '');
            try {
                await fetch(API + estado.tipo + '/' + estado.id + '/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: datosNota}).then(leer);
                estado.cambios = true; el('fpAdjDescripcion').value = ''; await cargar(false); mostrar('fpAdjuntosAviso', 'Nota de respaldo guardada.');
            } catch (e) {mostrar('fpAdjuntosError', mensajeError(e, 'No se pudo confirmar la nota. Consulta la lista antes de repetir.')); el('fpAdjuntosRecargar').hidden = false;}
            finally {ocupado(false);}
            return;
        }
        var usados = estado.datos.adjuntos.filter(function (a) { return !a.eliminado; }).length;
        if (usados + archivos.length > limites.max_por_documento) { mostrar('fpAdjuntosError', 'Puedes adjuntar hasta ' + limites.max_por_documento + ' archivos por documento. Selecciona menos archivos.'); return; }
        if (archivos.some(function (a) { return a.size > limites.max_bytes; })) { mostrar('fpAdjuntosError', 'Hay archivos que superan ' + Math.round(limites.max_bytes / 1048576) + ' MB. Selecciona archivos más pequeños.'); return; }
        var url = API + estado.tipo + '/' + estado.id + '/', campos = {};
        ['clase', 'referencia', 'fecha', 'importe', 'descripcion'].forEach(function (c) { campos[c] = el('fpAdjuntosForm').elements[c].value; });
        cola(); ocupado(true); mostrar('fpAdjuntosError', ''); mostrar('fpAdjuntosAviso', '');
        var hechos = 0, errores = [], avisos = [], barra = el('fpAdjuntosBarra');
        barra.hidden = false; barra.max = archivos.length; barra.value = 0;
        for (var i = 0; i < archivos.length; i++) {
            var archivo = archivos[i], fila = el('fpAdjuntosCola').children[i], datos = new FormData();
            el('fpAdjuntosProgreso').textContent = 'Subiendo ' + (i + 1) + ' de ' + archivos.length + '…';
            fila.querySelector('small').textContent = 'Subiendo…';
            datos.append('archivo', archivo, archivo.name);
            Object.keys(campos).forEach(function (c) { datos.append(c, campos[c]); });
            try {
                var r = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: datos}).then(leer);
                hechos++; estado.cambios = true;
                fila.querySelector('small').textContent = 'Adjuntado';
                if (r.tambien_en && r.tambien_en.length) avisos.push(archivo.name + ' también está adjunto en: ' + r.tambien_en.map(function (t) { return t.titulo; }).join(', ') + '.');
            } catch (e) {
                fila.querySelector('small').textContent = 'Revisar resultado';
                errores.push(archivo.name + ': ' + mensajeError(e, 'No se pudo confirmar la subida. Revisa la lista antes de intentarlo otra vez.'));
            }
            barra.value = i + 1;
        }
        el('fpAdjArchivo').value = '';
        var actualizado = await cargar(false);
        el('fpAdjuntosProgreso').textContent = 'Finalizado: ' + hechos + ' de ' + archivos.length + ' archivos confirmados.';
        if (hechos) mostrar('fpAdjuntosAviso', hechos + (hechos === 1 ? ' comprobante adjuntado.' : ' comprobantes adjuntados.') + (avisos.length ? ' ' + avisos.join(' ') : ''));
        if (errores.length) mostrar('fpAdjuntosError', errores.join(' ') + (!actualizado ? ' No se pudo actualizar la lista. Vuelve a consultar antes de subir de nuevo.' : ''));
        ocupado(false);   // después de los avisos: el foco pasa al aviso (o se queda en el error)
    }
    function cancelarQuitar() {
        var previo = estado.quitar; estado.quitar = null; el('fpAdjuntosQuitar').hidden = true;
        if (previo && previo.boton.isConnected) previo.boton.focus();
    }
    async function quitar(evento) {
        evento.preventDefault();
        if (estado.ocupado || !estado.quitar || !estado.datos || !estado.datos.permisos.quitar) return;
        var id = estado.quitar.id, datos = new FormData();
        datos.append('motivo', el('fpAdjMotivo').value);
        ocupado(true); mostrar('fpAdjuntosError', ''); mostrar('fpAdjuntosAviso', '');
        try {
            await fetch(API + 'quitar/' + id + '/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: datos}).then(leer);
            estado.cambios = true; estado.quitar = null; el('fpAdjuntosQuitar').hidden = true;
            await cargar(false);
            mostrar('fpAdjuntosAviso', 'Comprobante quitado. El archivo y el motivo se conservan en el historial.');
        } catch (e) {
            mostrar('fpAdjuntosError', mensajeError(e, 'No se pudo confirmar el resultado. Consulta el historial antes de repetir.'));
            el('fpAdjuntosRecargar').hidden = false;
        } finally { ocupado(false); }
    }
    function abrir(tipo, id, disparador) {
        if (estado.ocupado) return;
        var modal = el('fpAdjuntosModal');
        if (!modal || !/^(compra|gasto|pago)$/.test(tipo) || !/^\d+$/.test(String(id))) return;
        estado.version++; estado.tipo = tipo; estado.id = Number(id); estado.datos = null; estado.cambios = false; estado.quitar = null;
        estado.disparador = disparador || document.activeElement;
        el('fpAdjuntosForm').reset(); el('fpAdjuntosForm').hidden = true;
        ['fpAdjuntosQuitar', 'fpAdjuntosHistorial', 'fpAdjuntosBarra', 'fpAdjuntosRecargar', 'fpAdjuntosUsarCaptura'].forEach(function (k) { el(k).hidden = true; });
        el('fpAdjuntosHistorial').open = false;
        ['fpAdjuntosDocumento', 'fpAdjuntosCuenta', 'fpAdjuntosCola', 'fpAdjuntosListaHistorial', 'fpAdjuntosProgreso'].forEach(function (k) { el(k).textContent = ''; });
        mostrar('fpAdjuntosError', ''); mostrar('fpAdjuntosAviso', ''); mostrar('fpAdjuntosBloqueo', '');
        el('fpAdjuntosLista').textContent = '';
        el('fpAdjuntosLista').appendChild(nodo('p', 'Cargando comprobantes…', {class: 'fp-adjuntos-empty'}));
        if ($) $(modal).modal('show');
        cargar(true);
    }
    function preparar() {
        var modal = el('fpAdjuntosModal');
        if (!modal) return;
        el('fpAdjuntosForm').addEventListener('submit', subir);
        el('fpAdjuntosQuitar').addEventListener('submit', quitar);
        el('fpAdjuntosCaptura').addEventListener('change', function () {
            var captura = (estado.datos.capturas_pendientes || []).find(function (c) { return String(c.id) === el('fpAdjuntosCaptura').value; });
            el('fpAdjuntosCapturaDetalle').textContent = captura ? (captura.nota || 'Sin nota') + ' · guardado por ' + captura.creado_por : '';
        });
        el('fpAdjuntosUsarCaptura').addEventListener('submit', async function (e) {
            e.preventDefault(); if (estado.ocupado || !estado.datos || !estado.datos.permisos.subir) return;
            var id = el('fpAdjuntosCaptura').value; if (!id) return;
            var cuerpo = new FormData(); cuerpo.append('tipo', estado.tipo); cuerpo.append('documento_id', estado.id);
            ocupado(true); mostrar('fpAdjuntosError', ''); mostrar('fpAdjuntosAviso', '');
            try {
                var d = await fetch(API + 'capturas/' + id + '/vincular/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}, body: cuerpo}).then(leer);
                estado.cambios = true; await cargar(false); mostrar('fpAdjuntosAviso', d.ya_adjunto ? 'Recibo vinculado: el archivo ya estaba adjunto y no se duplicó.' : 'Recibo vinculado con su mismo archivo o nota.');
            } catch (e) {mostrar('fpAdjuntosError', mensajeError(e, 'No se pudo confirmar el vínculo. Vuelve a consultar.')); el('fpAdjuntosRecargar').hidden = false;}
            finally {ocupado(false);}
        });
        el('fpAdjuntosCancelarQuitar').addEventListener('click', cancelarQuitar);
        el('fpAdjuntosRecargar').addEventListener('click', function () {
            if (estado.ocupado) return;
            mostrar('fpAdjuntosError', ''); cancelarQuitar(); cargar(!estado.datos);
        });
        el('fpAdjArchivo').addEventListener('change', cola);
        var drop = el('fpAdjuntosDrop');
        ['dragenter', 'dragover'].forEach(function (nombre) { drop.addEventListener(nombre, function (e) { e.preventDefault(); if (!estado.ocupado) drop.classList.add('fp-adjuntos-drag'); }); });
        drop.addEventListener('dragleave', function () { drop.classList.remove('fp-adjuntos-drag'); });
        drop.addEventListener('drop', function (e) {
            e.preventDefault(); drop.classList.remove('fp-adjuntos-drag');
            if (!estado.ocupado && estado.datos && estado.datos.permisos.subir && e.dataTransfer.files.length) { el('fpAdjArchivo').files = e.dataTransfer.files; cola(); }
        });
        el('fpAdjuntosLista').addEventListener('click', function (e) {
            var b = e.target.closest('[data-quitar]');
            if (!b || estado.ocupado || !estado.datos || !estado.datos.permisos.quitar) return;
            var id = Number(b.getAttribute('data-quitar')), adjunto = estado.datos.adjuntos.find(function (a) { return a.id === id && !a.eliminado; });
            if (!adjunto) return;
            estado.quitar = {id: id, boton: b};
            el('fpAdjuntosQuitarNombre').textContent = adjunto.nombre;
            el('fpAdjMotivo').value = ''; el('fpAdjuntosQuitar').hidden = false; el('fpAdjMotivo').focus();
        });
        document.addEventListener('click', function (e) {
            var b = e.target.closest && e.target.closest('[data-adjuntos-tipo]');
            if (!b) return;
            e.preventDefault(); abrir(b.getAttribute('data-adjuntos-tipo'), b.getAttribute('data-adjuntos-id'), b);
        });
        function prepararDisparadores() {
            document.querySelectorAll('a[data-adjuntos-tipo]:not([href])').forEach(function (a) {
                a.setAttribute('role', 'button'); a.setAttribute('tabindex', '0');
            });
        }
        prepararDisparadores();
        document.addEventListener('keydown', function (e) {
            var b = e.target.closest && e.target.closest('a[data-adjuntos-tipo]:not([href])');
            if (b && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); b.click(); }
        });
        if ($) {
            $(document).on('draw.dt.fpAdjuntos', prepararDisparadores);
            $(modal).on('show.bs.modal', function () {
                var z = 1050 + 20 * $('.modal.show').length;
                modal.style.zIndex = z;
                setTimeout(function () { $('.modal-backdrop').not('.fp-adjuntos-backdrop').last().addClass('fp-adjuntos-backdrop').css('z-index', z - 5); }, 0);
            }).on('shown.bs.modal', function () {
                modal.querySelector('[data-dismiss]').focus();
            }).on('hide.bs.modal', function (e) {
                if (estado.ocupado) { e.preventDefault(); return; }
                estado.version++;
            }).on('hidden.bs.modal', function () {
                $('.fp-adjuntos-backdrop').remove();
                var parent = $('.modal.show').last();
                if (parent.length) {
                    $('body').addClass('modal-open');
                    var bootstrap = parent.data('bs.modal');
                    if (bootstrap && bootstrap._enforceFocus) bootstrap._enforceFocus();
                }
                if (estado.disparador && estado.disparador.isConnected) estado.disparador.focus();
                document.dispatchEvent(new CustomEvent('fp-adjuntos:cerrado', {detail: {tipo: estado.tipo, id: estado.id, cambios: estado.cambios}}));
            });
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', preparar); else preparar();
    window.fpAdjuntos = {abrir: abrir};
})();
