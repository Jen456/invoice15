/* UI only. Field names, payloads, financial rules and endpoints remain unchanged. */
(function (window, document) {
    'use strict';
    let errorSequence = 0;

    function message(value) {
        if (Array.isArray(value)) return value.map(message).join(' ');
        if (value && typeof value === 'object') return Object.values(value).map(message).join(' ');
        return value == null ? '' : String(value);
    }

    function clearField(field) {
        if (!field) return;
        const id = field.dataset.fpError;
        if (id) {
            const feedback = document.getElementById(id);
            if (feedback) feedback.remove();
            const descriptions = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(item => item && item !== id);
            if (descriptions.length) field.setAttribute('aria-describedby', descriptions.join(' '));
            else field.removeAttribute('aria-describedby');
            delete field.dataset.fpError;
        }
        if (field.dataset.fpValidity) {
            field.setCustomValidity('');
            delete field.dataset.fpValidity;
        }
        field.removeAttribute('aria-invalid');
        field.classList.remove('is-invalid');
    }

    function fieldError(field, text, nativeValidity) {
        if (!field) return;
        clearField(field);
        if (!text) return;
        const feedback = document.createElement('div');
        feedback.id = 'fp-field-error-' + (++errorSequence);
        feedback.className = 'invalid-feedback fp-field-error';
        feedback.textContent = text;
        const anchor = field.closest('.input-group') || field;
        anchor.insertAdjacentElement('afterend', feedback);
        field.dataset.fpError = feedback.id;
        field.classList.add('is-invalid');
        field.setAttribute('aria-invalid', 'true');
        field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), feedback.id].filter(Boolean).join(' '));
        if (nativeValidity) {
            field.setCustomValidity(text);
            field.dataset.fpValidity = '1';
        }
    }

    function errorBox(form) {
        let box = form.querySelector('[role="alert"]');
        if (!box) {
            box = document.createElement('div');
            box.className = 'fp-alert fp-alert-error';
            box.setAttribute('role', 'alert');
            box.tabIndex = -1;
            (form.querySelector('.modal-body') || form).prepend(box);
        }
        return box;
    }

    function clearErrors(form) {
        form.querySelectorAll('[data-fp-error]').forEach(clearField);
        const box = errorBox(form);
        box.hidden = true;
        box.replaceChildren();
    }

    function errors(form, error, status) {
        clearErrors(form);
        const box = errorBox(form);
        const title = document.createElement('strong');
        title.textContent = status === 403 ? 'No tienes permiso para esta acción.' :
            status === 409 ? 'Los datos de esta pestaña deben revisarse.' : 'Revisa los datos para continuar.';
        box.append(title);
        const list = document.createElement('ul');
        const values = error && typeof error === 'object' && !Array.isArray(error) ? error : {'__all__': error};
        Object.entries(values).forEach(([name, value]) => {
            const text = message(value);
            if (!text) return;
            const field = Array.from(form.elements).find(element => element.name === name && element.type !== 'hidden');
            if (field) fieldError(field, text, false);
            const li = document.createElement('li');
            if (field && field.id) {
                const link = document.createElement('a');
                link.href = '#' + field.id;
                link.textContent = text;
                link.addEventListener('click', function (event) { event.preventDefault(); field.focus(); });
                li.append(link);
            } else li.textContent = text;
            list.append(li);
        });
        box.append(list);
        if (status === 409) {
            const reload = document.createElement('button');
            reload.type = 'button';
            reload.className = 'btn fp-btn-secondary';
            reload.textContent = 'Recargar la página';
            reload.addEventListener('click', function () {
                if (window.confirm('Al recargar se perderán los datos sin guardar. Comprueba la empresa activa antes de volver a ingresar información.')) window.location.reload();
            });
            box.append(reload);
        }
        box.hidden = false;
        box.focus();
    }

    function validateCredit(form) {
        const condition = form.elements.namedItem('payment_type');
        const due = form.elements.namedItem('end_credit');
        const issued = form.elements.namedItem('date_joined');
        if (!condition || !due) return true;
        const credit = condition.value === 'credito';
        due.required = credit;
        clearField(due);
        if (!credit) return true;
        let error = '';
        const date = due.value.trim();
        if (!date) error = 'Indica el vencimiento del crédito.';
        else if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date) error = 'Ingresa una fecha válida en formato AAAA-MM-DD.';
        else if (issued && /^\d{4}-\d{2}-\d{2}$/.test(issued.value) && date < issued.value) error = 'El vencimiento no puede ser anterior a la fecha de emisión.';
        if (error) fieldError(due, error, true);
        return !error;
    }

    function submit(args, form) {
        if (form.dataset.fpBusy) return;
        if (form.id === 'frmForm' && !validateCredit(form)) { form.reportValidity(); return; }
        if (!form.reportValidity()) return;
        const invoice = form.id === 'frmForm';
        form.dataset.fpBusy = 'confirming';
        function cancel() { delete form.dataset.fpBusy; }
        function send() {
            clearErrors(form);
            form.dataset.fpBusy = 'sending';
            form.setAttribute('aria-busy', 'true');
            const buttons = Array.from(form.querySelectorAll('button[type="submit"]')).map(button => ({button, disabled: button.disabled}));
            buttons.forEach(item => { item.button.disabled = true; });
            const status = document.getElementById('fp-sale-status');
            if (invoice && status) status.textContent = 'Enviando la factura. Espera la respuesta antes de volver a intentarlo.';
            const csrf = form.querySelector('[name="csrfmiddlewaretoken"]');
            window.jQuery.ajax({
                url: window.location.pathname, type: 'POST', data: args.params,
                processData: false, contentType: false, dataType: 'json',
                headers: {'X-CSRFToken': csrf ? csrf.value : window.getCookie('csrftoken')},
                success: function (data) {
                    if (Object.prototype.hasOwnProperty.call(data, 'error')) {
                        errors(form, data.errors || data.errores || data.error);
                    } else if (args.success) args.success(data);
                },
                error: function (xhr) {
                    const data = xhr.responseJSON || {};
                    const fallback = xhr.status === 403 ? 'Solicita a tu administrador el acceso necesario.' :
                        xhr.status === 409 ? 'Comprueba la empresa activa y recarga esta página.' :
                        invoice ? 'No se pudo confirmar la respuesta. Conservamos lo escrito. Consulta la lista de facturas antes de repetir el envío.' :
                        'No se pudo confirmar el guardado. Conservamos tus datos; comprueba si el registro ya existe antes de repetir.';
                    errors(form, data.errors || data.errores || data.error || fallback, xhr.status);
                },
                complete: function () {
                    delete form.dataset.fpBusy;
                    form.removeAttribute('aria-busy');
                    buttons.forEach(item => { item.button.disabled = item.disabled; });
                    if (invoice && status) status.textContent = '';
                }
            });
        }
        if (invoice) window.dialog_action({title: 'Revisa antes de generar', content: 'Se enviarán los datos de esta factura. ¿Deseas continuar?', success: send, cancel: cancel});
        else send();
    }

    document.addEventListener('DOMContentLoaded', function () {
        const form = document.getElementById('frmForm');
        if (!form || !form.classList.contains('fp-sale-form')) return;
        const note = form.elements.namedItem('payment_note');
        const attachment = form.elements.namedItem('payment_attachment');
        const condition = form.elements.namedItem('payment_type');
        // Preserve the historical value required by this backend, clarify its label.
        Array.from(condition.options).forEach(option => {
            if (option.value === 'efectivo') option.textContent = 'Contado';
        });
        function updateAttachment() {
            clearField(attachment);
            const file = attachment.files[0];
            document.getElementById('fp-attachment-status').textContent = file ? file.name + ' · seleccionado, todavía no enviado.' : 'No has seleccionado un archivo.';
            document.getElementById('fp-remove-attachment').hidden = !file;
            let error = '';
            if (file && file.size > 10 * 1024 * 1024) error = 'El archivo no debe superar 10 MB.';
            else if (file && !/\.(pdf|jpe?g|png)$/i.test(file.name)) error = 'Selecciona un PDF, JPG o PNG.';
            if (error) fieldError(attachment, error, true);
        }
        note.addEventListener('input', function () { document.getElementById('fp-note-count').textContent = note.value.length + ' / 300'; });
        attachment.addEventListener('change', updateAttachment);
        document.getElementById('fp-remove-attachment').addEventListener('click', function () { attachment.value = ''; updateAttachment(); attachment.focus(); });
        document.addEventListener('invalid', function (event) {
            if (event.target.closest('.fp-sale-form,.fp-dialog') && !event.target.dataset.fpError) fieldError(event.target, event.target.validationMessage, false);
        }, true);
        document.addEventListener('input', function (event) {
            if (event.target.closest('.fp-sale-form,.fp-dialog') && event.target.name !== 'payment_attachment') clearField(event.target);
        }, true);
        window.jQuery(form).on('change', '[name="payment_type"],[name="end_credit"],[name="date_joined"]', function () {
            validateCredit(form);
            document.getElementById('fp-payment-guidance').textContent = form.elements.namedItem('payment_type').value === 'credito' ?
                'Esta factura queda pendiente de pago. La promesa, la nota y el adjunto no registran un abono.' :
                'La nota y el adjunto son opcionales. Si el pago está pendiente, selecciona Crédito e indica el vencimiento.';
        });
        window.jQuery('.fp-dialog').on('show.bs.modal', function () {
            this.fpReturnFocus = document.activeElement;
        }).on('shown.bs.modal', function () {
            const first = this.querySelector('input:not([type="hidden"]),select,textarea');
            if (first) first.focus();
        }).on('hidden.bs.modal', function () {
            if (this.fpReturnFocus && this.fpReturnFocus.isConnected) this.fpReturnFocus.focus();
        });
        window.jQuery('#tblProducts').on('draw.dt', function () {
            const count = window.sale.detail.products.length;
            document.getElementById('fp-product-count').textContent = count ? count + (count === 1 ? ' producto en el detalle' : ' productos en el detalle') : 'Sin productos todavía';
        });
    });
    window.FPSaleUX = {errors, clearErrors, fieldError, clearField, validateCredit, submit};
}(window, document));
