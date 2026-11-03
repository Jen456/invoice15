/* Importación por claves/reporte y confirmación por partes. No decide criterios fiscales. */
(function () {
    'use strict';
    const root = document.querySelector('.fp-importacion-claves, .fp-importacion-incorporar');
    if (!root) return;
    const csrf = root.querySelector('[name=csrfmiddlewaretoken]')?.value;
    const node = (tag, text, cls) => {const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n;};
    function error(e) {
        let box = root.querySelector('#fp-import-error');
        if (!box) {box = node('div', '', 'alert alert-danger'); box.id = 'fp-import-error'; box.tabIndex = -1; box.setAttribute('role', 'alert'); root.querySelector('header').after(box);}
        box.textContent = e.message || 'No se pudo confirmar la respuesta. Revisa el lote antes de repetir.';
        if (e.plan === 'ilimitado') {const a = node('a', 'Conocer Ilimitado y Multiempresa', 'btn btn-primary d-block mt-2'); a.href = '/suscripcion/'; box.append(a);}
        box.focus();
    }
    async function respuesta(r) {
        if (r.redirected) throw new Error('La sesión o el acceso cambió. Recarga la página antes de continuar.');
        const d = await r.json();
        if (!r.ok) throw Object.assign(new Error(d.error || 'No se pudo completar la solicitud.'), {plan: d.plan});
        return d;
    }
    root.querySelectorAll('#fp-claves-texto, #fp-claves-reporte').forEach(form => {
        form.addEventListener('submit', async e => {
            e.preventDefault(); if (root.dataset.busy || !form.reportValidity()) return;
            const archivo = form.elements.reporte?.files[0];
            if (archivo && archivo.size > 5 * 1048576) {error(new Error('El reporte supera 5 MB.')); return;}
            const data = new FormData(form), button = form.querySelector('[type=submit]');
            root.dataset.busy = '1'; button.disabled = true; button.textContent = 'Leyendo la lista…';
            try {
                const url = '/importacion/api/lotes/' + (archivo ? 'reporte/' : 'claves/');
                const d = await fetch(url, {method: 'POST', body: data, headers: {'X-CSRFToken': csrf}, credentials: 'same-origin'}).then(respuesta);
                const box = document.getElementById('fpMasivaResumen'); box.hidden = false; box.replaceChildren(node('h2', 'Lote #' + d.lote.id + ' preparado'));
                box.append(node('p', d.lista.con_clave + ' claves leídas · ' + d.lista.rechazadas + ' rechazadas · ' + d.lista.omitidas + ' omitidas.'));
                if (d.lista.columnas_desconocidas?.length) box.append(node('p', 'Columnas no reconocidas: ' + d.lista.columnas_desconocidas.join(', ') + '.'));
                const ul = node('ul', '', 'fp-work-list');
                (d.lote.entradas || []).forEach(entrada => (entrada.errores || []).forEach(x => ul.append(node('li', entrada.nombre + ': ' + x.texto))));
                if (ul.children.length) box.append(ul);
                box.append(node('p', 'Abre el lote para consultar los XML al SRI y revisar los resultados antes de incorporarlos.'));
                const a = node('a', 'Continuar con este lote', 'btn btn-primary'); a.href = d.lote.urls.detalle; box.append(a); box.focus();
                // Impide crear otro lote por un segundo clic; el usuario sigue el enlace al creado.
                form.querySelectorAll('input,textarea,button').forEach(n => n.disabled = true); button.textContent = 'Lote creado';
            } catch (e) {error(e); button.disabled = false; button.textContent = archivo ? 'Subir reporte' : 'Consultar en el SRI';}
            finally {delete root.dataset.busy;}
        });
    });
    const drop = document.getElementById('fpReporteDrop');
    if (drop) {
        ['dragenter', 'dragover'].forEach(tipo => drop.addEventListener(tipo, e => {e.preventDefault(); drop.classList.add('is-drag');}));
        drop.addEventListener('dragleave', () => drop.classList.remove('is-drag'));
        drop.addEventListener('drop', e => {e.preventDefault(); drop.classList.remove('is-drag'); const input = document.getElementById('id_reporte'); if (!input.disabled && e.dataTransfer.files.length === 1) input.files = e.dataTransfer.files;});
    }
    const form = document.getElementById('fp-incorporar'); if (!form) return;
    const checks = () => Array.from(form.querySelectorAll('[name=documentos]'));
    const selected = () => checks().filter(c => c.checked).map(c => Number(c.value));
    const confirmacion = document.getElementById('fpIncorporarConfirmacion');
    const confirmar = document.getElementById('fpIncorporarConfirmar'), pausa = document.getElementById('fpIncorporarPausa');
    const volver = document.getElementById('fpIncorporarVolver'), recargar = document.getElementById('fpIncorporarRecargar');
    let envio, busy = false, detener = false, total = 0, tratados = 0;
    const cuenta = () => document.getElementById('fpIncorporarCuenta').textContent = selected().length + ' documentos elegidos';
    document.getElementById('fpIncorporarSeleccion').hidden = false; cuenta();
    form.addEventListener('change', cuenta);
    form.querySelectorAll('[data-seleccion]').forEach(b => b.addEventListener('click', () => {checks().forEach(c => c.checked = b.dataset.seleccion === 'listos' && c.closest('tr').dataset.estado === 'listo'); cuenta();}));
    function bloquear(valor) {form.querySelectorAll('input,select,textarea,button').forEach(n => n.disabled = valor);}
    form.addEventListener('submit', e => {
        e.preventDefault(); if (busy || !form.reportValidity()) return;
        const ids = selected(); if (!ids.length) {error(new Error('Elige al menos un documento.')); return;}
        const datos = new FormData(form), opciones = {}, proveedores = {};
        ['type_expense', 'date_joined'].forEach(k => opciones[k] = datos.get(k) || '');
        ['confirmar_plazo_ats', 'confirmar_sin_verificar', 'confirmar_no_duplicada'].forEach(k => opciones[k] = datos.has(k));
        for (const [key, value] of datos.entries()) {const match = /^proveedor-(\d+)-(mobile|email|parte_relacionada)$/.exec(key); if (match) {(proveedores[match[1]] ||= {})[match[2]] = value;}}
        envio = {documentos: ids, opciones, proveedores}; total = ids.length; tratados = 0;
        document.getElementById('fpIncorporarResumen').textContent = 'Vas a incorporar ' + total + ' documentos con fecha de registro ' + (opciones.date_joined || 'según el servidor') + '.';
        document.getElementById('fpIncorporarResultados').replaceChildren();
        confirmacion.hidden = false; confirmar.disabled = false; confirmar.hidden = false; volver.hidden = false; recargar.hidden = true;
        bloquear(true); confirmacion.focus();
    });
    volver.addEventListener('click', () => {if (!busy) {envio = null; confirmacion.hidden = true; bloquear(false); form.querySelector('[type=submit]').focus();}});
    pausa.addEventListener('click', () => {detener = true; pausa.disabled = true;});
    confirmar.addEventListener('click', async () => {
        if (!envio || busy) return;
        busy = true; detener = false; confirmar.disabled = true; volver.hidden = true; pausa.hidden = false; pausa.disabled = false;
        const progress = document.getElementById('fpIncorporarProgreso'), status = document.getElementById('fpIncorporarAvance');
        progress.hidden = false; progress.max = total;
        try {
            do {
                const prev = envio.documentos.length;
                status.textContent = 'Incorporando: ' + tratados + ' de ' + total + ' tratados…';
                const d = await fetch('/importacion/api/lotes/' + root.dataset.lote + '/incorporar/', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify(envio)}).then(respuesta);
                d.resultados.forEach(r => document.getElementById('fpIncorporarResultados').append(node('li', r.numero + ': ' + r.mensaje, r.resultado === 'error' ? 'text-danger' : '')));
                tratados += d.tratados; progress.value = tratados;
                envio.documentos = d.restantes;
                if (d.restantes.length && d.restantes.length >= prev) throw new Error('No hubo avance. Actualiza la vista previa antes de continuar.');
            } while (envio.documentos.length && !detener);
            status.textContent = tratados + ' de ' + total + ' tratados. ' + (envio.documentos.length ? 'Quedan ' + envio.documentos.length + ' para continuar.' : 'Revisa los resultados de cada documento.');
            confirmar.hidden = !envio.documentos.length; confirmar.textContent = 'Continuar con los restantes';
        } catch (e) {error(e); status.textContent = 'Proceso detenido. Actualiza la vista previa para comprobar lo guardado antes de repetir.'; confirmar.hidden = true;}
        finally {busy = false; confirmar.disabled = false; pausa.hidden = true; recargar.hidden = false;}
    });
    window.addEventListener('beforeunload', e => {if (busy) {e.preventDefault(); e.returnValue = '';}});
}());
