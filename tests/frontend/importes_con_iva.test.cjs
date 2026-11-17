// Cálculo de la pantalla con precios CON IVA (static/js/fp-importes.js, contrato común «precios con IVA» §1): mismas
// cifras que el servidor, en centavos enteros, con BigInt y con el respaldo de enteros seguros.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const api = require('../../static/js/fp-importes.js');

const L = (precio_con_iva, cant, dscto, tarifa) => ({precio_con_iva, cant, dscto, tarifa});
const cifras = (calc, r) => [calc.dinero(r.base), calc.dinero(r.iva), calc.dinero(r.total), calc.dinero(r.descuento)];

for (const [modo, calc] of [['BigInt', api.crear(true)], ['enteros seguros', api.crear(false)]]) {
    test(`${modo}: el total con IVA que se escribe es exacto; base e IVA se derivan`, () => {
        assert.deepEqual(cifras(calc, calc.linea(L('1000.00', 1, 0, 15))), ['869.57', '130.43', '1000.00', '0.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('1000.00', 1, 10, 15))), ['782.61', '117.39', '900.00', '100.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('1000.00', 3, 0, 15))), ['2608.70', '391.30', '3000.00', '0.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('1000.00', 1, 0, 0))), ['1000.00', '0.00', '1000.00', '0.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('1000.00', 1, 0, 5))), ['952.38', '47.62', '1000.00', '0.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('0.01', 1, 0, 15))), ['0.01', '0.00', '0.01', '0.00']);
        assert.deepEqual(cifras(calc, calc.linea(L('1000,5', 1, 0, 15))), ['870.00', '130.50', '1000.50', '0.00']);
    });

    test(`${modo}: totales por tarifa suman las líneas (nunca base × tarifa sobre el total)`, () => {
        const diez = Array.from({length: 10}, () => Object.assign(calc.linea(L('1000.00', 1, 0, 15)), {grupo: '15 %'}));
        const t = calc.totales(diez);
        assert.deepEqual([calc.dinero(t.base), calc.dinero(t.iva), calc.dinero(t.total)], ['8695.70', '1304.30', '10000.00']);
        const m = calc.totales([
            Object.assign(calc.linea(L('1000.00', 1, 0, 15)), {grupo: '15 %'}),
            Object.assign(calc.linea(L('1000.00', 1, 0, 0)), {grupo: '0 %'}),
            Object.assign(calc.linea(L('1000.00', 1, 0, 5)), {grupo: '5 %'}),
        ]);
        assert.deepEqual(m.grupos.map(g => g.nombre), ['15 %', '5 %', '0 %']);
        assert.deepEqual([calc.dinero(m.base_0), calc.dinero(m.base_gravada), calc.dinero(m.total)], ['1000.00', '1821.95', '3000.00']);
    });

    test(`${modo}: datos inválidos no se calculan a medias`, () => {
        for (const mala of [L('', 1, 0, 15), L('1000.001', 1, 0, 15), L('1000000.00', 1, 0, 15), L('1e3', 1, 0, 15),
            L('10', 0, 0, 15), L('10', 1000000, 0, 15), L('10', 1, 101, 15), L('10', 1, 2.5, 15), L('10', 1, 0, 12.5)]) {
            assert.equal(calc.linea(mala), null, JSON.stringify(mala));
        }
    });
}

test('máximos (999999,99 × 999999): exactos con BigInt; sin BigInt se rechazan en vez de redondear mal', () => {
    const grande = api.crear(true);
    assert.deepEqual(cifras(grande, grande.linea(L('999999.99', 999999, 0, 15))),
        ['869564339130.44', '130434650869.57', '999998990000.01', '0.00']);
    assert.deepEqual(cifras(grande, grande.linea(L('999999.99', 999999, 33, 15))),
        ['582608107217.40', '87391216082.61', '669999323300.01', '329999666700.00']);
    assert.throws(() => api.crear(false).linea(L('999999.99', 999999, 0, 15)), RangeError);
});

test('datos anteriores al cambio: precio sin IVA × (1 + tarifa), mitad hacia arriba', () => {
    assert.equal(api.dinero(api.desdeSinIva(8.5, 15)), '9.78');
    assert.equal(api.dinero(api.desdeSinIva('869.57', 15)), '1000.01');
    assert.equal(api.desdeSinIva('abc', 15), null);
});
