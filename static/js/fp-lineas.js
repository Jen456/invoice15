/* Líneas de factura y proforma (presentación): ordenar las filas con su asa ⋮⋮ (ratón, dedo o lápiz con Pointer Events;
   flechas arriba/abajo, Inicio y Fin con el asa enfocada; botones «Subir» y «Bajar») y la descripción editable de cada
   línea (sin saltos de línea ni caracteres de control, hasta 300 caracteres con aviso). Aquí no se calcula ni se envía nada:
   quien lo usa reordena SU lista de líneas (la fuente de verdad) en `mover(desde, hasta)` y vuelve a dibujar la tabla. */
(function (raiz) {
    'use strict';

    var MAX_DESCRIPCION = 300;
    var CONTROL = /[\u0000-\u001F\u007F-\u009F]/g;

    function filas(tabla) {
        var cuerpo = tabla.tBodies[0];
        return cuerpo ? Array.prototype.filter.call(cuerpo.rows, function (f) {
            return !f.querySelector('td.dataTables_empty');
        }) : [];
    }

    function mitad(fila) {
        var r = fila.getBoundingClientRect();
        return r.top + r.height / 2;
    }

    // opciones: mover(desde, hasta) reordena la lista y redibuja (obligatorio); redibujar() vuelve a pintar la lista tal
    // como está (al cancelar un arrastre); nombre(indice) para el aviso; anuncio: elemento aria-live (se crea si falta).
    function ordenar(tabla, opciones) {
        if (!tabla || tabla.getAttribute('data-fp-orden') === '1') return;
        tabla.setAttribute('data-fp-orden', '1');
        var vivo = opciones.anuncio;
        if (!vivo) {
            vivo = document.createElement('p');
            vivo.className = 'sr-only';
            vivo.setAttribute('aria-live', 'polite');
            vivo.setAttribute('aria-atomic', 'true');
            var caja = tabla.closest('.fp-sale-lines, .table-responsive') || tabla;
            caja.parentNode.insertBefore(vivo, caja.nextSibling);
        }

        function anunciar(texto) {
            vivo.textContent = '';
            setTimeout(function () { vivo.textContent = texto; }, 60);
        }

        function indiceDe(nodo) {
            return filas(tabla).indexOf(nodo && nodo.closest('tr'));
        }

        function enfocar(indice, selector) {
            var fila = filas(tabla)[indice];
            if (!fila) return;
            var destino = fila.querySelector(selector);
            if (!destino || destino.disabled) destino = fila.querySelector('.fp-asa');
            if (destino) destino.focus({preventScroll: false});
        }

        function mover(desde, hasta, selector) {
            var total = filas(tabla).length;
            if (desde < 0 || hasta < 0 || hasta >= total || desde === hasta) return;
            opciones.mover(desde, hasta);
            enfocar(hasta, selector);
            anunciar((opciones.nombre ? opciones.nombre(hasta) + ': ' : 'Línea movida: ') + 'posición ' + (hasta + 1) +
                ' de ' + total + '.');
        }

        tabla.addEventListener('keydown', function (e) {
            var asa = e.target.closest ? e.target.closest('.fp-asa') : null;
            if (!asa || !tabla.contains(asa) || e.altKey || e.ctrlKey || e.metaKey) return;
            var i = indiceDe(asa), n = filas(tabla).length, destino = null;
            if (e.key === 'ArrowUp') destino = i - 1;
            else if (e.key === 'ArrowDown') destino = i + 1;
            else if (e.key === 'Home') destino = 0;
            else if (e.key === 'End') destino = n - 1;
            if (destino === null) return;
            e.preventDefault();
            mover(i, Math.max(0, Math.min(n - 1, destino)), '.fp-asa');
        });

        tabla.addEventListener('click', function (e) {
            var boton = e.target.closest ? e.target.closest('[data-mover]') : null;
            if (!boton || !tabla.contains(boton) || boton.disabled) return;
            var paso = Number(boton.getAttribute('data-mover')), i = indiceDe(boton);
            mover(i, i + paso, '[data-mover="' + paso + '"]');
        });

        // Arrastre: la fila tomada no sale del DOM (se mueven sus vecinas), así el puntero capturado no se pierde.
        var arrastre = null;

        function alMover(e) {
            if (!arrastre || e.pointerId !== arrastre.id) return;
            if (!arrastre.movida) {
                if (Math.abs(e.clientY - arrastre.y) < 5) return;   // un clic sobre el asa no es un arrastre
                arrastre.movida = true;
                arrastre.fila.classList.add('fp-fila-arrastrada');
                tabla.classList.add('fp-tabla-arrastrando');
            }
            e.preventDefault();
            var fila = arrastre.fila, y = e.clientY;
            var previa = fila.previousElementSibling, siguiente = fila.nextElementSibling;
            if (previa && y < mitad(previa)) {
                fila.parentNode.insertBefore(previa, fila.nextSibling);
            } else if (siguiente && y > mitad(siguiente)) {
                fila.parentNode.insertBefore(siguiente, fila);
            }
            if (y < 64) { window.scrollBy(0, -18); } else if (y > window.innerHeight - 64) { window.scrollBy(0, 18); }
        }

        function terminar(cancelar) {
            if (!arrastre) return;
            var a = arrastre;
            arrastre = null;
            document.removeEventListener('pointermove', alMover);
            document.removeEventListener('pointerup', alSoltar);
            document.removeEventListener('pointercancel', alCancelar);
            document.removeEventListener('keydown', alEscape, true);
            a.fila.classList.remove('fp-fila-arrastrada');
            tabla.classList.remove('fp-tabla-arrastrando');
            if (!a.movida) return;
            var hasta = indiceDe(a.fila);
            if (cancelar || hasta === a.desde || hasta < 0) {
                if (opciones.redibujar) opciones.redibujar();
                enfocar(a.desde, '.fp-asa');
                if (cancelar) anunciar('Orden sin cambios.');
                return;
            }
            mover(a.desde, hasta, '.fp-asa');
        }

        function alSoltar(e) { if (arrastre && e.pointerId === arrastre.id) terminar(false); }
        function alCancelar(e) { if (arrastre && e.pointerId === arrastre.id) terminar(true); }
        function alEscape(e) {
            if (e.key === 'Escape' && arrastre) { e.preventDefault(); e.stopPropagation(); terminar(true); }
        }

        tabla.addEventListener('pointerdown', function (e) {
            var asa = e.target.closest ? e.target.closest('.fp-asa') : null;
            if (!asa || !tabla.contains(asa) || arrastre || (e.pointerType === 'mouse' && e.button !== 0)) return;
            var fila = asa.closest('tr');
            e.preventDefault();   // sin seleccionar texto; en táctil el asa no desplaza la página (touch-action: none)
            asa.focus({preventScroll: true});
            arrastre = {fila: fila, desde: indiceDe(fila), id: e.pointerId, y: e.clientY, movida: false};
            try { asa.setPointerCapture(e.pointerId); } catch (ignorado) { /* sin captura también funciona */ }
            document.addEventListener('pointermove', alMover);
            document.addEventListener('pointerup', alSoltar);
            document.addEventListener('pointercancel', alCancelar);
            document.addEventListener('keydown', alEscape, true);
        });
    }

    // Descripción de la línea: una sola línea de texto (el SRI no admite caracteres de control), hasta 300 caracteres.
    var descripcion = {
        MAX: MAX_DESCRIPCION,
        limpiar: function (texto) {
            return String(texto === null || texto === undefined ? '' : texto).replace(CONTROL, ' ');
        },
        // Para enviar: sin espacios sobrantes (el servidor hace lo mismo; vacía → nombre del producto).
        normalizar: function (texto) {
            return descripcion.limpiar(texto).replace(/\s+/g, ' ').trim();
        },
        ajustar: function (area) {
            if (!area || !area.offsetParent) return;
            area.style.height = 'auto';
            area.style.height = (area.scrollHeight + 2) + 'px';
        },
        aviso: function (area, contador) {
            if (!contador) return;
            var n = area.value.length;
            contador.textContent = n >= MAX_DESCRIPCION ? 'Llegaste al máximo de ' + MAX_DESCRIPCION + ' caracteres.' :
                (n >= MAX_DESCRIPCION - 40 ? n + ' de ' + MAX_DESCRIPCION + ' caracteres.' : '');
            contador.classList.toggle('fp-desc-limite', n >= MAX_DESCRIPCION);
        },
        // Delegado en `contenedor` para los textarea.fp-desc-linea: alCambiar(area, texto) recibe el texto limpio.
        activar: function (contenedor, alCambiar) {
            if (!contenedor || contenedor.getAttribute('data-fp-descripcion') === '1') return;
            contenedor.setAttribute('data-fp-descripcion', '1');
            contenedor.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('fp-desc-linea')) e.preventDefault();
            });
            contenedor.addEventListener('input', function (e) {
                var area = e.target;
                if (!area.classList || !area.classList.contains('fp-desc-linea')) return;
                var limpio = descripcion.limpiar(area.value);
                if (limpio !== area.value) {   // texto pegado con saltos de línea: se vuelven espacios, sin mover el cursor
                    var cursor = area.selectionStart;
                    area.value = limpio;
                    try { area.setSelectionRange(cursor, cursor); } catch (ignorado) { /* sin selección */ }
                }
                if (area.value.length > MAX_DESCRIPCION) area.value = area.value.slice(0, MAX_DESCRIPCION);
                descripcion.ajustar(area);
                descripcion.aviso(area, document.getElementById(area.getAttribute('data-contador')));
                alCambiar(area, area.value);
            });
        },
        ajustarTodas: function (contenedor) {
            if (!contenedor) return;
            Array.prototype.forEach.call(contenedor.querySelectorAll('textarea.fp-desc-linea'), function (area) {
                descripcion.ajustar(area);
                descripcion.aviso(area, document.getElementById(area.getAttribute('data-contador')));
            });
        }
    };

    // Casillas numéricas de las líneas: la rueda del ratón no cambia una cantidad sin querer.
    function sinRueda(contenedor) {
        if (!contenedor || contenedor.getAttribute('data-fp-rueda') === '1') return;
        contenedor.setAttribute('data-fp-rueda', '1');
        contenedor.addEventListener('wheel', function (e) {
            if (e.target.type === 'number' && e.target === document.activeElement) e.target.blur();
        }, {passive: true});
    }

    raiz.fpLineas = {ordenar: ordenar, descripcion: descripcion, sinRueda: sinRueda, filas: filas};
}(window));
