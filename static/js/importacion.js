/* Presentación de la importación. Empresa, importes y decisiones fiscales pertenecen al servidor. */
(function () {
    'use strict';
    const root = document.querySelector('.fp-importacion, .fp-importacion-reglas');
    if (!root) return;
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    const api = '/importacion/api/';
    const node = (tag, text, attrs = {}) => {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
        return el;
    };
    function errorBox(error) {
        let box = root.querySelector('#fp-import-error');
        if (!box) {
            box = node('div', '', {id: 'fp-import-error', class: 'alert alert-danger', role: 'alert', tabindex: '-1'});
            root.querySelector('header').after(box);
        }
        box.replaceChildren(node('p', error.message || 'No se pudo completar la solicitud. Revisa el lote antes de volver a subir archivos.'));
        if (error.plan === 'ilimitado') box.append(node('a', 'Conocer Ilimitado y Multiempresa', {href: '/suscripcion/', class: 'btn fpa-btn-pagar'}));
        box.focus();
    }
    async function readResponse(response) {
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error('La respuesta no pudo leerse. Revisa tu conexión y el lote antes de reintentar.'); }
        if (!response.ok) throw Object.assign(new Error(data.error || 'No se pudo completar la solicitud.'), {plan: data.plan});
        return data;
    }
    async function request(path, body) {
        const response = await fetch(api + path, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
            headers: body === undefined ? {} : {'X-CSRFToken': csrf}, body});
        return readResponse(response);
    }
    const tag = (state) => node('span', ({emitido: 'Emitido', recibido: 'Recibido', ajeno: 'Ajeno'})[state.id] || state.nombre, {class: 'fp-import-tag', 'data-state': state.id, title: state.nombre});
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    function messages(container, items, className) {
        (items || []).forEach(item => container.append(node('p', item.texto || item.codigo, {class: className})));
    }
    async function processBatch(id, update) {
        let previous, stalled = 0;
        while (true) {
            const {lote} = await request('lotes/' + id + '/procesar/', new FormData());
            update(lote);
            if (!lote.pendientes) return lote;
            stalled = lote.pendientes === previous ? stalled + 1 : 0;
            if (stalled >= 10) throw new Error('El lote sigue ocupado. Puedes retomar el procesamiento desde su detalle.');
            previous = lote.pendientes;
            await delay(1000);
        }
    }
    // Cada archivo viaja en una petición independiente: como máximo 5 MB + multipart (< 9 MB).
    const upload = document.getElementById('fp-import-upload');
    if (upload) {
        const input = upload.querySelector('[name=archivos]'), drop = document.getElementById('fp-import-drop');
        const section = document.getElementById('fp-import-upload-status'), list = document.getElementById('fp-upload-files');
        const status = document.getElementById('fp-upload-message'), link = document.getElementById('fp-upload-lote');
        let busy = false;
        ['dragenter', 'dragover'].forEach(name => drop.addEventListener(name, event => {event.preventDefault(); drop.classList.add('fp-dragging');}));
        ['dragleave', 'drop'].forEach(name => drop.addEventListener(name, event => {event.preventDefault(); drop.classList.remove('fp-dragging');}));
        drop.addEventListener('drop', event => {
            if (busy) return;
            const transfer = new DataTransfer();
            Array.from(event.dataTransfer.files).forEach(file => transfer.items.add(file));
            input.files = transfer.files;
            input.dispatchEvent(new Event('change'));
        });
        input.addEventListener('change', () => {status.textContent = input.files.length + ' archivos seleccionados.'; section.hidden = false;});
        function send(file, path, progress) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest(), form = new FormData();
                form.append('archivos', file);
                xhr.open('POST', api + path); xhr.setRequestHeader('X-CSRFToken', csrf); xhr.timeout = 180000;
                xhr.upload.onprogress = event => {if (event.lengthComputable) progress.value = Math.round(event.loaded * 100 / event.total);};
                xhr.onerror = xhr.ontimeout = () => reject(new Error('Se interrumpió la conexión. Revisa el lote antes de volver a subir este archivo.'));
                xhr.onload = () => {
                    let data;
                    try {data = JSON.parse(xhr.responseText);} catch (_) {reject(new Error('No se pudo leer la respuesta de subida. Revisa el historial antes de reintentar.')); return;}
                    if (xhr.status < 200 || xhr.status >= 300) reject(Object.assign(new Error(data.error || 'No se pudo subir el archivo.'), {plan: data.plan}));
                    else resolve(data.lote);
                };
                xhr.send(form);
            });
        }
        upload.addEventListener('submit', async event => {
            event.preventDefault(); if (busy) return;
            const files = Array.from(input.files), MB = 1024 * 1024;
            try {
                if (!files.length || files.length > 50) throw new Error('Selecciona entre 1 y 50 archivos.');
                if (files.reduce((sum, file) => sum + file.size, 0) > 60 * MB) throw new Error('El lote supera los 60 MB. Divide la selección en varios lotes.');
                files.forEach(file => {
                    const extension = file.name.split('.').pop().toLowerCase();
                    if (!['xml', 'pdf'].includes(extension)) throw new Error(file.name + ': selecciona un XML o PDF.');
                    if (!file.size || file.size > (extension === 'xml' ? 2 : 5) * MB) throw new Error(file.name + ': archivo vacío o supera el límite de ' + (extension === 'xml' ? '2' : '5') + ' MB.');
                });
                busy = true; input.disabled = true; upload.querySelector('[type=submit]').disabled = true;
                root.querySelector('#fp-import-error')?.remove(); section.hidden = false; list.replaceChildren(); link.hidden = true;
                const rows = files.map((file, index) => {
                    const row = node('li'), title = node('strong', file.name), label = node('span', 'Esperando subida', {role: 'status'});
                    const progress = node('progress', '', {max: '100', value: '0', 'aria-label': 'Subida del archivo ' + (index + 1)});
                    row.append(title, progress, label); list.append(row); return {row, label, progress};
                });
                let lote;
                for (let index = 0; index < files.length; index++) {
                    status.textContent = 'Subiendo archivo ' + (index + 1) + ' de ' + files.length + '. No cierres esta página.';
                    rows[index].label.textContent = 'Subiendo…';
                    try {lote = await send(files[index], lote ? 'lotes/' + lote.id + '/archivos/' : 'lotes/', rows[index].progress);}
                    catch (error) {rows[index].label.textContent = 'Sin confirmar: revisa el lote antes de reintentar.'; throw error;}
                    rows[index].progress.value = 100;
                    const result = lote.entradas[lote.entradas.length - 1];
                    rows[index].label.textContent = result.estado.nombre;
                    messages(rows[index].row, result.errores, 'text-danger');
                    link.href = '/importacion/lotes/' + lote.id + '/'; link.hidden = false;
                }
                status.textContent = 'Archivos subidos. Procesando el lote; algunos PDF o consultas al SRI pueden tardar.';
                lote = await processBatch(lote.id, batch => {
                    status.textContent = 'Procesados: ' + batch.progreso + ' %. Pendientes: ' + batch.pendientes + '.';
                    batch.entradas.forEach((entry, index) => {if (rows[index]) rows[index].label.textContent = entry.estado.nombre;});
                });
                status.textContent = 'Procesamiento finalizado: ' + lote.estado.nombre + '. Abre el lote para revisar errores, duplicados o claves pendientes.';
                link.focus();
            } catch (error) {errorBox(error); status.textContent = 'Importación detenida. Los archivos ya recibidos se conservan en el lote.';}
            finally {busy = false; input.disabled = false; upload.querySelector('[type=submit]').disabled = false;}
        });
    }
    // Continuación del lote. Los formularios de clave siguen funcionando sin JS.
    const process = document.getElementById('fp-import-process');
    const lotId = root.dataset.lote;
    function renderEntries(batch) {
        document.getElementById('fp-lote-description').textContent = batch.estado.nombre + ' · ' + batch.progreso + ' % · ' + batch.total_archivos + ' archivos';
        document.getElementById('fp-lote-progress').value = batch.progreso;
        const tbody = document.getElementById('fp-lote-entries'); tbody.replaceChildren();
        batch.entradas.forEach(entry => {
            const row = node('tr'), detail = node('td', undefined, {'data-label': 'Detalle'});
            row.append(node('td', entry.nombre, {'data-label': 'Archivo'}), node('td', entry.tipo.toUpperCase(), {'data-label': 'Tipo'}), node('td', undefined, {'data-label': 'Estado'}), detail);
            row.children[2].append(tag(entry.estado)); messages(detail, entry.errores, 'text-danger'); messages(detail, entry.advertencias, 'small text-muted');
            if (entry.documento_id) detail.append(node('a', 'Ver documento', {href: '/importacion/documentos/' + entry.documento_id + '/'}));
            if (['pendiente_clave', 'pendiente_xml'].includes(entry.estado.id) && process) detail.append(node('p', 'Actualiza esta página para ingresar o reintentar la clave.', {class: 'small'}));
            tbody.append(row);
        });
    }
    if (process) process.addEventListener('submit', async event => {
        event.preventDefault(); const button = process.querySelector('button'), status = document.getElementById('fp-process-status'); button.disabled = true;
        try {await processBatch(lotId, batch => {renderEntries(batch); status.textContent = 'Avance: ' + batch.progreso + ' %. Pendientes: ' + batch.pendientes;}); location.reload();}
        catch (error) {errorBox(error); button.disabled = false;}
    });
    root.querySelectorAll('.fp-import-clave').forEach(form => form.addEventListener('submit', async event => {
        event.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
        try {await request('entradas/' + form.elements.entrada.value + '/clave/', new FormData(form)); location.reload();}
        catch (error) {errorBox(error); button.disabled = false;}
    }));
    // Bandejas: filtros y paginación reales del servidor, sin cálculos monetarios en el navegador.
    const filters = document.getElementById('fp-import-filters');
    if (filters) {
        filters.hidden = false;
        const select = filters.elements.bandeja, q = filters.elements.q, pagination = document.getElementById('fp-import-pagination');
        const status = document.getElementById('fp-import-filter-status');
        let page = 1, pages = 1, sequence = 0;
        select.value = filters.dataset.bandeja;
        // Tipo a la vista y modificable: ?cod_doc=07 (desde Retenciones recibidas) lo elige al abrir; otro valor se ignora.
        const tipo = filters.elements.cod_doc, pedido = new URLSearchParams(location.search).get('cod_doc') || '';
        if (Array.from(tipo.options).some(opcion => opcion.value === pedido)) tipo.value = pedido;
        async function load(target = 1) {
            const current = ++sequence;
            try {
                const params = new URLSearchParams({bandeja: select.value, q: q.value, pagina: target});
                if (tipo.value) params.set('cod_doc', tipo.value);
                const data = await request('documentos/?' + params);
                if (current !== sequence) return;
                page = data.pagina; pages = data.paginas;
                const tbody = document.getElementById('fp-import-documents'); tbody.replaceChildren();
                data.documentos.forEach(doc => {
                    const row = node('tr');
                    const cell = (label, value) => {const td = node('td', value, {'data-label': label}); row.append(td); return td;};
                    cell('Comprobante').append(node('a', doc.tipo_documento + ' ' + (doc.numero || 'Sin XML'), {href: '/importacion/documentos/' + doc.id + '/'}));
                    cell('Fecha', doc.fecha_emision || '—'); cell('Emisor', doc.emisor.razon_social + ' · ' + doc.emisor.ruc);
                    cell('Total', doc.estados.procesamiento.id === 'pendiente_xml' ? 'Pendiente de XML' : '$' + doc.importes.importe_total);
                    cell('Clasificación').append(tag(doc.estados.clasificacion)); cell('Verificación').append(tag(doc.estados.verificacion)); cell('Revisión', doc.estados.revision.nombre); tbody.append(row);
                });
                if (!data.documentos.length) {const row = node('tr'); row.append(node('td', 'No hay documentos con estos filtros.', {colspan: '7'})); tbody.append(row);}
                pagination.hidden = false; pagination.querySelector('span').textContent = 'Página ' + page + ' de ' + pages;
                pagination.querySelector('[data-page=prev]').disabled = page <= 1; pagination.querySelector('[data-page=next]').disabled = page >= pages;
                status.textContent = data.total + ' documentos encontrados.';
            } catch (error) {errorBox(error);}
        }
        filters.addEventListener('submit', event => {event.preventDefault(); load();});
        pagination.querySelector('[data-page=prev]').addEventListener('click', () => load(page - 1));
        pagination.querySelector('[data-page=next]').addEventListener('click', () => load(page + 1));
        load();
    }
    // Las confirmaciones son casillas explícitas, también en el fallback sin JavaScript.
    const docId = root.dataset.documento;
    if (docId) root.querySelectorAll('.fp-import-action').forEach(form => form.addEventListener('submit', async event => {
        event.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
        const path = 'documentos/' + docId + '/' + (form.elements.accion.value === 'verificar' ? 'verificar/' : 'revisar/');
        try {await request(path, new FormData(form)); location.reload();}
        catch (error) {errorBox(error); button.disabled = false;}
    }));
}());
