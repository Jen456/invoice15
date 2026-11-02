/* Recibos por completar: JavaScript funcional del backend (core/adjuntos/capturas.py). Codex lo rediseña sobre el contrato de
   HANDOFF. Envía cada formulario a la API (JSON), muestra el mensaje del servidor y recarga la lista al terminar. */
(function () {
    'use strict';
    var raiz = document.querySelector('.fp-capturas');
    if (!raiz) return;
    var mensaje = document.getElementById('fpCapturasMensaje');

    function csrf() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        var campo = document.querySelector('[name=csrfmiddlewaretoken]');
        return m ? decodeURIComponent(m[1]) : (campo ? campo.value : '');
    }

    function avisar(texto, error) {
        mensaje.textContent = texto;
        mensaje.className = 'alert ' + (error ? 'alert-danger' : 'alert-success');
        mensaje.focus && mensaje.setAttribute('tabindex', '-1');
        mensaje.focus && mensaje.focus();
    }

    function textoError(datos, defecto) {
        if (!datos) return defecto;
        var texto = datos.error || defecto;
        if (datos.errores) {
            Object.keys(datos.errores).forEach(function (campo) { texto += ' ' + datos.errores[campo].join(' '); });
        }
        return texto;
    }

    function enviar(url, cuerpo, boton, exito) {
        if (boton) boton.disabled = true;
        return fetch(url, {method: 'POST', body: cuerpo, credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}})
            .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, datos: d}; }); })
            .then(function (r) {
                if (!r.ok) { avisar(textoError(r.datos, 'No se pudo guardar.'), true); return; }
                exito(r.datos);
            })
            .catch(function () {
                avisar('No se pudo confirmar la respuesta. Vuelve a cargar la página antes de repetir: el servidor evita duplicados.', true);
            })
            .then(function () { if (boton) boton.disabled = false; });
    }

    var nueva = document.getElementById('fpCapturaNueva');
    if (nueva) {
        nueva.addEventListener('submit', function (e) {
            e.preventDefault();
            var archivo = nueva.elements.archivo.files[0], nota = nueva.elements.nota.value.trim();
            if (!archivo && !nota) { avisar('Adjunta el recibo o escribe una nota (o ambos).', true); return; }
            enviar(raiz.dataset.api, new FormData(nueva), nueva.querySelector('[type=submit]'), function (d) {
                nueva.elements.clave.value = d.clave_sugerida;   // cada envío nuevo lleva su propia clave
                avisar((d.repetido ? 'Ya estaba guardado: ' : 'Guardado: ') + d.captura.numero + '. Queda pendiente de completar.');
                window.setTimeout(function () { window.location.reload(); }, 800);
            });
        });
    }

    raiz.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.dataset.url) return;
        e.preventDefault();
        var boton = form.querySelector('[type=submit]');
        var datos = new FormData(form);
        enviar(form.dataset.url, datos, boton, function (d) {
            var texto = 'Listo.';
            if (form.classList.contains('fp-captura-completar')) texto = 'Gasto registrado: ' + d.gasto.titulo + '. El recibo quedó como su respaldo.';
            else if (form.classList.contains('fp-captura-vincular')) texto = d.ya_adjunto ? 'Vinculado. El archivo ya estaba adjunto a ese documento: no se duplicó.' : 'Vinculado al documento.';
            else if (form.classList.contains('fp-captura-descartar')) texto = 'Recibo descartado. El registro se conserva.';
            else if (form.classList.contains('fp-captura-nota')) texto = 'Nota corregida.';
            avisar(texto);
            window.setTimeout(function () { window.location.reload(); }, 900);
        });
    });

    raiz.addEventListener('input', function (e) {
        if (!e.target.classList.contains('fp-captura-buscar')) return;
        var form = e.target.closest('form'), tipo = form.elements.tipo.value, destino = form.elements.documento_id;
        window.clearTimeout(form._espera);
        form._espera = window.setTimeout(function () {
            fetch('/adjuntos/api/capturas/documentos/?tipo=' + encodeURIComponent(tipo) + '&q=' + encodeURIComponent(e.target.value), {credentials: 'same-origin'})
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    destino.textContent = '';
                    var vacio = document.createElement('option');
                    vacio.value = ''; vacio.textContent = (d.documentos && d.documentos.length) ? 'Elige el documento' : 'Sin resultados';
                    destino.appendChild(vacio);
                    (d.documentos || []).forEach(function (doc) {
                        var o = document.createElement('option');
                        o.value = doc.id;
                        o.textContent = doc.titulo + ' · ' + doc.fecha + (doc.importe ? ' · $' + doc.importe : '') + (doc.tercero ? ' · ' + doc.tercero : '');
                        destino.appendChild(o);
                    });
                });
        }, 300);
    });
}());
