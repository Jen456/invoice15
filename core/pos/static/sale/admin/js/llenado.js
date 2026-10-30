/* Alta contextual con el formulario y los endpoints existentes. No emite ni reserva números. */
(function () {
    'use strict';
    document.addEventListener('DOMContentLoaded', function () {
        const opener = document.querySelector('.fp-open-product');
        const dialog = document.getElementById('fp-product-dialog');
        if (!opener || !dialog || !dialog.showModal) return;
        const form = document.getElementById('fp-product-form');
        const fields = document.getElementById('fp-product-fields');
        const extras = document.getElementById('fp-product-extra-fields');
        const error = document.getElementById('fp-product-error');
        const loading = document.getElementById('fp-product-loading');
        const save = document.getElementById('fp-product-save');
        const status = document.getElementById('fp-product-status');
        const sourceURL = new URL(opener.dataset.productUrl, location.href);
        let busy = false, loaded = false, lookupCode = null, saved = false;
        const essentials = ['name', 'code', 'category', 'pvp', 'tarifa_iva', 'inventoried'];
        function note(text) { status.textContent = text; status.hidden = false; }
        function failure(text) { error.textContent = text; error.hidden = false; error.focus(); }
        function working(value) {
            busy = value; save.disabled = value;
            form.setAttribute('aria-busy', String(value));
            dialog.querySelectorAll('.fp-product-close').forEach(b => b.disabled = value);
        }
        function stockNote() {
            const stock = form.elements.namedItem('inventoried');
            const cost = form.elements.namedItem('price'), price = form.elements.namedItem('pvp');
            if (price && cost) price.min = String(Math.max(0.01, Number(cost.value) || 0));
            document.getElementById('fp-product-stock-note').hidden = !stock || !stock.checked;
            save.textContent = lookupCode ? 'Comprobar producto guardado' : stock && stock.checked ? 'Guardar producto' : 'Guardar y añadir a la factura';
        }
        function clearErrors() {
            error.hidden = true;
            form.querySelectorAll('.fp-field-error').forEach(e => e.remove());
            form.querySelectorAll('[aria-invalid]').forEach(e => {e.removeAttribute('aria-invalid'); e.classList.remove('is-invalid'); e.removeAttribute('aria-describedby');});
        }
        function showErrors(errors) {
            if (!errors || typeof errors !== 'object' || Array.isArray(errors)) { failure(String(errors || 'No se pudo guardar el producto.')); return; }
            let first = null, general = [];
            Object.entries(errors).forEach(([name, messages]) => {
                const input = form.elements.namedItem(name);
                const text = Array.isArray(messages) ? messages.join(' ') : String(messages);
                if (!input || !input.closest) { general.push(text); return; }
                const message = document.createElement('div'); message.className = 'invalid-feedback fp-field-error'; message.id = 'fp-error-' + input.id; message.textContent = text;
                input.closest('.form-group').append(message); input.setAttribute('aria-invalid', 'true'); input.setAttribute('aria-describedby', message.id); input.classList.add('is-invalid');
                if (input.closest('details')) input.closest('details').open = true;
                if (!first) first = input;
            });
            if (general.length) failure(general.join(' '));
            else { failure('Revisa los campos indicados. Tu factura sigue abierta.'); if (first) first.focus(); }
        }
        async function request(url, options) {
            const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 20000);
            try { return await fetch(url, {...options, credentials:'same-origin', signal:controller.signal}); }
            finally { clearTimeout(timer); }
        }
        async function loadForm() {
            loading.hidden = false; form.hidden = true; clearErrors(); working(true);
            try {
                const response = await request(sourceURL, {method:'GET'});
                if (!response.ok || response.redirected || new URL(response.url).pathname !== sourceURL.pathname) throw new Error('No se pudo abrir el formulario. Comprueba tu sesión y el permiso para crear productos.');
                const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
                const original = doc.getElementById('frmForm'); const context = doc.getElementById('fp-product-context');
                const company = document.querySelector('.fp-sale-editor').dataset.company;
                if (!original || !context || context.dataset.company !== company) throw new Error('La empresa activa cambió o el formulario no está disponible. No se ha creado ningún producto.');
                fields.replaceChildren(); extras.replaceChildren();
                original.querySelectorAll('input[type=hidden]').forEach(input => fields.append(input.cloneNode(true)));
                original.querySelectorAll('.card-body .form-group').forEach(group => {
                    const copy = group.cloneNode(true); const control = copy.querySelector('input,select,textarea');
                    if (!control) return;
                    copy.querySelectorAll('script').forEach(e => e.remove());
                    copy.querySelectorAll('[id]').forEach(e => e.id = 'fp-quick-' + e.id);
                    copy.querySelectorAll('label[for]').forEach(e => e.htmlFor = 'fp-quick-' + e.htmlFor);
                    copy.querySelectorAll('[autofocus]').forEach(e => e.removeAttribute('autofocus'));
                    // Selects nativos: no se ejecutan los scripts de la página descargada.
                    copy.querySelectorAll('.select2').forEach(e => e.classList.remove('select2'));
                    if (['name','code'].includes(control.name)) control.minLength = 2;
                    if (['price','pvp'].includes(control.name)) {
                        control.type = 'number'; control.inputMode = 'decimal'; control.step = '0.01';
                        control.min = control.name === 'pvp' ? '0.01' : '0'; control.max = '1000000';
                    }
                    if (control.name === 'inventoried') copy.querySelector('label').textContent = 'Controlar existencias de este producto';
                    (essentials.includes(control.name) ? fields : extras).append(copy);
                });
                if (!form.elements.namedItem('csrfmiddlewaretoken') || !form.elements.namedItem('code')) throw new Error('No se recibieron los campos necesarios. Cierra y vuelve a intentarlo.');
                form.elements.namedItem('name').value = document.querySelector('[name=search_product]').value.trim();
                loaded = true; form.hidden = false; stockNote(); form.elements.namedItem('name').focus();
            } catch (e) { failure(e.message || 'No se pudo cargar el formulario. Tu factura se conserva.'); }
            finally { loading.hidden = true; working(false); }
        }
        async function retrieveProduct() {
            const data = new FormData(); data.set('action','search_product_code'); data.set('code',lookupCode);
            const csrf = document.querySelector('#frmForm [name=csrfmiddlewaretoken]').value;
            const response = await request(location.pathname, {method:'POST',body:data,headers:{'X-CSRFToken':csrf}});
            if (!response.ok || response.redirected) throw new Error('No pudimos consultar el producto. Tu factura se conserva; compruébalo de nuevo.');
            const product = await response.json();
            if (!product.id || product.code !== lookupCode || product.error) throw new Error(saved ? 'El producto se guardó, pero no pudimos recuperarlo. Compruébalo de nuevo, sin repetir el alta.' : 'No pudimos confirmar el registro. Revisa el catálogo antes de intentar crear otro producto con el mismo código.');
            if (!saved) {
                // Una respuesta de guardado perdida no prueba que este registro lo haya creado esta petición.
                note('Encontramos un producto con ese código. Búscalo y revisa sus datos antes de agregarlo. No repetimos el guardado.');
                document.querySelector('[name=search_product]').value = product.code;
            } else if (product.inventoried && Number(product.stock) <= 0) {
                note('Producto creado: ' + product.name + '. No se añadió porque no tiene existencias. Registra su entrada en Bodega antes de venderlo. Los datos de esta factura se conservan.');
            } else {
                product.cant = 1; window.sale.addProduct(product);
                note('Producto creado y añadido: ' + product.name + '. Revisa la cantidad y la tarifa antes de emitir.');
                document.querySelector('[name=search_product]').value = '';
            }
            lookupCode = null; saved = false; loaded = false; dialog.close(); opener.focus();
        }
        opener.addEventListener('click', () => {
            dialog.showModal();
            if (!loaded) loadForm();
            else {stockNote(); form.elements.namedItem('name').focus();}
        });
        dialog.querySelectorAll('.fp-product-close').forEach(b => b.addEventListener('click', () => {if (!busy) dialog.close();}));
        dialog.addEventListener('cancel', e => {if (busy) e.preventDefault();});
        form.addEventListener('change', stockNote);
        form.addEventListener('invalid', e => {const section = e.target.closest('details'); if (section) section.open = true;}, true);
        form.addEventListener('submit', async e => {
            e.preventDefault(); if (busy) return; clearErrors(); working(true);
            try {
                if (lookupCode) {await retrieveProduct(); return;}
                const code = form.elements.namedItem('code').value.trim();
                // Comprobación orientativa; las restricciones del servidor siguen siendo obligatorias.
                for (const pattern of ['code', 'pattern']) {
                    const check = new FormData(form); check.set('action','validate_data'); check.set('pattern',pattern);
                    const answer = await request(sourceURL, {method:'POST',body:check});
                    if (!answer.ok || answer.redirected) throw new Error('No se pudo validar el producto. Revisa tu sesión y vuelve a intentar. No se envió el alta.');
                    const validation = await answer.json();
                    if (validation.valid === false) {
                        showErrors(pattern === 'code' ? {code:['Este código ya existe. Busca el producto en el catálogo.']} : {name:['Ya existe un producto con este nombre en la categoría.']}); return;
                    }
                    if (validation.valid !== true) throw new Error('No se pudo validar el producto. No se envió el alta.');
                }
                let response, result;
                try {
                    response = await request(sourceURL, {method:'POST',body:new FormData(form)});
                    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Respuesta inesperada');
                    result = await response.json();
                } catch (_) {
                    lookupCode = code; failure('No se pudo confirmar el guardado. No lo repetiremos: usa «Comprobar producto guardado» para consultar el código. Tu factura se conserva.'); return;
                }
                if (result && result.error) {showErrors(result.error); return;}
                if (!response.ok || !result || typeof result !== 'object' || Array.isArray(result) || Object.keys(result).length) {
                    lookupCode = code; failure('No se pudo confirmar el guardado. Comprueba el producto antes de repetir el alta.'); return;
                }
                saved = true; lookupCode = code; await retrieveProduct();
            } catch (e) {failure(e.message || 'No se pudo consultar el producto guardado.');}
            finally {working(false); stockNote();}
        });
    });
    // La búsqueda existente conserva sus endpoints, productos y cálculo de importes.
    if (window.jQuery) jQuery(function ($) {
        function documentLabel() {
            const invoice = $('[name=receipt]').val() === '01';
            $('#fp-sale-title').text(invoice ? 'Nueva factura' : 'Nuevo ticket de venta');
            $('#fp-sale-submit-label').text(invoice ? 'Emitir factura' : 'Generar ticket de venta');
        }
        $('[name=receipt]').on('change', documentLabel); documentLabel();
        $('[name=search_product]').on('autocompleteresponse', function (_, ui) {
            document.getElementById('fp-sale-no-results').hidden = !this.value.trim() || ui.content.length !== 0;
        }).on('input autocompleteselect', function () {document.getElementById('fp-sale-no-results').hidden = true;});
    });
})();
