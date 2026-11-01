/* Consulta mensual común. Los cobros se leen en su API; nunca pasan por adjuntos. */
(function () {
    'use strict';
    var filtros = document.getElementById('fpRespaldosFiltros');
    if (filtros) {
        var filas = Array.from(document.querySelectorAll('[data-documento]'));
        filtros.hidden = false;
        function filtrar(valor) {
            var visibles = 0;
            filas.forEach(function (fila) {
                fila.hidden = valor !== 'todos' && Number(fila.dataset[valor]) <= 0;
                if (!fila.hidden) visibles++;
            });
            filtros.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.filtro === valor)); });
            document.getElementById('fpRespaldosResultado').textContent = visibles + ' de ' + filas.length + ' documentos';
            document.getElementById('fpRespaldosSinResultados').hidden = visibles !== 0;
        }
        filtros.addEventListener('click', function (e) {
            var boton = e.target.closest('[data-filtro]');
            if (boton) filtrar(boton.dataset.filtro);
        });
        filtrar('todos');
    }
    document.addEventListener('fp-adjuntos:cerrado', function (e) {
        if (e.detail && e.detail.cambios) window.location.reload();
    });

    var modal = document.getElementById('fpConsultaCobro');
    if (!modal || !window.jQuery) return;
    var estado = document.getElementById('fpConsultaCobroEstado');
    var contenido = document.getElementById('fpConsultaCobroContenido');
    var reintentar = document.getElementById('fpConsultaCobroReintentar');
    var disparador, url, peticion, version = 0;
    function nodo(tag, texto, clase) {
        var el = document.createElement(tag);
        if (texto !== undefined && texto !== null) el.textContent = String(texto);
        if (clase) el.className = clase;
        return el;
    }
    function dato(lista, etiqueta, valor) {
        var grupo = nodo('div');
        grupo.append(nodo('dt', etiqueta), nodo('dd', valor || '—'));
        lista.append(grupo);
    }
    function fecha(valor) {
        var f = new Date(valor);
        return valor && !isNaN(f.getTime()) ? f.toLocaleString('es-EC') : '—';
    }
    function pintar(datos) {
        if (!datos.factura || !Array.isArray(datos.respaldos)) throw new Error('No se pudo leer el cobro. Vuelve a consultar.');
        var factura = datos.factura;
        var cabecera = nodo('div', null, 'fp-adjuntos-documento');
        cabecera.append(nodo('strong', 'Factura ' + factura.numero));
        var resumen = nodo('dl', null, 'fp-consulta-cobro-datos');
        dato(resumen, 'Total de la factura', '$' + factura.total);
        dato(resumen, 'Condición', factura.condicion.nombre);
        dato(resumen, 'Medio de cobro', factura.medio_cobro && factura.medio_cobro.nombre);
        if (datos.cuenta_por_cobrar) dato(resumen, 'Saldo por cobrar', '$' + datos.cuenta_por_cobrar.saldo);
        if (factura.anulada_sri) cabecera.append(nodo('p', 'Factura anulada en el SRI.', 'alert alert-warning'));
        cabecera.append(resumen);
        contenido.append(cabecera);
        contenido.append(nodo('h3', 'Respaldos registrados', 'fp-consulta-cobro-subtitulo'));
        if (!datos.respaldos.length) contenido.append(nodo('p', 'Todavía no hay un archivo o una nota de cobro registrados.', 'fp-adjuntos-empty'));
        datos.respaldos.forEach(function (r) {
            var tarjeta = nodo('article', null, 'fp-consulta-cobro-tarjeta');
            tarjeta.append(nodo('h4', '$' + r.importe + ' · ' + r.medio.nombre));
            var revision = nodo('span', r.estado.nombre, 'fp-respaldos-estado');
            revision.dataset.revisionEstado = r.estado.id;
            tarjeta.append(revision);
            if (r.nota) tarjeta.append(nodo('p', r.nota, 'fp-consulta-cobro-nota'));
            if (r.archivo && /^\/cobros\/respaldo\/\d+\/archivo\/$/.test(r.archivo.url)) {
                var enlace = nodo('a', 'Abrir ' + r.archivo.nombre, 'btn btn-outline-secondary');
                enlace.href = r.archivo.url; enlace.target = '_blank'; enlace.rel = 'noopener';
                tarjeta.append(enlace);
            }
            var meta = nodo('dl', null, 'fp-consulta-cobro-datos');
            dato(meta, 'Referencia', r.referencia);
            dato(meta, 'Registrado por', r.registrado_por && (r.registrado_por.nombre || r.registrado_por.username));
            dato(meta, 'Fecha de registro', fecha(r.registrado_en));
            if (r.revisado_por) dato(meta, 'Revisado por', r.revisado_por.nombre || r.revisado_por.username);
            if (r.revisado_en) dato(meta, 'Fecha de revisión', fecha(r.revisado_en));
            if (r.motivo_revision) dato(meta, 'Motivo de revisión', r.motivo_revision);
            tarjeta.append(meta);
            contenido.append(tarjeta);
        });
    }
    async function consultar() {
        if (peticion) peticion.abort();
        peticion = new AbortController();
        var actual = ++version;
        contenido.replaceChildren();
        estado.textContent = 'Consultando respaldos…'; estado.className = 'fp-adjuntos-muted';
        if (document.activeElement === reintentar) modal.querySelector('.close').focus();
        reintentar.hidden = true;
        contenido.setAttribute('aria-busy', 'true');
        try {
            var respuesta = await fetch(url, {credentials: 'same-origin', signal: peticion.signal, headers: {'Accept': 'application/json'}});
            if (!(respuesta.headers.get('Content-Type') || '').includes('application/json')) throw new Error('No se pudo consultar el cobro. Comprueba tu sesión y vuelve a intentarlo.');
            var datos = await respuesta.json();
            if (actual !== version) return;
            if (!respuesta.ok || datos.error) throw new Error(datos.error || 'No se pudo consultar este cobro.');
            pintar(datos);
            estado.textContent = '';
        } catch (error) {
            if (error.name === 'AbortError' || actual !== version) return;
            contenido.replaceChildren();
            estado.textContent = error.message;
            estado.className = 'alert alert-danger';
            reintentar.hidden = false;
        } finally {
            if (actual === version) contenido.setAttribute('aria-busy', 'false');
        }
    }
    document.addEventListener('click', function (e) {
        var boton = e.target.closest('[data-cobros-url]');
        if (!boton || !/^\/cobros\/factura\/\d+\/$/.test(boton.dataset.cobrosUrl)) return;
        disparador = boton; url = boton.dataset.cobrosUrl;
        window.jQuery(modal).modal('show');
        consultar();
    });
    reintentar.addEventListener('click', consultar);
    window.jQuery(modal).on('shown.bs.modal', function () {
        modal.querySelector('.close').focus();
    }).on('hide.bs.modal', function () {
        version++;
        if (peticion) peticion.abort();
        if (modal.contains(document.activeElement)) document.activeElement.blur();
    }).on('hidden.bs.modal', function () {
        contenido.replaceChildren();
        if (disparador && document.contains(disparador)) disparador.focus();
    });
}());
