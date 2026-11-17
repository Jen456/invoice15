/* Importes de las líneas con el precio CON IVA incluido (contrato común «precios con IVA», §1): lo que la usuaria escribe
   es el total exacto y la base y el IVA se derivan. Todo en centavos enteros, sin coma flotante: con BigInt (precio
   999999,99 × cantidad 999999 × 100 pasa de 2^53); en un navegador sin BigInt, con enteros seguros y división exacta, que
   rechaza (RangeError) lo que no cabe. El servidor calcula igual y manda; esto es la vista previa de la pantalla. */
(function (raiz) {
    'use strict';

    function crear(usarBigInt) {
        var grande = usarBigInt === undefined ? typeof BigInt === 'function' : Boolean(usarBigInt);
        var N = grande ? BigInt : Number;
        var CERO = N(0), DOS = N(2), CIEN = N(100);
        var MAX_CENTAVOS = N(99999999);   // 999999,99

        function seguro(x) {
            if (!grande && !Number.isSafeInteger(x)) throw new RangeError('El importe es demasiado grande para este navegador.');
            return x;
        }

        function dividir(a, b) {   // a ≥ 0, b > 0: parte entera exacta
            return grande ? a / b : (a - a % b) / b;
        }

        // medio_arriba(a, b) = floor((2a + b) / (2b)): a/b redondeado a la mitad hacia arriba.
        function medioArriba(a, b) {
            return dividir(seguro(DOS * a + b), seguro(DOS * b));
        }

        // «1000.00», «1000,5», «0.01» o un número con hasta 2 decimales → centavos; null si no es un precio válido.
        function centavos(valor) {
            var texto;
            if (typeof valor === 'number') {
                if (!isFinite(valor) || valor < 0 || Math.abs(valor * 100 - Math.round(valor * 100)) > 1e-6) return null;
                texto = valor.toFixed(2);
            } else if (typeof valor === 'string') {
                texto = valor.trim().replace(',', '.');
            } else {
                return null;
            }
            var m = /^(\d{1,6})(?:\.(\d{1,2}))?$/.exec(texto);
            if (!m) return null;
            var c = N(m[1]) * CIEN + N(((m[2] || '') + '00').slice(0, 2));
            return c > MAX_CENTAVOS ? null : c;
        }

        // Centavos → «1000.00» (texto exacto, sin pasar por coma flotante).
        function dinero(c) {
            var negativo = c < CERO, s = String(negativo ? -c : c);
            while (s.length < 3) s = '0' + s;
            return (negativo ? '-' : '') + s.slice(0, -2) + '.' + s.slice(-2);
        }

        function entero(valor, minimo, maximo) {
            if (valor === '' || valor === null || valor === undefined) return null;
            var n = typeof valor === 'number' ? valor : (/^\s*\d+\s*$/.test(String(valor)) ? Number(valor) : NaN);
            return Number.isInteger(n) && n >= minimo && n <= maximo ? n : null;
        }

        // Una línea: P (precio con IVA), q (cantidad 1–999999), d (descuento % entero 0–100), t (IVA % entero de la tarifa).
        // Devuelve centavos {bruto, descuento, total (T), base, iva} o null si algún dato no es válido.
        function linea(datos) {
            var P = centavos(datos.precio_con_iva);
            var q = entero(datos.cant, 1, 999999);
            var d = datos.dscto === '' || datos.dscto === null || datos.dscto === undefined ? 0 : entero(datos.dscto, 0, 100);
            var t = entero(datos.tarifa === undefined || datos.tarifa === null ? 0 : datos.tarifa, 0, 100);
            if (P === null || q === null || d === null || t === null) return null;
            var bruto = seguro(P * N(q));
            var descuento = medioArriba(seguro(bruto * N(d)), CIEN);
            var total = bruto - descuento;
            var base = t === 0 ? total : medioArriba(seguro(total * CIEN), CIEN + N(t));
            return {bruto: bruto, descuento: descuento, total: total, base: base, iva: total - base, tarifa: t};
        }

        // Totales del comprobante: importeTotal = Σ T; por tarifa, base = Σ base e IVA = Σ iva (nunca base × tarifa).
        // `lineas`: resultados de linea() con `grupo` (nombre de la tarifa, p. ej. «15 %»); se agrupa por ese nombre, en el
        // orden de mayor a menor tarifa.
        function totales(lineas) {
            var r = {total: CERO, base: CERO, iva: CERO, descuento: CERO, base_0: CERO, base_gravada: CERO, grupos: []};
            var porNombre = {};
            lineas.forEach(function (l) {
                if (!l) return;
                var nombre = l.grupo || (l.tarifa + ' %');
                var g = porNombre[nombre];
                if (!g) {
                    g = porNombre[nombre] = {nombre: nombre, tarifa: l.tarifa, base: CERO, iva: CERO, total: CERO};
                    r.grupos.push(g);
                }
                g.base += l.base;
                g.iva += l.iva;
                g.total += l.total;
                r.total += l.total;
                r.base += l.base;
                r.iva += l.iva;
                r.descuento += l.descuento;
                if (l.tarifa > 0) { r.base_gravada += l.base; } else { r.base_0 += l.base; }
            });
            r.grupos.sort(function (a, b) { return b.tarifa - a.tarifa; });
            return r;
        }

        // Centavos → número (para comparar con límites como los USD 50 del consumidor final; nunca para sumar).
        function numero(c) { return Number(dinero(c)); }

        // Precio con IVA desde uno sin IVA, con la conversión del catálogo del contrato (pvp × (1 + tarifa), mitad hacia
        // arriba a centavos). Solo para datos anteriores al cambio que llegan sin `precio_con_iva`.
        function desdeSinIva(valor, tarifa) {
            var c = centavos(valor), t = entero(tarifa === undefined || tarifa === null ? 0 : tarifa, 0, 100);
            if (c === null || t === null) return null;
            var r = medioArriba(seguro(c * (CIEN + N(t))), CIEN);
            return r > MAX_CENTAVOS ? null : r;
        }

        return {
            bigint: grande, centavos: centavos, dinero: dinero, numero: numero, entero: entero,
            medioArriba: medioArriba, linea: linea, totales: totales, desdeSinIva: desdeSinIva, crear: crear
        };
    }

    var api = crear();
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
    raiz.fpImportes = api;
}(typeof window !== 'undefined' ? window : this));
