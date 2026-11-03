/* Utilidades de presentación: filtros locales, búsqueda y descargas con empresa explícita. */
(function () {
    'use strict';
    const root = document.querySelector('.fp-workspace');
    if (!root) return;
    root.querySelectorAll('.fp-work-cards').forEach(table => {
        const labels = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
        table.querySelectorAll('tbody tr').forEach(row => Array.from(row.cells).forEach((td, i) => {if (!td.hasAttribute('data-label') && td.colSpan === 1) td.dataset.label = labels[i] || '';}));
    });
    function error(texto, recargar) {
        let box = document.getElementById('fpContableError');
        if (!box) {box = document.createElement('div'); box.id = 'fpContableError'; box.className = 'alert alert-danger'; box.setAttribute('role', 'alert'); box.tabIndex = -1; root.querySelector('header').after(box);}
        box.textContent = texto;
        if (recargar) {const b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-outline-secondary d-block mt-2'; b.textContent = 'Recargar la empresa activa'; b.addEventListener('click', () => window.location.reload()); box.append(b);}
        box.focus();
    }
    document.addEventListener('click', async e => {
        const a = e.target.closest('a[data-fp-download]'); if (!a) return;
        e.preventDefault(); if (a.dataset.busy) return;
        const prev = a.textContent; a.dataset.busy = '1'; a.setAttribute('aria-disabled', 'true'); a.textContent = 'Preparando descarga…';
        try {
            const r = await fetch(a.href, {credentials: 'same-origin', cache: 'no-store'});
            if (r.redirected) {error('Tu sesión, acceso o plan cambió. Recarga la página para continuar.', true); return;}
            if (!r.ok) {
                const isJson = (r.headers.get('Content-Type') || '').includes('json');
                const plano = (r.headers.get('Content-Type') || '').startsWith('text/plain');
                const d = isJson ? await r.json() : {error: plano ? await r.text() : 'No se pudo descargar (HTTP ' + r.status + '). Recarga la página.'};
                error(d.error || 'No se pudo descargar.', d.codigo === 'empresa_cambiada' || (r.status === 409 && !isJson)); return;
            }
            const disposition = r.headers.get('Content-Disposition') || '';
            if (!disposition.includes('attachment')) {error('La sesión cambió o la descarga no está disponible. Recarga la página.', true); return;}
            const blob = await r.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
            const filename = /filename\*=UTF-8''([^;]+)|filename="([^"]+)"|filename=([^;]+)/i.exec(disposition);
            link.href = url; link.download = filename ? decodeURIComponent(filename[1] || filename[2] || filename[3]).replace(/[/\\]/g, '-') : 'descarga';
            document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
        } catch (_) {error('No se pudo descargar. Revisa tu conexión y vuelve a intentarlo.', false);}
        finally {a.textContent = prev; a.removeAttribute('aria-disabled'); delete a.dataset.busy;}
    });
    const categoria = document.getElementById('fpRevisionCategoria'), nivel = document.getElementById('fpRevisionNivel');
    if (categoria && nivel) {
        document.getElementById('fpRevisionFiltros').hidden = false;
        function filtrar() {
            let total = 0;
            root.querySelectorAll('[data-categoria]').forEach(section => {
                let visibles = 0;
                section.querySelectorAll('[data-nivel]').forEach(item => {
                    item.hidden = !!((categoria.value && categoria.value !== section.dataset.categoria) || (nivel.value && nivel.value !== item.dataset.nivel));
                    if (!item.hidden) visibles++;
                });
                section.hidden = !visibles; total += visibles;
            });
            document.getElementById('fpRevisionResultado').textContent = total + ' observaciones con estos filtros.';
            document.getElementById('fpRevisionVacio').hidden = !!total;
        }
        categoria.addEventListener('change', filtrar); nivel.addEventListener('change', filtrar); filtrar();
    }
    const buscar = document.getElementById('fpKBusqueda');
    if (buscar) {
        buscar.parentElement.hidden = false;
        const selector = document.getElementById('fpKProducto'), aviso = document.getElementById('fpKBusquedaEstado');
        let timer, control, version = 0;
        buscar.addEventListener('input', () => {
            clearTimeout(timer); if (control) control.abort(); const actual = ++version;
            timer = setTimeout(async () => {
                control = new AbortController(); aviso.textContent = 'Buscando…';
                try {
                    const r = await fetch('/contabilidad/api/kardex/productos/?' + new URLSearchParams({q: buscar.value, empresa: root.dataset.empresa}), {credentials: 'same-origin', signal: control.signal});
                    if (r.redirected) throw new Error('Recarga la página para comprobar tu acceso.');
                    if (!(r.headers.get('Content-Type') || '').includes('json')) throw new Error('No se pudo buscar (HTTP ' + r.status + '). Recarga la página.');
                    const d = await r.json(); if (actual !== version) return;
                    if (!r.ok) {error(d.error || 'No se pudo buscar.', d.codigo === 'empresa_cambiada'); aviso.textContent = 'No se pudo buscar.'; return;}
                    const elegido = selector.selectedOptions[0]?.cloneNode(true);
                    selector.replaceChildren(new Option('Elige un producto inventariado', ''));
                    if (elegido && elegido.value && !d.productos.some(p => String(p.id) === elegido.value)) selector.add(elegido);
                    d.productos.forEach(p => selector.add(new Option(p.codigo + ' · ' + p.nombre, p.id)));
                    if (elegido) selector.value = elegido.value;
                    aviso.textContent = d.productos.length + ' resultados. Elige un producto y pulsa Ver.';
                } catch (e) {if (e.name !== 'AbortError' && actual === version) aviso.textContent = e.message || 'No se pudo buscar.';}
            }, 300);
        });
    }
    const tipo = document.getElementById('fpKTipo'), costo = document.getElementById('fpKCosto');
    if (tipo && costo) {
        function cambioTipo() {const salida = tipo.value === 'salida'; costo.disabled = salida; costo.required = !salida; costo.placeholder = salida ? 'Se calcula al costo promedio' : '0.000000';}
        tipo.addEventListener('change', cambioTipo); cambioTipo();
    }
}());
