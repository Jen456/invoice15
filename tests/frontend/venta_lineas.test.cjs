// Pantalla de la venta (core/pos/static/sale/admin/js/form.js): lo que guarda la línea mientras se escribe en «P. unitario
// con IVA» y en «Cantidad», y si deja emitir. Un precio que no se puede leer («1.500», «1.000,00», vacío) nunca se
// convierte en otro que sí (1,50 o 1,00): la línea queda marcada y «Emitir» se detiene. Al salir de una cantidad vacía
// vuelve la que había al entrar, no la que quedó a medio escribir.
//
// Sin navegador: un jQuery de juguete acepta cualquier llamada y guarda los manejadores delegados de la tabla de líneas
// (`.on(evento, selector, función)`), que se llaman con una casilla simulada, tecla por tecla, como lo haría el navegador.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const fpImportes = require('../../static/js/fp-importes.js');

const RAIZ = path.join(__dirname, '../..');
const FUENTE = fs.readFileSync(path.join(RAIZ, 'core/pos/static/sale/admin/js/form.js'), 'utf8');
const LINEAS = fs.readFileSync(path.join(RAIZ, 'static/js/fp-lineas.js'), 'utf8');

// Acepta cualquier propiedad o llamada y se devuelve a sí mismo; `.on(evento, selector, fn)` guarda el manejador.
function cualquiera(manejadores) {
    const p = new Proxy(function () {}, {
        get(objetivo, clave) {
            if (clave === Symbol.toPrimitive) return () => '';
            if (clave === Symbol.iterator) return function* () {};
            if (clave === 'then') return undefined;
            if (clave === 'length') return 0;
            if (clave === 'on') {
                return (evento, selector, fn) => {
                    if (typeof selector === 'string' && typeof fn === 'function') manejadores[`${evento} ${selector}`] = fn;
                    return p;
                };
            }
            return p;
        },
        apply() { return p; },
        construct() { return p; },
    });
    return p;
}

function pantalla(lineas) {
    const manejadores = {}, errores = [], avisos = [], listos = [];
    const todo = cualquiera(manejadores);
    const $ = new Proxy(function () {}, {
        get(objetivo, clave) { return todo[clave]; },
        apply(objetivo, yo, args) {
            if (typeof args[0] === 'function') listos.push(args[0]);   // $(function () { … }): se corre al final
            return todo;
        },
    });
    // Sin la precarga de una proforma (fp-proforma-precarga): una venta nueva.
    const documento = new Proxy({}, {get: (o, clave) => clave === 'getElementById' ?
        id => (id === 'fp-proforma-precarga' ? null : todo) : todo[clave]});
    const ventana = {};
    vm.runInNewContext(LINEAS, {window: ventana, document: documento});
    const contexto = {
        fpImportes, fpLineas: ventana.fpLineas, $, jQuery: $, document: documento, window: todo, location: todo, moment: todo,
        FormValidation: todo, pathname: '/pos/sale/add/', csrftoken: 'ficticio',
        message_error: texto => errores.push(String(texto)),
        validate_text_box: () => true, es_identificacion_extranjera: () => false, dialog_action: todo, loading: todo,
        alert_sweetalert: todo, submit_formdata_with_ajax_form: todo, submit_formdata_with_ajax: todo,
    };
    vm.runInNewContext(FUENTE, contexto);
    listos.forEach(fn => fn());
    const sale = contexto.sale;
    sale.detail.iva = 15;
    sale.filaDe = elemento => ({tr: todo, indice: elemento.indice});
    sale.avisarLinea = (tr, texto) => { if (texto) avisos.push(texto); };
    lineas.forEach(l => sale.detail.products.push(sale.prepararLinea(l)));
    sale.listProducts();

    // Entra en la casilla, borra lo que tiene (todo de una vez, o con `teclas` una tecla de retroceso por carácter) y escribe
    // `texto` tecla por tecla (un `input` por tecla); con `salir` (por defecto), deja la casilla (`change`).
    function teclear(indice, nombre, texto, {salir = true, teclas = false} = {}) {
        const linea = sale.detail.products[indice];
        const casilla = {indice, value: String(nombre === 'cant' ? linea.cant : linea.precio_con_iva), dataset: {}};
        const llamar = evento => {
            const fn = manejadores[`${evento} input[name="${nombre}"]`];
            if (fn) fn.call(casilla);
        };
        llamar('focusin');
        const antes = casilla.value;
        for (let i = teclas ? antes.length - 1 : 0; i >= 0; i--) {
            casilla.value = antes.slice(0, i);
            llamar('input');
        }
        for (let i = 1; i <= texto.length; i++) {
            casilla.value = texto.slice(0, i);
            llamar('input');
        }
        if (salir) llamar('change');
        return casilla;
    }
    // «Emitir factura» o «Guardar borrador»: lo primero que miran es sale.lineasValidas().
    function emitir() {
        errores.length = 0;
        return sale.lineasValidas() ? sale.lineasParaEnviar() : null;
    }
    return {sale, teclear, emitir, errores, avisos};
}

// Como Product.toJSON() de la búsqueda: precio con IVA del catálogo 1000,00 (sin IVA 869,57) al 15 %.
function producto(extra = {}) {
    return {id: 1, code: 'SD15', name: 'SERVICIO FICTICIO', with_tax: true, tarifa: 15, nombre_tarifa: '15 %',
        price_current: 869.57, precio_con_iva: '1000.00', descripcion: 'SERVICIO FICTICIO', inventoried: false, stock: 0,
        cant: 1, ...extra};
}

for (const texto of ['1.500', '1.000,00', '1.000,50', '1,000.50']) {
    test(`precio «${texto}» (con puntos de miles): la línea queda marcada y no se emite por otro precio`, () => {
        const {sale, teclear, emitir, errores, avisos} = pantalla([producto()]);
        const casilla = teclear(0, 'precio_linea', texto);
        const linea = sale.detail.products[0];
        assert.equal(casilla.value, texto, 'la casilla conserva lo escrito');
        assert.equal(linea.precio_con_iva, texto);
        assert.equal(linea.importes_validos, false);
        assert.match(avisos.at(-1), /sin puntos de miles/);
        assert.equal(emitir(), null, 'no se envía nada');
        assert.match(errores[0], /^Revisa la línea 1:/);
    });
}

test('borrar el precio tecla por tecla y salir: no queda 1,00 ni el del catálogo, tampoco al reordenar o quitar otra fila', () => {
    const {sale, teclear, emitir} = pantalla([producto(), producto({id: 2, code: 'TE15', name: 'TECLADO FICTICIO',
        descripcion: 'TECLADO FICTICIO', precio_con_iva: '25.00', price_current: 21.74})]);
    teclear(0, 'precio_linea', '', {teclas: true});   // 1000.00 → 1000.0 → … → 1 → (vacío)
    assert.equal(sale.detail.products[0].precio_con_iva, '');
    assert.equal(emitir(), null);
    sale.moverLinea(0, 1);   // asa ⋮⋮ o «Bajar»: se redibuja la tabla (prepararLinea de cada línea)
    const movida = sale.detail.products[1];
    assert.equal(movida.code, 'SD15');
    assert.equal(movida.precio_con_iva, '', 'el redibujo no lo deriva del precio sin IVA');
    assert.equal(movida.importes_validos, false);
    sale.detail.products.splice(0, 1);   // quitar la otra fila, como el botón de la papelera
    sale.listProducts();
    assert.equal(sale.detail.products[0].precio_con_iva, '');
    assert.equal(emitir(), null);
});

test('precio corregido después de un error: se emite por lo escrito', () => {
    const {teclear, emitir} = pantalla([producto()]);
    teclear(0, 'precio_linea', '1.500');
    assert.equal(emitir(), null);
    const casilla = teclear(0, 'precio_linea', '1500');
    assert.equal(casilla.value, '1500.00');
    const [linea] = emitir();
    assert.equal(linea.precio_con_iva, '1500.00');
});

test('precios válidos: «1500», «12,5» y «0,01» se envían con 2 decimales', () => {
    for (const [texto, enviado] of [['1500', '1500.00'], ['12,5', '12.50'], ['0,01', '0.01'], ['999999.99', '999999.99']]) {
        const {sale, teclear, emitir} = pantalla([producto()]);
        teclear(0, 'precio_linea', texto);
        assert.equal(sale.detail.products[0].importes_validos, true, texto);
        assert.equal(emitir()[0].precio_con_iva, enviado, texto);
    }
});

test('mientras se escribe «1.5» el total ya es el de 1,50 (vista previa) y al terminar «1.50» vale', () => {
    const {sale, teclear, emitir} = pantalla([producto()]);
    teclear(0, 'precio_linea', '1.5', {salir: false});
    assert.equal(sale.detail.products[0].total_con_iva, '1.50');
    teclear(0, 'precio_linea', '1.50');
    assert.equal(emitir()[0].precio_con_iva, '1.50');
});

test('cantidad: borrar «25» y salir vuelve a 25 (no a 2, lo que quedó a medio borrar) y avisa', () => {
    const {sale, teclear, emitir, avisos} = pantalla([producto({cant: 25})]);
    assert.equal(sale.detail.products[0].cant, 25);
    const casilla = teclear(0, 'cant', '', {teclas: true});   // 25 → 2 → (vacío)
    assert.equal(sale.detail.products[0].cant, 25);
    assert.equal(casilla.value, '25');
    assert.match(avisos.at(-1), /La cantidad es un número entero/);
    assert.equal(emitir()[0].cant, 25);
});

test('cantidad: escribir otra la cambia; la siguiente vez vuelve a la nueva', () => {
    const {sale, teclear, emitir} = pantalla([producto({cant: 25})]);
    teclear(0, 'cant', '3');
    assert.equal(sale.detail.products[0].cant, 3);
    teclear(0, 'cant', '', {teclas: true});
    assert.equal(sale.detail.products[0].cant, 3);
    assert.equal(emitir()[0].cant, 3);
});
