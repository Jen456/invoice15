const {test} = require('node:test');
const assert = require('node:assert/strict');
const {preparar} = require('../../core/pos/static/sale/admin/js/base.js');

function detalle(extra = {}) {
    return {
        id: 99, cant: 3, price: 8.5, dscto: 5, tarifa: 15,
        client: {id: 8}, voucher_number: '000000111', access_code: 'no-copiar',
        product: {id: 4, code: 'DEMO', name: 'Producto ficticio', stock: 30, inventoried: true,
            with_tax: true, tarifa: 15, nombre_tarifa: '15 %', price_current: 10}, ...extra
    };
}

test('copia cantidades, precio y descuento sin datos fiscales ni cliente de origen', () => {
    const origen = detalle(), antes = JSON.stringify(origen);
    const copia = preparar([origen], true);
    assert.equal(copia.lineas[0].id, 4); // id del producto, nunca el detalle 99
    assert.equal(copia.lineas[0].cant, 3);
    // Línea anterior a los precios con IVA (sin precio_con_iva): 8,50 × 1,15 = 9,775 → 9,78 (mitad hacia arriba).
    assert.equal(copia.lineas[0].precio_con_iva, '9.78');
    assert.equal(copia.lineas[0].price_current, undefined);
    assert.equal(copia.lineas[0].descripcion, 'Producto ficticio');
    assert.equal(copia.lineas[0].dscto, 5);
    assert.equal(copia.lineas[0].client, undefined);
    assert.equal(copia.lineas[0].voucher_number, undefined);
    assert.equal(copia.lineas[0].access_code, undefined);
    assert.equal(JSON.stringify(origen), antes);
});

test('sin permiso conserva el precio vigente y explica el cambio', () => {
    const copia = preparar([detalle()], false);
    assert.equal(copia.lineas[0].precio_con_iva, '11.50');
    assert.match(copia.avisos[0], /precio vigente/);
});

test('precios con IVA: usa precio_con_iva y la descripción de la línea de origen', () => {
    const origen = detalle({precio_con_iva: '9.80', descripcion: 'Servicio de junio, sede norte',
        product: {...detalle().product, precio_con_iva: '11.49'}});
    assert.equal(preparar([origen], true).lineas[0].precio_con_iva, '9.80');
    assert.equal(preparar([origen], true).lineas[0].descripcion, 'Servicio de junio, sede norte');
    const vigente = preparar([origen], false);
    assert.equal(vigente.lineas[0].precio_con_iva, '11.49');
    assert.equal(vigente.avisos.length, 1);
    assert.equal(preparar([detalle({precio_con_iva: '1000,5', descripcion: '  '})], true).lineas[0].precio_con_iva, '1000.50');
    assert.equal(preparar([detalle({descripcion: '  '})], true).lineas[0].descripcion, 'Producto ficticio');
    for (const malo of ['1000.001', '-1', '1e3', '1000000.00']) {
        assert.throws(() => preparar([detalle({precio_con_iva: malo})], true), malo);
    }
});

test('IVA actual y falta de stock se avisan sin recortar cantidades ni copiar impuestos viejos', () => {
    const origen = detalle({cant: 40, tarifa: 12});
    const copia = preparar([origen], true);
    assert.equal(copia.lineas[0].cant, 40);
    assert.equal(copia.lineas[0].tarifa, 15);
    assert.equal(copia.avisos.length, 2);
    assert.match(copia.avisos[0], /stock/);
    assert.match(copia.avisos[1], /IVA/);
});

test('rechaza resultados vacíos, duplicados y líneas que el servidor no permite', () => {
    for (const datos of [[], {}, [detalle(), detalle()], [detalle({cant: 0})],
        [detalle({price: 'NaN'})], [detalle({price: 3.141})], [detalle({dscto: 2.5})]]) {
        assert.throws(() => preparar(datos, true));
    }
});
