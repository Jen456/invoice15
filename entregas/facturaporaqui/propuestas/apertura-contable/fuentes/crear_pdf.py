from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'Inicio-contable-saldos-o-historial.pdf'
for face, file in [('Regular', 'Regular'), ('Bold', 'Bold'), ('Italic', 'Italic')]:
    pdfmetrics.registerFont(TTFont('FPA' + face, '/usr/share/fonts/truetype/liberation/LiberationSans-' + file + '.ttf'))
pdfmetrics.registerFontFamily('FPARegular', normal='FPARegular', bold='FPABold', italic='FPAItalic')
NAVY, CORAL, SKY, PALE, MUTED = [HexColor(x) for x in ['#163B50', '#CA462C', '#44BADD', '#E5F1F6', '#516975']]
c = canvas.Canvas(str(OUT), pagesize=A4, pageCompression=1)
c.setTitle('Inicio contable desde saldos o historial — Propuesta FacturaPorAquí')
c.setAuthor('FacturaPorAquí · Diseño Codex')
c.setSubject('Propuesta para aprobación: dos formas de inicio contable, sin datos reales ni conexión a API')
page_num = 0

def text(txt, x, y, width, size=11, color=NAVY, bold=False):
    style = ParagraphStyle('p', fontName='FPABold' if bold else 'FPARegular', fontSize=size, leading=size*1.4, textColor=color, spaceAfter=0)
    p = Paragraph(txt, style)
    _, height = p.wrap(width, 2000)
    p.drawOn(c, x, y-height)
    return y-height

def page(title, subtitle, wide=False):
    global W, H, page_num
    page_num += 1
    W, H = landscape(A4) if wide else A4
    c.setPageSize((W, H))
    c.setFillColor(PALE); c.rect(0, H-64, W, 64, fill=1, stroke=0)
    c.drawImage(str(ROOT/'colibri.png'), 36, H-48, width=32, height=27, mask='auto', preserveAspectRatio=True)
    text('FacturaPorAquí', 77, H-23, W-140, 15, bold=True)
    text('INICIO CONTABLE · PROPUESTA PARA APROBACIÓN', 77, H-43, W-140, 8, MUTED)
    text(title, 36, H-87, W-72, 23, bold=True)
    y = text(subtitle, 36, H-123, W-72, 10, MUTED)
    c.setStrokeColor(PALE); c.line(36, 43, W-36, 43)
    c.setFillColor(MUTED); c.setFont('FPAItalic', 8)
    c.drawString(36, 29, '13/11/2026 · Datos ficticios · Diseño sin conexión a la aplicación')
    c.drawRightString(W-36, 29, str(page_num))
    return y-22

def box(title, body, x, top, width, height, stripe=CORAL):
    c.setFillColor(PALE); c.roundRect(x, top-height, width, height, 9, fill=1, stroke=0)
    c.setFillColor(stripe); c.roundRect(x, top-height, 4, height, 2, fill=1, stroke=0)
    y=text(title, x+17, top-16, width-34, 15, bold=True)
    return text(body, x+17, y-10, width-34, 11)

def picture(path, x, y, maxw, maxh):
    with Image.open(path) as img:
        iw, ih = img.size
        scale = min(maxw/iw, maxh/ih)
        w,h=iw*scale,ih*scale
        c.drawImage(ImageReader(img), x+(maxw-w)/2, y-h, width=w, height=h, mask='auto')
    return y-h

y=page('Cada empresa elige cómo empezar', 'Añadido al plan del proyecto: aceptar estados financieros existentes sin exigir reconstruir todos los años anteriores.')
y=text('La apertura es un punto de partida revisado. No es una nueva venta, compra ni declaración.',36,y,W-72,13,bold=True)-20
box('1. Ya tengo estados financieros', 'Registrar o importar los saldos a una fecha de corte, mapearlos al plan de cuentas y continuar desde el día siguiente.<br/><br/><b>Preferible:</b> balance de comprobación. Un estado resumido sirve como fuente, pero puede requerir detalle. El PDF es respaldo; no confirma saldos por sí solo.',36,y,W-72,166)
y-=185
box('2. Quiero reconstruir el historial', 'Importar documentos o asientos del sistema anterior, revisar duplicados y conciliar por períodos.<br/><br/>Si la reconstrucción empieza después del inicio de la empresa, también requiere saldos anteriores. La ausencia de datos no significa saldo cero.',36,y,W-72,150,stripe=SKY)
y-=171
y=text('Se puede completar por etapas',36,y,W-72,15,bold=True)-9
y=text('Quien comienza con saldos puede añadir después las facturas que los respaldan. Esos documentos explican el saldo inicial; no vuelven a sumarlo. Cambiar a una reconstrucción que abarque el mismo período exige conciliación y confirmación.',36,y,W-72)-18
text('<b>Ejemplo de fechas:</b> corte al 31/12/2025; nuevas operaciones desde el 01/01/2026. Son fechas ilustrativas, no datos de la empresa piloto.',36,y,W-72,10,MUTED)
c.showPage()

y=page('Saldos útiles, sin duplicaciones', 'La información se completa según lo que la empresa necesita operar y reportar.')
box('Ejemplo: cobrar una factura anterior', 'Clientes al corte: <b>$3.000</b>. Cobro posterior: <b>$500</b>.<br/>Queda por cobrar: <b>$2.500</b>; el banco recibe $500.<br/><br/>Vincular la factura histórica no genera una segunda venta ni vuelve a reconocer su IVA.',36,y,W-72,125)
y-=145
y=text('Detalle que explica los saldos',36,y,W-72,15,bold=True)-8
y=text('<b>Cartera:</b> tercero, documento, vencimiento y saldo. <b>Bancos:</b> cuentas y partidas pendientes. <b>Inventario:</b> cantidades, almacén y costo. <b>Activos:</b> costo y depreciación cuando aplique. <b>Impuestos:</b> saldos anteriores con fuente y período.',36,y,W-72)-18
y=text('Qué permite reportar',36,y,W-72,15,bold=True)-10
rows=[['Reporte','Información necesaria'],
      ['Situación financiera posterior al corte','Apertura revisada y movimientos posteriores conciliados. No exige todas las facturas de años anteriores.'],
      ['104, 103 y ATS','Datos tributarios y documentos del período, reglas vigentes y saldos anteriores confirmados. Un balance aislado no basta.'],
      ['Resultado anual y 101','Ingresos, costos y gastos acumulados del año, movimientos posteriores y conciliación tributaria. Si falta cobertura, indicar provisionalidad.']]
style=ParagraphStyle('cell',fontName='FPARegular',fontSize=10,leading=14,textColor=NAVY)
data=[[Paragraph(cell,style) for cell in row] for row in rows]
t=Table(data,colWidths=[142,W-72-142]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('GRID',(0,0),(-1,-1),.5,PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
_,th=t.wrap(W-72,1000);t.drawOn(c,36,y-th);y-=th+18
text('<b>Inicio a mitad de año:</b> conciliar los resultados acumulados del ejercicio sin duplicarlos en patrimonio y en las cuentas de ingresos/gastos. Los datos pendientes se señalan; no se inventan para cuadrar.',36,y,W-72,10)
c.showPage()

views=[
 ('elegir','Elegir el punto de partida','Dos recorridos por empresa. Fechas y datos de muestra; no se ha importado ninguna empresa real.'),
 ('saldos','Revisar saldos y cuentas','El cuadre no sustituye la revisión del origen, las cuentas de destino ni el detalle necesario para operar.'),
 ('historial','Reconstruir por períodos','Vista previa y cobertura explícita. Un documento anterior puede servir de respaldo sin volver a contabilizarse.'),
 ('validacion','Confirmar alcance y pendientes','Cada reporte informa qué datos necesita. La confirmación de apertura permanece deshabilitada en esta demostración.')]
for key,title,subtitle in views:
    y=page(title,subtitle)
    picture(ROOT/'capturas'/f'panel-{key}-1360.webp',36,y,W-72,y-66)
    c.showPage()

y=page('Siguiente entrega de implementación', 'La decisión de iniciar desde saldos o historial se incorpora al contrato propuesto para Claude.')
left=228
picbottom=picture(ROOT/'capturas'/'opciones-movil-360.webp',36,y,left,410)
x=36+left+22; width=W-36-x
z=text('Diseño móvil',x,y,width,14,bold=True)-12
z=text('Las opciones se apilan y conservan sus explicaciones. Tablas adaptadas, foco visible y estados pendientes identificados.',x,z,width,11)-19
z=text('Claude · Backend',x,z,width,14,bold=True)-10
z=text('Plan de cuentas e importador; apertura y auxiliares; asientos, diario y mayor; conciliación/cierre; completar la validación del módulo tributario existente.',x,z,width,11)-19
z=text('Codex · Interfaz',x,z,width,14,bold=True)-10
z=text('Asistente, mapeo de cuentas, estados, cobertura y reportes. Conectar a los contratos definitivos después de aprobar el diseño.',x,z,width,11)
y=min(picbottom,z)-26
y=text('Criterio de aceptación',36,y,W-72,14,bold=True)-10
y=text('Una apertura confirmada, sin duplicados por reintento; auxiliares que concilian; documentos históricos que no repiten sus efectos; permisos y aislamiento por empresa; reportes provisionales cuando falta información.',36,y,W-72,11)-16
text('<b>Estado de esta entrega:</b> propuesta visual y contrato. No añade el módulo a producción. Los endpoints nuevos no existen aún. El precio pendiente no impide desarrollar el núcleo genérico; la activación comercial y la validación fiscal se resuelven por separado.',36,y,W-72,10,MUTED)
c.showPage();c.save()
print(OUT)
