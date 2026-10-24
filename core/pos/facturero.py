"""Migración desde Facturero Móvil: reportes de productos, clientes y proveedores exportados en .txt.

Cada reporte es texto separado por tabuladores: unas líneas de cabecera (titular, título, fecha), la fila con los
nombres de las columnas y los datos. Se importa a la empresa activa sin modificar lo que ya existe: lo repetido
(código de producto, identificación del cliente, RUC o razón social del proveedor) se omite, igual que las filas que
el sistema no aceptaría desde sus formularios (identificación inválida, tarifa de IVA desconocida...). Todo queda en
el informe, fila por fila.

Correspondencias que no son obvias:
- Producto: «Valor» es el precio de venta sin IVA (pvp); el precio de compra queda en 0.00 porque el reporte no lo
  trae. Categoría = la de Facturero; si es «Ninguna», el «Tipo» (Bien / Servicio).
- Cliente: el comprador no recibe acceso al sistema (usuario inactivo y sin contraseña, como el consumidor final).
  El primer correo válido es el principal y los demás van a «Otros correos»; todos reciben los comprobantes.
"""
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from core.login.identificacion import solo_digitos
from core.pos.clientes import CONSUMIDOR_FINAL, correo_valido, separar_correos, unir_correos, validar_identificacion
from core.pos.models import Category, Client, Product, Provider
from core.tenancy.context import company_context
from core.user.models import User

CENTAVO = Decimal('0.01')
TARIFAS = {'15%': '4', '5%': '5', '0%': '0', 'exento': '7', 'exentodeiva': '7', 'noobjeto': '6', 'noobjetodeiva': '6'}
TIPOS_IDENTIFICACION = {'ruc': '04', 'cedula': '05', 'cedula de identidad': '05', 'pasaporte': '06',
                        'identificacion del exterior': '08', 'consumidor final': '07'}
CONDICIONES_CONTADO = {'', 'contado', 'de contado'}


def clave(texto):
    """Texto comparable: sin tildes, en minúsculas, sin puntos y con espacios simples."""
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return ' '.join(texto.replace('.', ' ').lower().split())


def texto(valor):
    return ' '.join((valor or '').split())


@dataclass
class Reporte:
    titulo: str
    titular: str
    filas: list


def leer_reporte(contenido, tipo):
    """`tipo` = 'productos', 'clientes' o 'proveedores'. Falla si el archivo es de otro reporte."""
    if isinstance(contenido, bytes):
        try:
            contenido = contenido.decode('utf-8-sig')
        except UnicodeDecodeError:
            contenido = contenido.decode('cp1252')
    lineas = contenido.splitlines()
    primera = 'cod principal' if tipo == 'productos' else 'no'
    for inicio, linea in enumerate(lineas):
        if clave(linea.split('\t')[0]) == primera:
            break
    else:
        raise ValueError(f'No es un reporte de {tipo} de Facturero Móvil: falta la fila de títulos.')
    cabecera = [texto(linea.replace('\t', ' ')) for linea in lineas[:inicio] if linea.strip()]
    titulo = next((c for c in cabecera if clave(c).startswith('reporte')), '')
    if tipo not in clave(titulo):
        raise ValueError(f'No es un reporte de {tipo} de Facturero Móvil (título: «{titulo or "sin título"}»).')
    generado = next((c.split(':', 1)[1] for c in cabecera if clave(c).startswith('generado por')), '')
    titular = texto(generado) or next((c for c in cabecera if not clave(c).startswith(('reporte', 'facturero', 'fecha'))), '')
    columnas = [clave(c) for c in lineas[inicio].split('\t')]
    filas = []
    for numero, linea in enumerate(lineas[inicio + 1:], start=inicio + 2):
        if not linea.strip():
            continue
        celdas = linea.split('\t')
        fila = {c: (celdas[i] if i < len(celdas) else '') for i, c in enumerate(columnas) if c}
        fila['_linea'] = numero
        filas.append(fila)
    return Reporte(titulo=titulo, titular=titular, filas=filas)


@dataclass
class Informe:
    creados: dict = field(default_factory=lambda: {'categorías': 0, 'productos': 0, 'clientes': 0, 'proveedores': 0})
    omitidos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    archivos: list = field(default_factory=list)   # códigos de barra generados: se borran si la importación se deshace

    def omitir(self, tipo, fila, referencia, motivo):
        self.omitidos.append({'tipo': tipo, 'linea': fila['_linea'], 'referencia': referencia, 'motivo': motivo})

    def avisar(self, tipo, fila, referencia, aviso):
        self.avisos.append({'tipo': tipo, 'linea': fila['_linea'], 'referencia': referencia, 'aviso': aviso})


def _correos(valor):
    """(primer correo válido, otros válidos, no válidos)."""
    correos = separar_correos(valor)
    validos = [c for c in correos if correo_valido(c)]
    return (validos[0] if validos else ''), validos[1:], [c for c in correos if c not in validos]


def _telefono(valor, largo=10):
    """Primer número del campo, solo dígitos; vacío si no tiene entre 7 y `largo` dígitos."""
    primero = re.split(r'[,;/]', valor or '')[0]
    digitos = solo_digitos(primero)
    return digitos if 7 <= len(digitos) <= largo else ''


def _identificacion(tipo_texto, numero):
    """(código de tipo, número) o (None, motivo) si el sistema no la aceptaría (mismas reglas que el formulario)."""
    tipo = TIPOS_IDENTIFICACION.get(clave(tipo_texto))
    if tipo is None:
        return None, f'tipo de identificación desconocido: «{texto(tipo_texto)}»'
    numero, errores = validar_identificacion(tipo, numero)
    if tipo == '07' or numero == CONSUMIDOR_FINAL:
        return None, 'consumidor final: la empresa ya tiene el suyo'
    if errores:
        return None, f'{errores[0][1]} ({numero})'
    return tipo, numero


def _guardar(objeto):
    with transaction.atomic():
        objeto.save()


def borrar_archivos(nombres):
    almacen = Product._meta.get_field('barcode').storage
    for nombre in nombres:
        if nombre:
            almacen.delete(nombre)


def importar_productos(filas, informe):
    codigos = set(Product.objects.values_list('code', flat=True))
    categorias = {}
    for fila in filas:
        codigo, nombre = texto(fila.get('cod principal')), texto(fila.get('descripcion'))
        if not codigo or not nombre:
            informe.omitir('producto', fila, codigo or nombre, 'sin código o sin descripción')
            continue
        if len(codigo) > 20:
            informe.omitir('producto', fila, codigo, 'el código tiene más de 20 caracteres')
            continue
        if codigo in codigos:
            informe.omitir('producto', fila, codigo, 'ya existe un producto con este código')
            continue
        if clave(fila.get('estado', 'activo')) not in ('', 'activo'):
            informe.omitir('producto', fila, codigo, f'«{texto(fila.get("estado"))}» en Facturero Móvil')
            continue
        tarifa = TARIFAS.get(clave(fila.get('tarifa iva')).replace(' ', ''))
        if tarifa is None:
            informe.omitir('producto', fila, codigo, f'tarifa de IVA desconocida: «{texto(fila.get("tarifa iva"))}»')
            continue
        try:
            valor = Decimal(texto(fila.get('valor')).replace(',', '.') or '0')
        except InvalidOperation:
            informe.omitir('producto', fila, codigo, f'valor no numérico: «{texto(fila.get("valor"))}»')
            continue
        if valor < 0 or valor >= Decimal('10000000'):
            informe.omitir('producto', fila, codigo, f'valor fuera de rango: {valor}')
            continue
        if valor != valor.quantize(CENTAVO):
            informe.avisar('producto', fila, codigo, f'valor {valor} redondeado a 2 decimales')
        if texto(fila.get('tarifa ice')):
            informe.avisar('producto', fila, codigo, f'tarifa ICE «{texto(fila.get("tarifa ice"))}» no migrada')
        nombre_categoria = texto(fila.get('categoria'))
        if clave(nombre_categoria) in ('', 'ninguna'):
            nombre_categoria = texto(fila.get('tipo')) or 'General'
        nombre_categoria = nombre_categoria[:50]
        if nombre_categoria not in categorias:
            categoria, creada = Category.objects.get_or_create(name=nombre_categoria)
            categorias[nombre_categoria] = categoria
            informe.creados['categorías'] += int(creada)
        if len(nombre) > 150:
            informe.avisar('producto', fila, codigo, 'descripción recortada a 150 caracteres (completa en «Descripción»)')
        auxiliar = texto(fila.get('cod auxiliar'))
        descripcion = '; '.join(p for p in ((nombre if len(nombre) > 150 else ''),
                                             (f'Código auxiliar: {auxiliar}' if auxiliar else '')) if p) or None
        inventariado = clave(fila.get('control inventario')) == 'si'
        try:
            existencias = int(Decimal(texto(fila.get('existencias')).replace(',', '.') or '0')) if inventariado else 0
        except InvalidOperation:
            existencias = 0
            informe.avisar('producto', fila, codigo, 'existencias no numéricas: quedan en 0')
        producto = Product(code=codigo, name=nombre[:150], description=descripcion, category=categorias[nombre_categoria],
                           price=Decimal('0.00'), pvp=valor.quantize(CENTAVO, ROUND_HALF_UP), inventoried=inventariado,
                           stock=existencias, tarifa_iva=tarifa)
        try:
            _guardar(producto)
        except Exception as error:
            borrar_archivos([producto.barcode.name])
            informe.omitir('producto', fila, codigo, f'no se pudo guardar ({error.__class__.__name__}: {error})')
            continue
        informe.archivos.append(producto.barcode.name)
        codigos.add(codigo)
        informe.creados['productos'] += 1


def importar_clientes(filas, informe):
    existentes = set(Client.objects.values_list('dni', flat=True))
    for fila in filas:
        nombre = texto(fila.get('razon social'))[:150]
        tipo, numero = _identificacion(fila.get('tipo identificacion'), fila.get('identificacion'))
        referencia = f'{nombre} ({texto(fila.get("identificacion"))})'
        if tipo is None:
            informe.omitir('cliente', fila, referencia, numero)
            continue
        if not nombre:
            informe.omitir('cliente', fila, referencia, 'sin razón social')
            continue
        if numero in existentes:
            informe.omitir('cliente', fila, referencia, 'ya existe un cliente con esta identificación')
            continue
        correo, otros, invalidos = _correos(fila.get('email'))
        adicionales = unir_correos(otros, 500)
        if len(adicionales) < len(', '.join(otros)):
            informe.avisar('cliente', fila, referencia, 'correos adicionales recortados a 500 caracteres')
        if invalidos:
            informe.avisar('cliente', fila, referencia, f'correo no válido, no migrado: {", ".join(invalidos)}')
        telefono = _telefono(fila.get('telefonos'))
        if texto(fila.get('telefonos')) and not telefono:
            informe.avisar('cliente', fila, referencia, f'teléfono no válido, no migrado: {texto(fila.get("telefonos"))}')
        condicion = texto(fila.get('observaciones'))
        if clave(condicion) not in CONDICIONES_CONTADO:
            informe.avisar('cliente', fila, referencia, f'observación no migrada: «{condicion}»')
        try:
            with transaction.atomic():
                usuario = User(username=numero if not User.objects.filter(username=numero).exists() else f'{numero}-{uuid.uuid4().hex[:8]}',
                               names=nombre, email=correo or None, is_active=False)
                usuario.set_unusable_password()
                usuario.save()
                Client(user=usuario, dni=numero, identification_type=tipo, mobile=telefono, extra_emails=adicionales,
                       address=texto(fila.get('direccion'))[:500] or 'S/N', send_email_invoice=bool(correo)).save()
        except Exception as error:
            informe.omitir('cliente', fila, referencia, f'no se pudo guardar ({error.__class__.__name__}: {error})')
            continue
        existentes.add(numero)
        informe.creados['clientes'] += 1


def importar_proveedores(filas, informe):
    actuales = list(Provider.objects.values_list('ruc', 'name', 'mobile', 'email'))
    rucs, nombres, telefonos, correos = (set(columna) for columna in zip(*actuales)) if actuales else (set(), set(), set(), set())
    for fila in filas:
        nombre = texto(fila.get('razon social'))[:100]
        tipo, numero = _identificacion(fila.get('tipo identificacion'), fila.get('identificacion'))
        referencia = f'{nombre} ({texto(fila.get("identificacion"))})'
        correo, otros, invalidos = _correos(fila.get('email'))
        telefono = _telefono(fila.get('telefonos'))
        motivo = (numero if tipo is None else
                  'sin razón social' if not nombre else
                  'ya existe un proveedor con este RUC' if numero in rucs else
                  'ya existe un proveedor con esta razón social' if nombre in nombres else
                  f'el teléfono «{telefono or "vacío"}» ya lo tiene otro proveedor' if telefono in telefonos else
                  f'el correo «{correo or "vacío"}» ya lo tiene otro proveedor' if correo in correos else
                  'correo de más de 50 caracteres' if len(correo) > 50 else None)
        if motivo:
            informe.omitir('proveedor', fila, referencia, motivo)
            continue
        if otros:
            informe.avisar('proveedor', fila, referencia, f'correos adicionales no migrados: {", ".join(otros)}')
        if invalidos:
            informe.avisar('proveedor', fila, referencia, f'correo no válido, no migrado: {", ".join(invalidos)}')
        try:
            _guardar(Provider(name=nombre, ruc=numero, mobile=telefono, email=correo, address=texto(fila.get('direccion')) or None))
        except Exception as error:
            informe.omitir('proveedor', fila, referencia, f'no se pudo guardar ({error.__class__.__name__}: {error})')
            continue
        rucs.add(numero)
        nombres.add(nombre)
        telefonos.add(telefono)
        correos.add(correo)
        informe.creados['proveedores'] += 1


IMPORTADORES = {'proveedores': importar_proveedores, 'productos': importar_productos, 'clientes': importar_clientes}


class _Ensayo(Exception):
    """Deshace la transacción de un ensayo."""


def importar(empresa, reportes, aplicar=False):
    """`reportes` = {'productos' | 'clientes' | 'proveedores': Reporte}. Todo o nada, en una sola transacción.
    Sin `aplicar` es un ensayo: se deshace al final y se borran los códigos de barra que se generaron."""
    informe = Informe()
    try:
        with company_context(empresa), transaction.atomic():
            for tipo, importador in IMPORTADORES.items():
                if tipo in reportes:
                    importador(reportes[tipo].filas, informe)
            if not aplicar:
                raise _Ensayo
    except _Ensayo:
        borrar_archivos(informe.archivos)
    except BaseException:
        borrar_archivos(informe.archivos)
        raise
    return informe
