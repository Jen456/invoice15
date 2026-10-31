/* Alta contextual: solo presentación; el servidor valida y guarda el cliente. */
window.fpClienteRapido = (function () {
    'use strict';
    var form, modal, alertBox, matches, save, lookup;
    var busy = false, uncertain = false, searching = false, lookupVersion = 0;
    var opener, finished = false, previousDisabled = new Map();

    function field(name) { return form.elements.namedItem(name); }
    function announce(message) {
        alertBox.textContent = message;
        alertBox.hidden = !message;
    }
    function focus(element) {
        var details = element.closest('details');
        if (details) { details.open = true; }
        element.focus({preventScroll: true});
        // Desplazar solo el cuerpo del diálogo, sin mover la factura que queda detrás.
        var body = form.querySelector('.modal-body');
        if (body.contains(element)) {
            var target = (element.closest('.form-group') || element).getBoundingClientRect();
            var viewport = body.getBoundingClientRect();
            if (target.top < viewport.top || target.height > viewport.height) {
                body.scrollTop += target.top - viewport.top - 8;
            } else if (target.bottom > viewport.bottom) {
                body.scrollTop += target.bottom - viewport.bottom + 8;
            }
        }
    }
    function lockInputs(locked) {
        form.querySelectorAll('input, select, textarea').forEach(function (element) {
            if (locked) {
                if (!previousDisabled.has(element)) { previousDisabled.set(element, element.disabled); }
                element.disabled = true;
            } else if (previousDisabled.has(element)) {
                element.disabled = previousDisabled.get(element);
            }
        });
        if (!locked) { previousDisabled.clear(); }
    }
    function refreshButtons() {
        save.disabled = busy || uncertain || searching;
        lookup.disabled = busy || searching;
        save.textContent = busy ? 'Guardando cliente…' : (uncertain ? 'Comprueba el registro antes de continuar' : 'Guardar y usar cliente');
        lookup.textContent = searching ? 'Buscando cliente…' : 'Buscar cliente con esta identificación';
        form.setAttribute('aria-busy', String(busy || searching));
    }
    function clearErrors() {
        form.querySelectorAll('[data-client-error]').forEach(function (error) { error.textContent = ''; error.hidden = true; });
        announce('');
    }
    function showErrors(errors) {
        clearErrors();
        if (!errors || typeof errors !== 'object' || Array.isArray(errors)) {
            announce(typeof errors === 'string' ? errors : 'No se pudo guardar. Revisa los datos e inténtalo de nuevo.');
            focus(alertBox);
            return;
        }
        var first, general = [];
        Object.keys(errors).forEach(function (name) {
            var messages = Array.isArray(errors[name]) ? errors[name] : [errors[name]];
            var text = messages.map(function (value) { return typeof value === 'string' ? value : value.message || ''; }).join(' ');
            var input = field(name), error = document.getElementById('fp-client-error-' + name);
            if (!input || !error) { general.push(text); return; }
            error.textContent = text;
            error.hidden = false;
            input.classList.add('is-invalid');
            input.setAttribute('aria-invalid', 'true');
            first = first || input;
        });
        announce(general.join(' ') || 'Revisa los campos señalados. Tu factura y lo escrito se conservan.');
        focus(first || alertBox);
    }
    function selectClient(client, created) {
        select_client.select2('trigger', 'select', {data: client});
        fvSale.revalidateField('client');
        var status = document.getElementById('fp-client-status');
        status.textContent = (created ? 'Cliente guardado y seleccionado: ' : 'Cliente seleccionado: ') + client.text + '. Puedes continuar con tu factura.';
        status.hidden = false;
        uncertain = false;
        finished = true;
        modal.modal('hide');
    }
    function validClient(value) {
        return value && value.id && typeof value.text === 'string' && value.identification_type && value.identification_type.id;
    }
    async function post(params) {
        var controller = new AbortController();
        var timeout = window.setTimeout(function () { controller.abort(); }, 25000);
        try {
            var response = await fetch(pathname, {
                method: 'POST', body: params, credentials: 'same-origin', redirect: 'error',
                headers: {'X-CSRFToken': field('csrfmiddlewaretoken').value}, signal: controller.signal
            });
            if (!response.ok) { throw new Error('Respuesta no confirmada'); }
            return await response.json();
        } finally { window.clearTimeout(timeout); }
    }
    async function guardar() {
        if (busy || uncertain || searching || finished || !modal.hasClass('show')) { return; }
        var params = new FormData(form);
        params.set('action', 'create_client');
        clearErrors();
        busy = true;
        lookupVersion += 1;
        matches.hidden = true;
        lockInputs(true);
        refreshButtons();
        var result;
        try {
            result = await post(params);
            if (!Object.prototype.hasOwnProperty.call(result || {}, 'error') && !validClient(result)) {
                throw new Error('Alta no confirmada');
            }
        } catch (_) {
            // Un corte de red no demuestra que el POST no se haya guardado. No repetirlo.
            uncertain = true;
            announce('No recibimos la confirmación del guardado. Busca el cliente con esta identificación antes de continuar. No volveremos a enviarlo automáticamente.');
        } finally {
            busy = false;
            lockInputs(uncertain);
            refreshButtons();
        }
        if (uncertain) { focus(lookup); return; }
        if (Object.prototype.hasOwnProperty.call(result, 'error')) { showErrors(result.error); return; }
        selectClient(result, true);
    }
    async function findClient() {
        if (busy || searching) { return; }
        var number = field('dni').value.trim();
        if (!number) { announce('Escribe una identificación para buscar al cliente.'); focus(field('dni')); return; }
        var version = ++lookupVersion;
        searching = true;
        refreshButtons();
        matches.replaceChildren();
        matches.hidden = false;
        var params = new FormData();
        params.set('action', 'search_client');
        // Misma normalización de espacios que usa la validación existente.
        var foreign = es_identificacion_extranjera(field('identification_type').value);
        params.set('term', foreign ? number.replace(/\s+/g, ' ').toUpperCase() : number.replace(/\s/g, ''));
        try {
            var clients = await post(params);
            if (version !== lookupVersion) { return; }
            if (!Array.isArray(clients) || !clients.every(validClient)) { throw new Error('Búsqueda no confirmada'); }
            var title = document.createElement('p');
            title.textContent = clients.length ? 'Revisa los resultados y elige el cliente correcto.' : (uncertain ? 'Todavía no aparece un cliente con esa identificación. Puedes volver a buscar. No repitas el alta hasta comprobar el resultado con tu administrador.' : 'No encontramos clientes con esa identificación. Puedes completar el formulario para crear uno.');
            matches.appendChild(title);
            clients.forEach(function (client) {
                var row = document.createElement('div');
                row.className = 'fp-client-match';
                var name = document.createElement('strong');
                name.textContent = client.text;
                var use = document.createElement('button');
                use.type = 'button';
                use.className = 'btn btn-outline-secondary';
                use.textContent = 'Usar este cliente';
                use.setAttribute('aria-label', 'Usar ' + client.text);
                use.addEventListener('click', function () { selectClient(client, false); });
                row.append(name, use);
                matches.appendChild(row);
            });
            if (clients.length) { focus(matches.querySelector('button')); }
        } catch (_) {
            if (version === lookupVersion) {
                matches.textContent = 'No pudimos consultar los clientes. Revisa tu conexión y vuelve a buscar. Lo escrito se conserva.';
            }
        } finally { searching = false; refreshButtons(); }
    }
    function identificationHint() {
        var type = field('identification_type').value;
        var descriptions = {'04': 'RUC de 13 dígitos.', '05': 'Cédula de 10 dígitos.', '06': 'Pasaporte: letras, números, espacios o guiones.', '07': 'Consumidor final: 9999999999999.', '08': 'Identificación del exterior: hasta 20 caracteres.'};
        document.getElementById('fp-client-id-help').textContent = descriptions[type] || '';
        field('dni').inputMode = es_identificacion_extranjera(type) ? 'text' : 'numeric';
        lookupVersion += 1;
        matches.hidden = true;
    }
    document.addEventListener('DOMContentLoaded', function () {
        form = document.getElementById('frmClient');
        if (!form) { return; }
        modal = $('#myModalClient');
        alertBox = document.getElementById('fp-client-alert');
        matches = document.getElementById('fp-client-matches');
        save = document.getElementById('fp-client-save');
        lookup = document.getElementById('fp-client-lookup');
        field('names').removeAttribute('autofocus');
        form.querySelectorAll('input:not([type=hidden]), select').forEach(function (input) {
            var error = document.createElement('div');
            error.id = 'fp-client-error-' + input.name;
            error.dataset.clientError = input.name;
            error.className = 'invalid-feedback';
            error.hidden = true;
            input.closest('.form-group').appendChild(error);
            input.setAttribute('aria-describedby', ((input.getAttribute('aria-describedby') || '') + ' ' + error.id).trim());
            input.addEventListener('input', function () {
                var hadServerError = !error.hidden;
                error.hidden = true;
                error.textContent = '';
                input.removeAttribute('aria-invalid');
                if (hadServerError) {
                    input.classList.remove('is-invalid');
                    if (!form.querySelector('[data-client-error]:not([hidden])')) { announce(''); }
                }
                if (input.name === 'dni') { lookupVersion += 1; matches.hidden = true; }
            });
        });
        lookup.addEventListener('click', findClient);
        field('identification_type').addEventListener('change', identificationHint);
        identificationHint();
        fvClient.on('core.form.invalid', function () {
            announce('Revisa los campos señalados antes de guardar.');
            var invalid = form.querySelector('.is-invalid:not([disabled])');
            focus(invalid || alertBox);
        });
        fvClient.on('core.element.validated', function (event) {
            event.element.setAttribute('aria-invalid', String(!event.valid));
            var group = event.element.closest('.form-group');
            var feedback = group.querySelector('[data-field][data-validator]');
            if (feedback) {
                var container = feedback.parentElement;
                container.id = 'fp-client-validation-' + event.field;
                var ids = new Set((event.element.getAttribute('aria-describedby') || '').split(' '));
                ids.add(container.id);
                event.element.setAttribute('aria-describedby', Array.from(ids).join(' '));
            }
        });
        modal.on('show.bs.modal', function () {
            opener = document.activeElement;
            identificationHint();
        }).on('shown.bs.modal', function () {
            focus(uncertain ? lookup : field('identification_type'));
        }).on('hide.bs.modal', function (event) {
            if (busy) { event.preventDefault(); return; }
            // Evita que Bootstrap oculte con aria-hidden el elemento aún enfocado.
            if (form.contains(document.activeElement)) { document.activeElement.blur(); }
        }).on('hidden.bs.modal', function () {
            lookupVersion += 1;
            matches.hidden = true;
            if (finished) {
                lockInputs(false);
                form.reset();
                input_birthdate.datetimepicker('date', input_birthdate.val());
                fvClient.resetForm(false);
                clearErrors();
                matches.hidden = true;
                document.getElementById('fp-client-more').open = false;
                refreshButtons();
                finished = false;
            }
            var target = opener && opener.isConnected && opener !== document.body ? opener : document.querySelector('.btnAddClient');
            if (target) { target.focus(); }
        });
    });
    return {guardar: guardar};
})();
