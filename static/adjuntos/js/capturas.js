/* Captura breve. La clave y el contenido se conservan en memoria ante una respuesta perdida.
   No crea documentos hasta completar o vincular; permisos y decisiones son del servidor. */
(function () {
    'use strict';
    const raiz = document.querySelector('.fp-capturas');
    if (!raiz) return;
    const mensaje = document.getElementById('fpCapturasMensaje');
    const nueva = document.getElementById('fpCapturaNueva');
    let pendiente = null, ocupado = false;
    const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    function avisar(texto, error) {
        mensaje.hidden = false;
        mensaje.textContent = texto;
        mensaje.className = 'alert ' + (error ? 'alert-danger' : 'alert-success');
        mensaje.focus();
    }
    function errores(datos, form) {
        let texto = datos.error || 'No se pudo guardar.';
        Object.entries(datos.errores || {}).forEach(([nombre, valor]) => {
            const contenido = Array.isArray(valor) ? valor.join(' ') : String(valor);
            texto += ' ' + contenido;
            const campo = form.elements.namedItem(nombre);
            if (campo && campo.classList) {
                campo.classList.add('is-invalid'); campo.setAttribute('aria-invalid', 'true');
                const detalle = document.createElement('div'); detalle.className = 'invalid-feedback'; detalle.textContent = contenido;
                detalle.id = 'fpCapturaError-' + campo.id; campo.setAttribute('aria-describedby', detalle.id); campo.after(detalle);
            }
        });
        return texto;
    }
    async function leer(r) {
        const datos = await r.json();
        return {ok: r.ok, datos};
    }
    async function refrescar(captura) {
        // Reemplaza solo el recibo afectado; conserva lo escrito en los demás formularios.
        try {
            const r = await fetch('/adjuntos/capturas/?estado=' + encodeURIComponent(raiz.dataset.estado), {credentials: 'same-origin', cache: 'no-store'});
            if (!r.ok || r.redirected) throw new Error();
            const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
            const nuevo = doc.getElementById('captura-' + captura.id), viejo = document.getElementById('captura-' + captura.id);
            const visible = raiz.dataset.estado === 'todas' || raiz.dataset.estado === captura.estado.id;
            if (visible) {
                if (!nuevo) return false;
                if (viejo) viejo.replaceWith(nuevo); else document.getElementById('fpCapturasLista').prepend(nuevo);
            } else if (viejo) viejo.remove();
            const contador = doc.getElementById('fpCapturasPendientes');
            if (contador) document.getElementById('fpCapturasPendientes').textContent = contador.textContent;
            let vacio = document.getElementById('fpCapturasVacio');
            if (!vacio) {vacio = document.createElement('p'); vacio.id = 'fpCapturasVacio'; vacio.className = 'fp-work-empty'; vacio.textContent = 'No hay recibos en este estado.'; document.getElementById('fpCapturasLista').append(vacio);}
            vacio.hidden = !!raiz.querySelector('.fp-captura');
            return true;
        } catch (_) {
            return false;
        }
    }
    async function enviar(form, cuerpo, url) {
        if (ocupado) return;
        ocupado = true;
        form.querySelectorAll('.invalid-feedback').forEach(n => n.remove());
        form.querySelectorAll('[aria-invalid=true]').forEach(n => {n.removeAttribute('aria-invalid'); n.classList.remove('is-invalid');});
        const botones = Array.from(form.querySelectorAll('button[type=submit]'));
        botones.forEach(b => b.disabled = true); form.setAttribute('aria-busy', 'true');
        if (form === nueva) { document.getElementById('fpCapturaCampos').disabled = true; document.getElementById('fpCapturaReintentar').disabled = true; }
        try {
            const {ok, datos} = await fetch(url, {method: 'POST', body: cuerpo, credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}}).then(leer);
            if (!ok) {
                avisar(errores(datos, form), true);
                if (datos.captura) await refrescar(datos.captura);
                if (form === nueva) pendiente = null; // respuesta definitiva: se puede corregir conservando la clave
                return;
            }
            let texto = 'Nota corregida.';
            if (form === nueva) {
                pendiente = null; nueva.reset(); nueva.elements.clave.value = datos.clave_sugerida;
                nueva.elements.archivo.dispatchEvent(new Event('change'));
                texto = (datos.repetido ? 'Ya estaba guardado: ' : 'Guardado: ') + datos.captura.numero + '. Puedes completar sus datos después.';
            } else if (form.classList.contains('fp-captura-completar')) texto = 'Gasto registrado: ' + datos.gasto.titulo + '. Conserva el recibo o la nota como respaldo.';
            else if (form.classList.contains('fp-captura-vincular')) texto = datos.ya_adjunto ? 'Vinculado. El archivo ya estaba adjunto: no se duplicó.' : 'Vinculado al documento existente.';
            else if (form.classList.contains('fp-captura-descartar')) texto = 'Recibo descartado. Su historial se conserva.';
            const actualizado = await refrescar(datos.captura);
            avisar(texto + (actualizado ? '' : ' Recarga la bandeja para ver el estado actualizado.'));
        } catch (_) {
            avisar(form === nueva ? 'No se pudo confirmar la respuesta. Usa «Confirmar el envío pendiente»: conserva la misma clave y el mismo contenido para evitar duplicados. No cierres esta página todavía.' : 'No se pudo confirmar la respuesta. Revisa la bandeja antes de repetir la operación.', true);
        } finally {
            ocupado = false; botones.forEach(b => b.disabled = false); form.removeAttribute('aria-busy');
            if (form === nueva) { document.getElementById('fpCapturaCampos').disabled = !!pendiente; const r = document.getElementById('fpCapturaReintentar'); r.hidden = !pendiente; r.disabled = false; }
        }
    }
    if (nueva) {
        const archivo = nueva.elements.archivo, nota = nueva.elements.nota;
        nueva.addEventListener('submit', e => {
            e.preventDefault();
            if (ocupado) return;
            if (!archivo.files.length && !nota.value.trim()) { avisar('Adjunta el recibo o escribe una nota (o ambos).', true); return; }
            if (!nueva.reportValidity()) return;
            pendiente = pendiente || new FormData(nueva);
            enviar(nueva, pendiente, raiz.dataset.api);
        });
        document.getElementById('fpCapturaReintentar').addEventListener('click', () => {if (pendiente) enviar(nueva, pendiente, raiz.dataset.api);});
        archivo.addEventListener('change', () => {
            const f = archivo.files[0];
            archivo.setCustomValidity(f && f.size > 8 * 1048576 ? 'El archivo supera los 8 MB.' : '');
            document.getElementById('fpCapturaArchivoEstado').textContent = f ? f.name + ' · ' + (f.size / 1048576).toFixed(2) + ' MB' : '';
            document.getElementById('fpCapturaQuitarArchivo').hidden = !f;
        });
        document.getElementById('fpCapturaQuitarArchivo').addEventListener('click', () => {archivo.value = ''; archivo.dispatchEvent(new Event('change')); archivo.focus();});
        const drop = document.getElementById('fpCapturaDrop');
        ['dragenter', 'dragover'].forEach(tipo => drop.addEventListener(tipo, e => {e.preventDefault(); if (!ocupado && !pendiente) drop.classList.add('is-drag');}));
        drop.addEventListener('dragleave', () => drop.classList.remove('is-drag'));
        drop.addEventListener('drop', e => {
            e.preventDefault(); drop.classList.remove('is-drag');
            if (ocupado || pendiente) return;
            if (e.dataTransfer.files.length !== 1) {avisar('Guarda un recibo por vez para completarlo por separado.', true); return;}
            archivo.files = e.dataTransfer.files; archivo.dispatchEvent(new Event('change'));
        });
        window.addEventListener('beforeunload', e => {if (pendiente) {e.preventDefault(); e.returnValue = '';}});
    }
    raiz.addEventListener('submit', e => {
        const form = e.target;
        if (!form.dataset.url) return;
        e.preventDefault();
        if (!form.reportValidity()) return;
        enviar(form, new FormData(form), form.dataset.url);
    });
    function buscar(form) {
        clearTimeout(form._espera);
        if (form._control) form._control.abort();
        const destino = form.elements.documento_id, version = (form._version || 0) + 1;
        form._version = version; destino.replaceChildren(new Option('Buscando…', '')); destino.disabled = true;
        form._espera = setTimeout(async () => {
            const control = new AbortController(); form._control = control;
            try {
                const q = form.querySelector('.fp-captura-buscar').value;
                const r = await fetch('/adjuntos/api/capturas/documentos/?' + new URLSearchParams({tipo: form.elements.tipo.value, q}), {credentials: 'same-origin', signal: control.signal});
                const d = await r.json(); if (version !== form._version) return;
                if (!r.ok) throw new Error(d.error || 'No se pudo buscar.');
                destino.replaceChildren(new Option(d.documentos.length ? 'Elige el documento' : 'Sin resultados', ''));
                d.documentos.forEach(doc => destino.add(new Option(doc.titulo + ' · ' + doc.fecha + (doc.importe ? ' · $' + doc.importe : '') + (doc.tercero ? ' · ' + doc.tercero : ''), doc.id)));
            } catch (error) {
                if (error.name === 'AbortError' || version !== form._version) return;
                destino.replaceChildren(new Option('No se pudo buscar; vuelve a intentarlo', '')); avisar(error.message || 'No se pudo buscar.', true);
            } finally {if (version === form._version) destino.disabled = false;}
        }, 300);
    }
    raiz.addEventListener('toggle', async e => {
        const detalle = e.target, card = detalle.closest('.fp-captura');
        if (!card || !detalle.open || card.dataset.revisado) return;
        card.dataset.revisado = '1';
        try {
            const r = await fetch('/adjuntos/api/capturas/' + card.dataset.captura + '/', {credentials: 'same-origin', cache: 'no-store'});
            const d = await r.json();
            if (!r.ok) {avisar(d.error || 'No se pudo consultar el recibo.', true); delete card.dataset.revisado; return;}
            if (d.captura.mismo_archivo?.length && !card.querySelector('.fp-capture-duplicado')) {
                const aviso = document.createElement('p'); aviso.className = 'alert alert-warning fp-capture-duplicado';
                aviso.textContent = 'Este archivo también aparece en: ' + d.captura.mismo_archivo.map(x => x.titulo).join(', ') + '. Revisa si corresponde vincularlo a un documento existente antes de crear otro.';
                card.querySelector('.card-body').prepend(aviso);
            }
        } catch (_) {delete card.dataset.revisado;}
    }, true);
    raiz.addEventListener('input', e => {if (e.target.matches('.fp-captura-buscar')) buscar(e.target.closest('form'));});
    raiz.addEventListener('change', e => {
        if (e.target.matches('.fp-captura-vincular [name=tipo]')) buscar(e.target.closest('form'));
        if (e.target.name === 'medio_pago') e.target.form.elements.referencia.required = e.target.value === 'cheque';
    });
}());
