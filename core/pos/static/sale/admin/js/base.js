/* Reutiliza solo las líneas mediante la consulta de detalle existente y sus permisos. No crea documentos ni reserva números. */
(function () {
    'use strict';

    function preparar(detalles, precioEditable) {
        if (!Array.isArray(detalles) || !detalles.length) {
            throw new Error('No encontramos productos para copiar. Vuelve al listado y elige una factura de esta empresa.');
        }
        const vistos = new Set(), avisos = [];
        let preciosActualizados = 0, impuestosActualizados = 0;
        const lineas = detalles.map(function (detalle) {
            const p = detalle.product || {};
            const cantidad = Number(detalle.cant), descuento = Number(detalle.dscto);
            const original = Number(detalle.price), vigente = Number(p.price_current);
            const precio = precioEditable ? original : vigente;
            if (!Number.isSafeInteger(p.id) || p.id <= 0 || vistos.has(p.id) ||
                !Number.isInteger(cantidad) || cantidad < 1 || cantidad > 999999 ||
                !Number.isInteger(descuento) || descuento < 0 || descuento > 100 ||
                !Number.isFinite(precio) || precio < 0 || precio > 999999.99 ||
                Math.abs(precio * 100 - Math.round(precio * 100)) > .00001 ||
                !Number.isFinite(Number(p.stock)) || !Number.isFinite(Number(p.tarifa))) {
                throw new Error('Una línea de la factura de origen necesita revisión. Crea una factura vacía y agrega sus productos desde el catálogo.');
            }
            vistos.add(p.id);
            if (!precioEditable && original !== vigente) preciosActualizados += 1;
            if (Number(detalle.tarifa) !== Number(p.tarifa)) impuestosActualizados += 1;
            if (p.inventoried && cantidad > Number(p.stock)) {
                avisos.push(String(p.name) + ': copiaste ' + cantidad + ', pero hay ' + p.stock + ' en stock. Revisa la cantidad antes de emitir.');
            }
            // Lista explícita: nunca pasa el id del detalle, cliente, número, autorización, pagos ni archivos de origen.
            return {
                id: p.id, code: String(p.code || ''), name: String(p.name || ''),
                stock: Number(p.stock), inventoried: Boolean(p.inventoried), with_tax: Boolean(p.with_tax),
                tarifa: Number(p.tarifa), nombre_tarifa: String(p.nombre_tarifa || ''),
                cant: cantidad, price_current: precio, dscto: descuento, fp_base: true
            };
        });
        if (preciosActualizados) avisos.push('Tu perfil usa el precio vigente del catálogo: se actualizaron ' + preciosActualizados + ' líneas.');
        if (impuestosActualizados) avisos.push('Se aplicaron las tarifas de IVA actuales del catálogo en ' + impuestosActualizados + ' líneas. Revisa los totales.');
        return {lineas: lineas, avisos: avisos};
    }

    // También permite comprobar la transformación sin navegador ni servicios externos.
    if (typeof module !== 'undefined' && module.exports) { module.exports = {preparar: preparar}; return; }

    $(function () {
        const parametros = new URLSearchParams(window.location.search);
        if (!parametros.has('base')) return;
        const panel = document.getElementById('fp-sale-base');
        if (!panel) return;
        const editor = document.querySelector('.fp-sale-editor');
        const estado = document.getElementById('fp-sale-base-status');
        const lista = document.getElementById('fp-sale-base-warnings');
        const reintentar = document.getElementById('fp-sale-base-retry');
        const formulario = document.getElementById('frmForm');
        const origen = parametros.get('base');
        let listaParaEmitir = false, enCurso = false;

        panel.hidden = false;
        document.getElementById('fp-sale-title').textContent = 'Nueva factura desde otra';

        function bloquear(bloqueado) {
            editor.querySelectorAll('fieldset').forEach(function (campo) {
                campo.disabled = bloqueado;
                campo.inert = bloqueado; // Select2 también debe esperar; sus controles visibles son elementos propios.
            });
            formulario.querySelectorAll('[type="submit"]').forEach(function (boton) { boton.disabled = bloqueado; });
        }

        function informar(texto, error) {
            estado.textContent = texto;
            panel.classList.toggle('has-error', Boolean(error));
        }

        function mostrarAvisos(avisos) {
            lista.replaceChildren();
            avisos.forEach(function (aviso) {
                const item = document.createElement('li');
                item.textContent = aviso;
                lista.appendChild(item);
            });
            lista.hidden = !avisos.length;
        }

        sale.validarBase = function () {
            if (!listaParaEmitir) { estado.focus(); return false; }
            const sinStock = sale.detail.products.find(function (p) { return p.inventoried && p.cant > p.stock; });
            if (sinStock) {
                informar('Revisa la cantidad de ' + sinStock.name + ': hay ' + sinStock.stock + ' en stock.', true);
                estado.focus();
                return false;
            }
            return true;
        };

        function cargar() {
            if (enCurso || listaParaEmitir) return;
            bloquear(true);
            reintentar.hidden = true;
            if (parametros.has('proforma') || !/^[1-9]\d*$/.test(origen) ||
                !Number.isSafeInteger(Number(origen))) {
                informar('El enlace de la factura de origen no es válido. Vuelve al listado para elegirla.', true);
                return;
            }
            if (parametros.get('empresa') !== editor.dataset.company) {
                informar('La empresa activa cambió. Vuelve a Facturas emitidas y elige una factura de la empresa actual.', true);
                return;
            }
            select_client.val(null).trigger('change');
            enCurso = true;
            panel.setAttribute('aria-busy', 'true');
            informar('Cargando productos de la factura de origen…', false);
            $.ajax({
                url: panel.dataset.listUrl, type: 'POST', dataType: 'json', timeout: 20000,
                headers: {'X-CSRFToken': csrftoken}, data: {action: 'search_detail_products', id: origen}
            }).done(function (datos) {
                try {
                    if (!datos || datos.error) throw new Error('No se pudo leer la factura. Comprueba tus permisos o vuelve a intentarlo.');
                    const copia = preparar(datos, sale.precioEditable());
                    sale.detail.products = copia.lineas;
                    select_receipt.val('01').trigger('change');
                    select_receipt.find('option').not('[value="01"]').prop('disabled', true);
                    sale.listProducts();
                    listaParaEmitir = true;
                    bloquear(false);
                    mostrarAvisos(copia.avisos);
                    informar('Productos cargados. Elige el cliente de esta nueva factura; revisa el pago antes de emitir.', false);
                    const ayudaCliente = document.getElementById('fp-client-status');
                    ayudaCliente.textContent = 'Selecciona el cliente para esta nueva factura.';
                    ayudaCliente.hidden = false;
                } catch (error) {
                    informar(error.message, true);
                    reintentar.hidden = false;
                }
            }).fail(function (respuesta) {
                informar(respuesta.status === 403 ? 'Tu perfil no puede consultar la factura de origen.' :
                    'No se pudieron cargar los productos. Comprueba tu conexión y vuelve a intentarlo.', true);
                reintentar.hidden = respuesta.status === 403;
            }).always(function () {
                enCurso = false;
                panel.removeAttribute('aria-busy');
            });
        }
        reintentar.addEventListener('click', cargar);
        cargar();
    });
}());
