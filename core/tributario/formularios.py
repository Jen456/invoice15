"""Borradores de las hojas del 104 (IVA) y del 103 (retenciones de renta) por casillero (entrega E).

Son BORRADORES para que el contador los revise. FacturaPorAquí no presenta declaraciones: el contribuyente las presenta en el
portal del SRI. Cada casillero dice de dónde sale (regla y fuente), si su criterio está confirmado y qué documentos lo
componen (trazabilidad hasta cada fila de los libros mensuales). Lo que depende de un criterio tributario sin confirmar no
se asigna a un casillero: va en «por confirmar», con su importe, los casilleros posibles y el motivo.

Fuentes (NORMA-CONTABLE-TRIBUTARIA-2026-10.md): §1 y fuente 6 (Guía del formulario de IVA) para el 104; §2 para el 103
(«el casillero de la base es el código de retención; el del valor retenido, la base + 50», verificado en una declaración
real de mayo de 2024: 303→353, 3030→3530, 3480→3980; subtotal país 349/399; 499 = 399 + 498). Esos ejemplos suman el
50 en la segunda cifra: +50 en los casilleros de 3 dígitos y +500 en los de 4. La regla se aplica a los códigos de residentes
(3xx y 3xxx, como los de la declaración verificada). Los códigos con letra se agrupan en casilleros de 4 dígitos y su mapa
completo NO está confirmado (el Catálogo ATS solo trae código, concepto y porcentaje): solo el ejemplo 303A→3030 de la norma.
Los pagos al exterior (5xx y el 498) quedan por confirmar.

Confirmado y calculado en el 104 (ventas y compras desde los libros, solo producción y autorizados):
- 401/411/421 ventas con tarifa distinta de 0 (sin separar activos fijos: no se registra), 425/435/445 ventas al 5 %,
  431 ventas no objeto o exentas, 507 compras con tarifa 0, 531/532 compras no objeto / exentas,
  609 retenciones de IVA que le hicieron, 721–731 retenciones de IVA efectuadas por porcentaje.
Por confirmar (sin casillero): ventas con tarifa 0 (403/405/406 según el derecho a crédito), ajustes por notas de crédito
(423/424), contado y crédito (480/481), compras con tarifa distinta de 0 (con o sin derecho a crédito: 500…/502, depende del
sustento), activos fijos (402/412/422, 501/511/521). No calculados: arrastres del período anterior (605/606), saldos para el
mes siguiente (615/617), proporcionalidad (563), pagos e intereses.
"""
from collections import OrderedDict
from datetime import date
from decimal import Decimal

from core.tributario import libros as lb

CERO = Decimal('0.00')
FUENTE_104 = 'Guía para el llenado del Formulario de IVA (SRI) — NORMA-CONTABLE-TRIBUTARIA-2026-10.md §1, fuente 6'
FUENTE_103 = 'Regla de casilleros verificada en una declaración real (mayo de 2024) — NORMA-CONTABLE-TRIBUTARIA-2026-10.md §2'
VIGENCIAS = {'104': date(2024, 4, 1), '103': date(2024, 1, 1)}   # IVA 15 % desde el 01/04/2024; regla del 103 verificada en 2024
AVISO = ('Borrador para que lo revise tu contador. FacturaPorAquí no presenta declaraciones: la presentas tú en el portal del SRI. '
         'Los criterios marcados «por confirmar» no se asignaron a ningún casillero.')
IVA_EFECTUADAS = {Decimal('10'): '721', Decimal('20'): '723', Decimal('30'): '725', Decimal('50'): '727', Decimal('70'): '729',
                  Decimal('100'): '731'}
GRAVADAS_NO_5 = ('4', '2', '3', '10', '8')
LETRAS_CONFIRMADAS = {'303A': '3030'}


class SinVigencia(ValueError):
    pass


def _ref(libro, fila, importe):
    return {'libro': libro, 'id': fila['id'], 'tipo': fila.get('tipo', ''), 'numero': fila['numero'], 'url': fila['url'],
            'importe': f'{importe:.2f}'}


class Hoja:
    def __init__(self, formulario, inicio):
        self.formulario, self.inicio = formulario, inicio
        self.casilleros = OrderedDict()
        self.por_confirmar, self.no_calculados, self.advertencias = [], [], []

    def sumar(self, casillero, descripcion, valor, documento=None, fuente=None):
        c = self.casilleros.setdefault(casillero, {'casillero': casillero, 'descripcion': descripcion, 'valor': CERO, 'confirmado': True,
                                                  'fuente': fuente or (FUENTE_104 if self.formulario == '104' else FUENTE_103),
                                                  'documentos': []})
        c['valor'] += valor
        if documento is not None:
            c['documentos'].append(documento)

    def pendiente(self, clave, concepto, valor, posibles, motivo, documento=None):
        p = next((x for x in self.por_confirmar if x['clave'] == clave), None)
        if p is None:
            p = {'clave': clave, 'concepto': concepto, 'valor': CERO, 'casilleros_posibles': posibles, 'motivo': motivo, 'documentos': []}
            self.por_confirmar.append(p)
        p['valor'] += valor
        if documento is not None:
            p['documentos'].append(documento)

    def como_dict(self):
        def d(x):
            return {**x, 'valor': f'{x["valor"]:.2f}'}
        return {'formulario': self.formulario, 'mes': f'{self.inicio:%Y-%m}', 'aviso': AVISO,
                'casilleros': [d(c) for c in sorted(self.casilleros.values(), key=lambda c: (len(c['casillero']), c['casillero']))],
                'por_confirmar': [d(p) for p in self.por_confirmar], 'no_calculados': self.no_calculados,
                'advertencias': self.advertencias, 'vigente_desde': VIGENCIAS[self.formulario].isoformat()}


def _vigencia(formulario, inicio):
    if inicio < VIGENCIAS[formulario]:
        raise SinVigencia(f'No hay un mapa de casilleros del {formulario} vigente para {inicio:%m/%Y}: el borrador cubre desde '
                          f'{VIGENCIAS[formulario]:%m/%Y}.')


def hoja_104(inicio):
    _vigencia('104', inicio)
    hoja = Hoja('104', inicio)
    ventas, _, _ = lb.construir('ventas', inicio)
    for fila in ventas.filas:
        if not fila['cuenta']:
            continue
        signo = fila['signo']
        for codigo, base in fila['bases'].items():
            iva = fila['ivas'].get(codigo, CERO)
            if codigo in GRAVADAS_NO_5:
                if signo > 0:
                    hoja.sumar('401', 'Ventas locales gravadas con tarifa diferente de 0 (sin activos fijos): valor bruto', base, _ref('ventas', fila, base))
                hoja.sumar('411', 'Ventas locales gravadas con tarifa diferente de 0 (sin activos fijos): valor neto', signo * base, _ref('ventas', fila, signo * base))
                hoja.sumar('421', 'Ventas locales gravadas con tarifa diferente de 0 (sin activos fijos): impuesto generado', signo * iva, _ref('ventas', fila, signo * iva))
            elif codigo == '5':
                if signo > 0:
                    hoja.sumar('425', 'Ventas locales gravadas con tarifa 5 %: valor bruto', base, _ref('ventas', fila, base))
                hoja.sumar('435', 'Ventas locales gravadas con tarifa 5 %: valor neto', signo * base, _ref('ventas', fila, signo * base))
                hoja.sumar('445', 'Ventas locales gravadas con tarifa 5 %: impuesto generado', signo * iva, _ref('ventas', fila, signo * iva))
            elif codigo in ('6', '7'):
                hoja.sumar('431', 'Ventas no objeto de IVA o exentas', signo * base, _ref('ventas', fila, signo * base))
            elif codigo == '0':
                hoja.pendiente('ventas_0', 'Ventas con tarifa 0 % (valor neto)', signo * base, ['403/413', '405/415', '406/416'],
                               'El casillero depende de si la venta con tarifa 0 % da derecho a crédito tributario: lo decide el contador.',
                               _ref('ventas', fila, signo * base))
        if fila['tipo'] == 'nota_credito':
            hoja.pendiente('ajustes_nc', 'Notas de crédito del mes (base total)', fila['base_total'], ['423', '424'],
                           'Los ajustes por notas de crédito ya restan en el valor neto; su registro en 423/424 está sin confirmar.',
                           _ref('ventas', fila, fila['base_total']))
        if fila['tipo'] == 'factura':
            clave = 'contado' if fila['condicion'] == 'Contado' else 'credito'
            gravada = sum((fila['bases'].get(c, CERO) for c in GRAVADAS_NO_5 + ('5',)), CERO)
            hoja.pendiente(f'ventas_{clave}', f'Ventas gravadas a {"contado" if clave == "contado" else "crédito"} (base gravada)',
                           gravada, ['480' if clave == 'contado' else '481'],
                           'Qué importe exacto va en 480/481 (bruto o neto y cómo se reparten las notas de crédito) está sin confirmar.',
                           _ref('ventas', fila, gravada))
    compras, _, _ = lb.construir('compras', inicio)
    for fila in compras.filas:
        signo = fila['signo']
        for codigo, base in fila['bases'].items():
            if codigo == '0':
                hoja.sumar('507', 'Adquisiciones y pagos con tarifa 0 %', signo * base, _ref('compras', fila, signo * base))
            elif codigo == '6':
                hoja.sumar('531', 'Adquisiciones no objeto de IVA', signo * base, _ref('compras', fila, signo * base))
            elif codigo == '7':
                hoja.sumar('532', 'Adquisiciones exentas de IVA', signo * base, _ref('compras', fila, signo * base))
            elif codigo == 'sin_tarifa':
                hoja.pendiente('compras_sin_tarifa', 'Compras antiguas sin tarifa registrada', signo * base, [],
                               'No se sabe su tarifa: complétalas antes de declarar.', _ref('compras', fila, signo * base))
            else:
                hoja.pendiente(f'compras_{fila.get("cod_sustento") or "sin_sustento"}',
                               f'Compras con tarifa diferente de 0 — sustento: {fila["sustento"] or "sin sustento"} (base neta)',
                               signo * base, ['500/510/520', '501/511/521', '502', '540/550/560'],
                               'Con o sin derecho a crédito tributario y si son activos fijos depende del sustento y del contador.',
                               _ref('compras', fila, signo * base))
    recibidas, _, _ = lb.construir('retenciones_recibidas', inicio)
    for fila in recibidas.filas:
        if fila['cuenta'] and fila['impuesto_id'] == '2':
            hoja.sumar('609', 'Retenciones en la fuente de IVA que le han sido efectuadas', fila['valor'], _ref('retenciones_recibidas', fila, fila['valor']))
    efectuadas, _, _ = lb.construir('retenciones_efectuadas', inicio)
    for fila in efectuadas.filas:
        if not fila['cuenta'] or fila['impuesto_id'] != '2':
            continue
        casillero = IVA_EFECTUADAS.get(fila['porcentaje'])   # Decimal('30.00') == Decimal('30')
        if casillero:
            hoja.sumar(casillero, f'Retención del {fila["porcentaje"]:.0f} % de IVA efectuada como agente', fila['valor'],
                       _ref('retenciones_efectuadas', fila, fila['valor']))
        else:
            hoja.pendiente('iva_otro_porcentaje', 'Retenciones de IVA con un porcentaje sin casillero', fila['valor'], [],
                           f'No hay casillero confirmado para el {fila["porcentaje"]} %.', _ref('retenciones_efectuadas', fila, fila['valor']))
    hoja.no_calculados = ['605/606 saldos de crédito del mes anterior', '615/617 saldos de crédito para el mes siguiente',
                          '563 factor de proporcionalidad', '564/565 crédito aplicable', '902/903/904 total a pagar, intereses y multas']
    hoja.advertencias.append({'codigo': 'activos_fijos', 'texto': 'La aplicación no distingue ventas ni compras de activos fijos: '
                              'todas las ventas gravadas van en 401–421; si vendiste activos fijos, corrígelo en 402–422.'})
    for exclusion in (ventas.excluidos or {}).items():
        hoja.advertencias.append({'codigo': 'excluidos', 'texto': f'Fuera del borrador ({exclusion[0]}): {exclusion[1]["pruebas"]} en '
                                  f'pruebas y {exclusion[1]["sin_autorizar"]} sin autorizar.'})
    hoja.advertencias += compras.advertencias
    return hoja


def _valor_103(base):
    """Casillero del valor retenido: la base + 50 en la segunda cifra (303→353; 3030→3530 y 3480→3980, verificados)."""
    return str(int(base) + 5 * 10 ** (len(base) - 2))


def casillero_103(codigo):
    """(casillero de la base, casillero del valor, confirmado) de un código de retención de renta."""
    codigo = (codigo or '').strip().upper()
    if codigo.isdigit() and codigo.startswith('3') and len(codigo) in (3, 4):   # residentes, como la declaración verificada
        return codigo, _valor_103(codigo), True
    if codigo in LETRAS_CONFIRMADAS:
        base = LETRAS_CONFIRMADAS[codigo]
        return base, _valor_103(base), True
    return None, None, False


MOTIVO_EXTERIOR = ('Pago al exterior: la regla de casilleros verificada es la de residentes; los del exterior (5xx, subtotal 498) '
                   'están sin confirmar.')
MOTIVO_LETRA = 'Los códigos con letra se agrupan en casilleros de 4 dígitos y su mapa completo no está confirmado.'


def hoja_103(inicio):
    _vigencia('103', inicio)
    hoja = Hoja('103', inicio)
    efectuadas, _, _ = lb.construir('retenciones_efectuadas', inicio)
    for fila in efectuadas.filas:
        if not fila['cuenta'] or fila['impuesto_id'] != '1':
            continue
        base_c, valor_c, confirmado = casillero_103(fila['codigo'])
        if not confirmado:
            hoja.pendiente(f'codigo_{fila["codigo"]}', f'Código {fila["codigo"]}: {fila["concepto"]} (valor retenido)', fila['valor'], [],
                           MOTIVO_EXTERIOR if fila['codigo'].startswith('5') else MOTIVO_LETRA,
                           _ref('retenciones_efectuadas', fila, fila['valor']))
            continue
        hoja.sumar(base_c, f'Base imponible — código {fila["codigo"]}', fila['base'], _ref('retenciones_efectuadas', fila, fila['base']))
        hoja.sumar(valor_c, f'Valor retenido — código {fila["codigo"]}', fila['valor'], _ref('retenciones_efectuadas', fila, fila['valor']))
        # solo los códigos de residentes llegan aquí (los del exterior quedan por confirmar): subtotal país
        hoja.sumar('349', 'Subtotal operaciones efectuadas en el país: base', fila['base'], _ref('retenciones_efectuadas', fila, fila['base']))
        hoja.sumar('399', 'Subtotal operaciones efectuadas en el país: valor retenido', fila['valor'],
                   _ref('retenciones_efectuadas', fila, fila['valor']))
    if '399' in hoja.casilleros:
        hoja.sumar('499', 'Total de retención de impuesto a la renta (399 + 498; el 498 no se calcula)', hoja.casilleros['399']['valor'])
    if hoja.por_confirmar:
        hoja.advertencias.append({'codigo': 'totales_parciales', 'texto': 'Los casilleros 349, 399 y 499 no incluyen lo que está '
                                  '«por confirmar»: súmalo cuando el contador le asigne su casillero.'})
    hoja.no_calculados = ['498 pagos al exterior (no se registran retenciones al exterior)', '890/902/903/904 pago, intereses y multas']
    return hoja


def hoja(formulario, inicio):
    return (hoja_104 if formulario == '104' else hoja_103)(inicio)


def a_xlsx(h):
    """XLSX del borrador: casilleros, por confirmar y documentos de cada uno (valores, nunca fórmulas)."""
    import io

    from openpyxl import Workbook

    from core.tributario.exportar import _escribir
    datos = h.como_dict()
    wb = Workbook()
    hoja_c = wb.active
    hoja_c.title = f'Borrador {h.formulario}'
    _escribir(hoja_c, 1, 1, datos['aviso'], 'texto')
    for col, titulo in enumerate(('Casillero', 'Descripción', 'Valor', 'Criterio', 'Fuente'), start=1):
        _escribir(hoja_c, 3, col, titulo, 'texto')
    fila = 4
    for c in datos['casilleros']:
        for col, (valor, tipo) in enumerate(((c['casillero'], 'texto'), (c['descripcion'], 'texto'), (Decimal(c['valor']), 'importe'),
                                             ('Confirmado' if c['confirmado'] else 'Por confirmar', 'texto'), (c['fuente'], 'texto')), start=1):
            _escribir(hoja_c, fila, col, valor, tipo)
        fila += 1
    hoja_p = wb.create_sheet('Por confirmar')
    for col, titulo in enumerate(('Concepto', 'Valor', 'Casilleros posibles', 'Motivo'), start=1):
        _escribir(hoja_p, 1, col, titulo, 'texto')
    for n, p in enumerate(datos['por_confirmar'], start=2):
        for col, (valor, tipo) in enumerate(((p['concepto'], 'texto'), (Decimal(p['valor']), 'importe'),
                                             (', '.join(p['casilleros_posibles']), 'texto'), (p['motivo'], 'texto')), start=1):
            _escribir(hoja_p, n, col, valor, tipo)
    hoja_d = wb.create_sheet('Documentos')
    for col, titulo in enumerate(('Casillero o concepto', 'Libro', 'Tipo', 'Número', 'Importe', 'Enlace'), start=1):
        _escribir(hoja_d, 1, col, titulo, 'texto')
    n = 2
    for grupo in [(c['casillero'], c['documentos']) for c in datos['casilleros']] + [(p['concepto'], p['documentos']) for p in datos['por_confirmar']]:
        for doc in grupo[1]:
            for col, (valor, tipo) in enumerate(((grupo[0], 'texto'), (doc['libro'], 'texto'), (doc['tipo'], 'texto'), (doc['numero'], 'texto'),
                                                 (Decimal(doc['importe']), 'importe'), (doc['url'], 'texto')), start=1):
                _escribir(hoja_d, n, col, valor, tipo)
            n += 1
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
