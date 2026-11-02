"""Exportación de los libros mensuales a XLSX y CSV.

- Sin fórmulas: los totales se escriben como valores calculados en el servidor. Un texto que empieza con «=», «+», «-»,
  «@», tabulador o retorno (por ejemplo, el nombre de un proveedor) queda como TEXTO: en XLSX la celda se marca de tipo
  texto; en CSV se antepone un apóstrofo (recomendación OWASP contra la inyección de fórmulas).
- Importes exactos: en XLSX son números con dos decimales (Decimal); en CSV, texto con punto decimal y separador «;»,
  en UTF-8 con BOM (Excel lo abre con tildes).
- Cada fila lleva el enlace a su documento, y el pie de cada hoja, los totales y lo excluido del mes.
"""
import csv
import hashlib
import io
from decimal import Decimal

from core.tributario import libros as lb

PELIGROSOS = ('=', '+', '-', '@', '\t', '\r')


def texto_seguro(texto):
    texto = '' if texto is None else str(texto)
    return "'" + texto if texto.startswith(PELIGROSOS) else texto


def _celda_csv(valor, tipo):
    if tipo in ('importe', 'porcentaje') and isinstance(valor, Decimal):
        return f'{valor:.2f}'
    return texto_seguro(valor)


def _filas_pie(libro, totales):
    """Filas de texto/valor para el pie: totales del libro y documentos excluidos."""
    pie = [('Documentos en el libro', totales['documentos']), ('Documentos que suman', totales['cuentan']),
           ('Documentos que no suman (anulados)', totales['no_cuentan'])]
    if libro.clave in ('ventas', 'compras'):
        for codigo in lb.tarifas_presentes(libro):
            nombre = 'sin tarifa registrada' if codigo == 'sin_tarifa' else lb.NOMBRES_TARIFA.get(codigo, codigo)
            pie.append((f'Base {nombre}', totales['bases'].get(codigo, lb.CERO)))
            if codigo not in ('0', '6', '7', 'sin_tarifa'):
                pie.append((f'IVA {nombre}', totales['ivas'].get(codigo, lb.CERO)))
        pie += [('Base total', totales['base_total']), ('IVA total', totales['iva_total']), ('Total', totales['total'])]
    else:
        for nombre, g in totales['por_codigo'].items():
            pie.append((f'{nombre}: base', g['base']))
            pie.append((f'{nombre}: retenido', g['valor']))
        pie += [('Total retenido de renta', totales['renta']), ('Total retenido de IVA', totales['iva'])]
    for grupo, conteo in libro.excluidos.items():
        pie.append((f'Excluidos ({grupo}): en ambiente de pruebas', conteo['pruebas']))
        pie.append((f'Excluidos ({grupo}): sin autorizar en el SRI', conteo['sin_autorizar']))
    for aviso in libro.advertencias:
        pie.append(('Advertencia', aviso['texto']))
    return pie


def a_csv(libro, totales, columnas):
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=';')
    escritor.writerow([encabezado for _, encabezado, _ in columnas])
    for fila in libro.filas:
        escritor.writerow([_celda_csv(lb.valor(fila, clave), tipo) for clave, _, tipo in columnas])
    escritor.writerow([])
    for etiqueta, valor_ in _filas_pie(libro, totales):
        escritor.writerow([texto_seguro(etiqueta), _celda_csv(valor_, 'importe') if isinstance(valor_, Decimal) else texto_seguro(valor_)])
    return ('﻿' + salida.getvalue()).encode('utf-8')


def _hoja(wb, libro, totales, columnas, primera=False):
    from openpyxl.styles import Font
    hoja = wb.active if primera else wb.create_sheet()
    hoja.title = libro.nombre[:31]
    for col, (_, encabezado, _) in enumerate(columnas, start=1):
        celda = hoja.cell(row=1, column=col, value=encabezado)
        celda.data_type = 's'
        celda.font = Font(bold=True)
    for fila_n, fila in enumerate(libro.filas, start=2):
        for col, (clave, _, tipo) in enumerate(columnas, start=1):
            _escribir(hoja, fila_n, col, lb.valor(fila, clave), tipo)
    fila_n = len(libro.filas) + 3
    for etiqueta, valor_ in _filas_pie(libro, totales):
        _escribir(hoja, fila_n, 1, etiqueta, 'texto')
        _escribir(hoja, fila_n, 2, valor_, 'importe' if isinstance(valor_, Decimal) else 'texto')
        fila_n += 1
    hoja.freeze_panes = 'A2'
    return hoja


def _escribir(hoja, fila, col, valor_, tipo):
    if tipo in ('importe', 'porcentaje') and isinstance(valor_, Decimal):
        celda = hoja.cell(row=fila, column=col, value=valor_)
        celda.number_format = '0.00'
        return
    if isinstance(valor_, int) and not isinstance(valor_, bool):
        hoja.cell(row=fila, column=col, value=valor_)
        return
    celda = hoja.cell(row=fila, column=col, value='' if valor_ is None else str(valor_))
    celda.data_type = 's'   # nunca una fórmula, aunque empiece por «=»


def a_xlsx(libros_construidos):
    """XLSX con una hoja por libro: [(libro, totales, columnas)]."""
    from openpyxl import Workbook
    wb = Workbook()
    for n, (libro, totales, columnas) in enumerate(libros_construidos):
        _hoja(wb, libro, totales, columnas, primera=(n == 0))
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def huella(contenido):
    return hashlib.sha256(contenido).hexdigest()
