// Pantalla de la nota de crédito (core/pos/static/credit_note/admin/js/form.js): los importes que enseña antes de emitir
// con las líneas que manda el servidor (acción `search_sale`). Una factura con precios con IVA se devuelve con el cálculo
// del contrato §1 sobre la cantidad devuelta (lo mismo que hará el servidor); una anterior al cambio, como siempre.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const fpImportes = require('../../static/js/fp-importes.js');

const FUENTE = fs.readFileSync(path.join(__dirname, '../../core/pos/static/credit_note/admin/js/form.js'), 'utf8');

// La pantalla sin navegador: jQuery mínimo que recuerda lo escrito en cada casilla del pie y en los rótulos.
function pantalla(lineas) {
    const escrito = {};
    const nodo = selector => {
        let contenido = '';
        const n = {
            val: valor => { escrito[selector] = valor; return n; },
            text: valor => { if (valor === undefined) return contenido; contenido = String(valor); return n; },
            html: () => contenido.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),   // $('<div>').text(x).html()
            eq: i => nodo(selector + '#' + i), find: () => n, on: () => n,
        };
        return n;
    };
    const contexto = {fpImportes, $: selector => nodo(typeof selector === 'string' ? selector : 'fn'),
        document: {addEventListener() {}}};
    vm.runInNewContext(FUENTE, contexto);
    contexto.credit_note.detail.iva = 15;
    contexto.credit_note.detail.products = lineas;
    contexto.credit_note.calculateInvoice();
    return {nota: contexto.credit_note, pie: campo => escrito[`input[name="${campo}"]`]};
}

// Como SaleDetail.toJSON() con lo que añade `search_sale` (quantity = lo que queda por acreditar).
function nueva(extra = {}) {
    return {id: 5, cant: 3, quantity: 3, state: 1, price: 869.57, dscto: 0, tarifa: 15, precio_con_iva: '1000.00',
        descripcion: 'Equipo', con_iva_incluido: true, total: 0, product: {name: 'PRODUCTO DEMO', with_tax: true}, ...extra};
}

function anterior(extra = {}) {
    return {id: 6, cant: 2, quantity: 2, state: 1, price: 8.75, dscto: 10, tarifa: 15, precio_con_iva: '10.06',
        descripcion: 'PRODUCTO ANT15', con_iva_incluido: false, total: 0, product: {name: 'PRODUCTO ANT15', with_tax: true},
        ...extra};
}

test('devolver 2 de 3 unidades de 1000,00 da 2000,00 exactos (base 1739,13 + IVA 260,87)', () => {
    const {nota, pie} = pantalla([nueva({quantity: 2})]);
    assert.deepEqual([pie('subtotal_12'), pie('total_iva'), pie('total'), pie('subtotal_0')], ['1739.13', '260.87', '2000.00', '0.00']);
    assert.equal(nota.textoPrecio(nota.detail.products[0]), '$1000.00');
    assert.equal(nota.textoTotal(nota.detail.products[0]), '$2000.00');
    // Con el precio sin IVA de 2 decimales (869,57 × 2 = 1739,14 + 260,87) habría salido 2000,01.
    assert.notEqual(pie('total'), (869.57 * 2 * 1.15).toFixed(2));
});

test('devolución total y con descuento: los mismos importes que la factura', () => {
    const {nota, pie} = pantalla([nueva({dscto: 10})]);   // 3 × 1000,00 con 10 %: T 2700,00; base 2347,83; IVA 352,17
    assert.deepEqual([pie('subtotal_12'), pie('total_iva'), pie('total'), pie('total_dscto')], ['2347.83', '352.17', '2700.00', '300.00']);
    assert.match(nota.textoDescuento(nota.detail.products[0]), /^10 %<br><small class="text-muted">−\$300\.00 con IVA<\/small>$/);
});

test('tarifa 0 % y 5 %: cada base en su subtotal y el total es la suma de las líneas', () => {
    const {pie} = pantalla([nueva({quantity: 1}), nueva({id: 8, precio_con_iva: '25.00', quantity: 3, tarifa: 0}),
        nueva({id: 9, precio_con_iva: '57.35', quantity: 2, tarifa: 5})]);
    assert.deepEqual([pie('subtotal_0'), pie('subtotal_12'), pie('total_iva'), pie('total')], ['75.00', '978.81', '135.89', '1189.70']);
});

test('una línea sin marcar no entra en el pie', () => {
    const {pie} = pantalla([nueva({quantity: 1}), nueva({id: 8, precio_con_iva: '25.00', state: 0})]);
    assert.deepEqual([pie('total'), pie('total_dscto')], ['1000.00', '0.00']);
});

test('factura anterior al cambio: el cálculo de siempre sobre el precio sin IVA', () => {
    const {nota, pie} = pantalla([anterior()]);   // 2 × 8,75 − 10 % = 15,75; IVA 2,36; total 18,11
    assert.deepEqual([pie('subtotal_12'), pie('total_dscto'), pie('total_iva'), pie('total')], ['15.75', '1.75', '2.36', '18.11']);
    assert.equal(nota.conIva(), false);
    assert.equal(nota.textoPrecio(nota.detail.products[0]), '$8.75');
    assert.equal(nota.textoTotal(nota.detail.products[0]), '$15.75');
    assert.match(nota.textoDescuento(nota.detail.products[0]), /−\$1\.75 sin IVA/);
});

test('el descuento no se edita en la pantalla: es el de la factura', () => {
    assert.equal(FUENTE.includes('name="dscto_unitary"'), false);
    const {nota} = pantalla([nueva()]);
    assert.equal(nota.textoDescuento(nota.detail.products[0]), 'Sin descuento');
});
