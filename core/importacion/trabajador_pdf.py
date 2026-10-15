"""Trabajador aislado para RIDE en PDF: se ejecuta como proceso aparte (python -I) con límites del sistema operativo.

Lee el PDF por la entrada estándar y escribe JSON por la salida: número de páginas, símbolos leídos (QR y códigos de
barras) y el texto incrustado de cada página. No importa Django ni el proyecto, no abre archivos ni la red, y no
interpreta importes: solo busca la clave de acceso. Los límites llegan como JSON en el primer argumento.
"""
import json
import math
import resource
import sys


def limitar(memoria, cpu):
    resource.setrlimit(resource.RLIMIT_AS, (memoria, memoria))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))      # no puede escribir archivos (la salida es una tubería)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    opciones = json.loads(sys.argv[1])
    limitar(opciones['memoria'], opciones['cpu'])
    datos = sys.stdin.buffer.read()
    import pypdfium2 as pdfium
    import zxingcpp
    salida = {'paginas': 0, 'procesadas': 0, 'simbolos': [], 'textos': []}
    try:
        pdf = pdfium.PdfDocument(datos)
    except pdfium.PdfiumError as e:
        mensaje = str(e).lower()
        salida['error'] = 'pdf_protegido' if 'password' in mensaje else 'pdf_invalido'
        print(json.dumps(salida))
        return
    salida['paginas'] = len(pdf)
    if salida['paginas'] > opciones['max_paginas']:
        salida['error'] = 'demasiadas_paginas'
        print(json.dumps(salida))
        return
    formatos = zxingcpp.BarcodeFormat.QRCode | zxingcpp.BarcodeFormat.Code128 | zxingcpp.BarcodeFormat.Code39 | \
        zxingcpp.BarcodeFormat.DataMatrix | zxingcpp.BarcodeFormat.PDF417 | zxingcpp.BarcodeFormat.Aztec
    for numero in range(salida['paginas']):
        pagina = pdf[numero]
        ancho, alto = pagina.get_size()
        escala = opciones['dpi'] / 72
        if ancho * alto * escala * escala > opciones['max_pixeles']:
            escala = math.sqrt(opciones['max_pixeles'] / (ancho * alto))
        imagen = pagina.render(scale=escala, grayscale=True).to_pil()
        for lectura in zxingcpp.read_barcodes(imagen, formats=formatos):
            salida['simbolos'].append({'pagina': numero + 1, 'formato': str(lectura.format), 'texto': lectura.text[:2000]})
        texto = pagina.get_textpage().get_text_range()
        salida['textos'].append(texto[:50000])
        salida['procesadas'] += 1
    print(json.dumps(salida))


if __name__ == '__main__':
    main()
