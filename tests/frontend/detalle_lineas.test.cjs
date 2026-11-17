// Modal «Detalle» de los listados de ventas y notas de crédito (static/js/fp-detalle-lineas.js): lo que pinta con las
// líneas que manda el servidor (SaleDetail.toJSON / CreditNoteDetail.toJSON, acción `search_detail_products`).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {conIva, fila, filas, ENCABEZADOS} = require('../../static/js/fp-detalle-lineas.js');

// Línea guardada con precio con IVA: 1000,00 con 10 % de descuento al 15 % (T 900,00; base 782,61; IVA 117,39).
function nueva(extra = {}) {
    return {
        id: 7, cant: 1, price: 869.57, price_with_vat: 1000, subtotal: 869.57, total_dscto: 86.96, total: 782.61,
        total_iva: 117.39, dscto: 10, tarifa: 15, codigo_porcentaje: '4', precio_con_iva: '1000.00',
        descripcion: 'Servicio de diseño', total_con_iva: '900.00', precio_unitario: '869.57', con_iva_incluido: true,
        product: {id: 4, name: 'PRODUCTO DEMO', short_name: 'PRODUCTO DEMO (CATEGORÍA FICTICIA)'}, ...extra
    };
}

// Línea guardada antes del cambio: 2 × 8,75 sin IVA con 10 % de descuento (base 15,75; IVA 2,36). El servidor manda
// `con_iva_incluido` falso y, en `precio_con_iva`, el price_with_vat que calculó entonces.
function anterior(extra = {}) {
    return {
        id: 3, cant: 2, price: 8.75, price_with_vat: 10.06, subtotal: 17.5, total_dscto: 1.75, total: 15.75, total_iva: 2.36,
        dscto: 10, tarifa: 15, codigo_porcentaje: '4', precio_con_iva: '10.06', descripcion: 'PRODUCTO ANT15',
        total_con_iva: '18.11', precio_unitario: '8.75', con_iva_incluido: false,
        product: {id: 9, name: 'PRODUCTO ANT15', short_name: 'PRODUCTO ANT15 (CATEGORÍA FICTICIA)'}, ...extra
    };
}

test('línea con precio con IVA: descripción, precio, descuento y total con IVA del servidor', () => {
    const r = filas([nueva()], 'price');
    assert.equal(r.con_iva, true);
    assert.deepEqual(r.encabezados, ['Descripción', 'P. unitario con IVA', 'Cantidad', 'Descuento con IVA', 'Total con IVA']);
    assert.deepEqual(r.filas, [{
        descripcion: 'Servicio de diseño', producto: 'PRODUCTO DEMO (CATEGORÍA FICTICIA)', precio: '1000.00', cantidad: '1',
        descuento: '100.00', total: '900.00'
    }]);
});

test('una línea de 1000,00 × 3 sin descuento muestra 1000,00 y 3000,00 (no 869,57 ni 2608,70)', () => {
    const [f] = filas([nueva({cant: 3, dscto: 0, price: 869.57, total_dscto: 0, total: 2608.7, total_con_iva: '3000.00',
        precio_unitario: '869.566667'})], 'price').filas;
    assert.deepEqual([f.precio, f.cantidad, f.descuento, f.total], ['1000.00', '3', '0.00', '3000.00']);
});

test('si la descripción es el nombre del producto no se repite el producto debajo', () => {
    const [f] = filas([nueva({descripcion: 'PRODUCTO DEMO'})], 'price').filas;
    assert.deepEqual([f.descripcion, f.producto], ['PRODUCTO DEMO', '']);
    const [g] = filas([nueva({descripcion: '   '})], 'price').filas;   // sin descripción: el nombre del producto
    assert.deepEqual([g.descripcion, g.producto], ['PRODUCTO DEMO', '']);
});

test('factura anterior al cambio: lo que mostraba antes, sin inventar un precio con IVA', () => {
    const r = filas([anterior()], 'price');
    assert.equal(r.con_iva, false);
    assert.deepEqual(r.encabezados, ['Producto', 'P./Unitario', 'Cantidad', 'Descuento', 'Total']);
    assert.deepEqual(r.filas, [{
        descripcion: 'PRODUCTO ANT15 (CATEGORÍA FICTICIA)', producto: '', precio: '8.75', cantidad: '2', descuento: '1.75',
        total: '15.75'
    }]);
});

test('nota de crédito anterior: «P./Unitario» sigue siendo el price_with_vat que guardó', () => {
    const [f] = filas([anterior()], 'price_with_vat').filas;
    assert.deepEqual([f.precio, f.descuento, f.total], ['10.06', '1.75', '15.75']);
});

test('una sola línea anterior deja todo el comprobante como antes (columnas coherentes)', () => {
    const r = filas([nueva(), anterior()], 'price');
    assert.equal(r.con_iva, false);
    assert.deepEqual(r.encabezados, ENCABEZADOS.anterior);
    assert.deepEqual(r.filas.map(f => [f.descripcion, f.precio, f.descuento, f.total]), [
        ['PRODUCTO DEMO (CATEGORÍA FICTICIA)', '869.57', '86.96', '782.61'],
        ['PRODUCTO ANT15 (CATEGORÍA FICTICIA)', '8.75', '1.75', '15.75']]);
});

test('sin el total con IVA del servidor no se trata como línea nueva', () => {
    assert.equal(conIva([nueva({total_con_iva: undefined})]), false);
    assert.equal(conIva([nueva({precio_con_iva: 'abc'})]), false);
    assert.equal(conIva([nueva({con_iva_incluido: 'true'})]), false);
    assert.equal(conIva([nueva()]), true);
});

test('respuesta vacía o que no es una lista: sin filas y con los encabezados de siempre', () => {
    for (const respuesta of [[], null, undefined, {error: 'No ha seleccionado ninguna opción'}]) {
        const r = filas(respuesta, 'price');
        assert.equal(r.con_iva, false);
        assert.deepEqual(r.filas, []);
        assert.deepEqual(r.encabezados, ENCABEZADOS.anterior);
    }
});

test('importes grandes sin coma flotante y sin modificar lo recibido', () => {
    const origen = nueva({cant: 9, dscto: 0, precio_con_iva: '999999.99', total_con_iva: '8999999.91'});
    const antes = JSON.stringify(origen);
    const f = fila(origen, true, 'price');
    assert.deepEqual([f.precio, f.descuento, f.total], ['999999.99', '0.00', '8999999.91']);
    assert.equal(JSON.stringify(origen), antes);
});
