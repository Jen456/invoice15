"""Inicio contable (C1 del contrato contable v9): lo que responde GET /contabilidad/api/inicio/.

No decide nada por su cuenta. Cada parte sale del servicio que ya la decide, para que el inicio nunca diga otra cosa que la
pantalla a la que lleva:

- `acceso` es el contrato de capacidades entero (capacidades.capacidades) y `capacidades`, esos mismos datos en la forma
  corta del contrato v9 (booleanos);
- `etapas.plan_cuentas` cuenta las cuentas de la empresa y mira si hay una importación confirmada; `apertura` sale de la
  configuración y del estado de la apertura (inicio_contable.etapa: `sin_configurar | pendiente | en_revision |
  confirmada`, con `fecha` = el corte); `conciliacion` todavía no existe y lo dice con el texto del registro de funciones;
- `pendientes` llama a la revisión del mes (revision.revisar), al contador de recibos por completar
  (capturas.contar_pendientes) y a la bandeja de documentos importados pendientes de revisión (la consulta de su pantalla).

Dos reglas del contrato que aquí importan:

- una etapa nunca queda «completada» por haber abierto una pantalla: solo se informa lo que hay guardado;
- lo que el usuario no puede consultar no se devuelve en cero. La etapa sale `no_disponible` con su causa y el origen de
  pendientes no aparece en `origenes`; un origen que sí aparece y no tiene entradas es «consultado y sin pendientes»."""
from django.utils import timezone

from core.contabilidad import capacidades as cap
from core.contabilidad import inicio_contable
from core.contabilidad.importar_cuentas import CONFIRMADO
from core.contabilidad.models import Cuenta, ImportacionCuentas
from core.suscripciones import reglas
from core.suscripciones.servicios import estado_de_peticion

# Basta uno para abrir el inicio (los declara el registro de funciones); cada parte de la respuesta vuelve a mirar el suyo.
PERMISOS = cap.funcion_de('inicio').permisos['ver']

SIN_CONFIGURAR, CONFIGURADO, IMPORTADO, NO_DISPONIBLE = 'sin_configurar', 'configurado', 'importado', 'no_disponible'

REVISION, CAPTURAS, IMPORTACION = 'revision', 'capturas', 'importacion'
URL_REVISION, URL_CAPTURAS, URL_IMPORTADOS = '/tributario/revision/', '/adjuntos/capturas/', '/importacion/pendientes/'
# Como el menú llama a esas dos pantallas (core/security/menu.py): el nombre de una y la descripción de la otra, que es
# la que dice que los documentos son importados. Las categorías de la revisión traen su propio nombre.
TITULOS = {CAPTURAS: 'Recibos por completar', IMPORTACION: 'Documentos importados pendientes de revisión'}


# ---------------------------------------------------------------- capacidades (forma corta del contrato v9)

def capacidades_v9(acceso):
    """`{"revision", "libros", "kardex", "plan_cuentas": {"ver", "editar"}}`, leído del mismo `acceso` (ya con la licencia
    y el permiso del rol): las dos formas nunca dicen cosas distintas. Con el plan vencido `editar` es falso."""
    def puede(codigo, accion='ver'):
        return acceso['funciones'][codigo]['acciones'][accion]
    return {'revision': puede('revision'), 'libros': puede('libros'), 'kardex': puede('kardex'),
            'plan_cuentas': {'ver': puede('plan_cuentas'), 'editar': puede('plan_cuentas', 'editar')}}


# ---------------------------------------------------------------- etapas

def etapa_plan_cuentas(acceso):
    """`sin_configurar` sin cuentas (`cuentas: null`, no cero); `importado` si hay un lote confirmado, con la fecha del
    último; `configurado` si las cuentas se crearon a mano. Las desactivadas cuentan: siguen en el plan. A quien no puede
    ver el plan no se le dice cuántas cuentas hay, ni tampoco «sin configurar», que sería afirmar algo que no se le
    muestra: `no_disponible` con la causa del contrato de capacidades."""
    funcion = acceso['funciones']['plan_cuentas']
    etapa = {'estado': NO_DISPONIBLE, 'cuentas': None, 'importado_en': None, 'causa': None}
    if not funcion['acciones']['ver']:
        return {**etapa, 'causa': funcion['texto']}
    cuentas = Cuenta.objects.count()
    if not cuentas:
        return {**etapa, 'estado': SIN_CONFIGURAR}
    # Solo la fecha: `filas` y `resultado` de un lote pueden pesar megas.
    confirmado_en = (ImportacionCuentas.objects.filter(estado=CONFIRMADO).order_by('-confirmado_en', '-id')
                     .values_list('confirmado_en', flat=True).first())
    if confirmado_en is None:
        return {**etapa, 'estado': CONFIGURADO, 'cuentas': cuentas}
    return {**etapa, 'estado': IMPORTADO, 'cuentas': cuentas,
            'importado_en': timezone.localtime(confirmado_en).date().isoformat()}


def _por_construir(codigo):
    """Causa de una etapa que todavía no tiene bloque: el texto del registro de funciones, que es el único que lo explica."""
    return cap.funcion_de(codigo).texto_pendiente


def etapas(acceso):
    return {
        'plan_cuentas': etapa_plan_cuentas(acceso),
        # Bloque 2 (Parte B): valores nuevos de la etapa, aditivos (sin_configurar | pendiente | en_revision | confirmada).
        'apertura': inicio_contable.etapa(acceso),
        # Hasta que exista su bloque. Quien lo construya cambia esta entrada: tests/test_inicio_contable.py falla en cuanto
        # `bancos` deja de estar pendiente en el registro.
        'conciliacion': {'estado': NO_DISPONIBLE, 'causa': _por_construir('bancos')},
    }


# ---------------------------------------------------------------- pendientes

def _pendiente(origen, codigo, titulo, cantidad, url):
    return {'origen': origen, 'codigo': codigo, 'titulo': titulo, 'cantidad': cantidad, 'url': url}


def _de_la_revision(request):
    """Una entrada por categoría de la revisión del mes en curso que tenga algo «por revisar», con el nombre y la cuenta
    que muestra esa pantalla. Las observaciones informativas (cuentas vencidas, respaldos por revisar) no son pendientes:
    la revisión tampoco las suma como tales. El enlace baja al título de la categoría (`id` de tributario/revision.html)."""
    from core.tributario import revision
    mes = timezone.localdate().replace(day=1)
    resumen = revision.revisar(mes, request.company, request)
    url = f'{URL_REVISION}?mes={mes:%Y-%m}'
    return [_pendiente(REVISION, clave, categoria['nombre'], categoria['revisar'], f'{url}#fp-rev-{clave}')
            for clave, categoria in resumen['por_categoria'].items() if categoria['revisar']]


def _de_las_capturas(request):
    """Recibos y notas guardados que nadie completó, de cualquier mes. Los de este mes cuentan también en «Respaldos
    pendientes» de la revisión: las cantidades de dos orígenes no se suman."""
    from core.adjuntos import capturas
    cantidad = capturas.contar_pendientes(request)
    return [_pendiente(CAPTURAS, 'recibo_por_completar', TITULOS[CAPTURAS], cantidad, URL_CAPTURAS)] if cantidad else []


def _de_la_importacion():
    from core.importacion import views as importacion
    from core.importacion.models import DocumentoImportado
    cantidad = DocumentoImportado.objects.filter(importacion.BANDEJAS['pendientes']).count()
    return [_pendiente(IMPORTACION, 'documento_por_revisar', TITULOS[IMPORTACION], cantidad, URL_IMPORTADOS)] if cantidad else []


def _ve_los_importados(request):
    """Tiene el permiso de esa bandeja y el plan de la empresa la incluye: lo mismo que PlanMiddleware le pregunta a una
    consulta de /importacion/ (plan Ilimitado o Multiempresa; vencido, se sigue consultando)."""
    from core.importacion.views import VER
    if not cap.tiene(request, VER):
        return False
    estado = estado_de_peticion(request)
    return not reglas.requiere_ilimitado(URL_IMPORTADOS) or (estado is not None and estado.ilimitado)


def pendientes(request, acceso):
    """`(pendientes, origenes)`: las entradas con algo pendiente y los orígenes que se consultaron para este usuario. Un
    origen que no le corresponde (sin su permiso o sin el plan que lo incluye) no se consulta ni aparece."""
    from core.adjuntos.capturas import VER as VER_CAPTURAS
    fuentes = (
        (REVISION, acceso['funciones']['revision']['acciones']['ver'], lambda: _de_la_revision(request)),
        (CAPTURAS, cap.tiene(request, VER_CAPTURAS), lambda: _de_las_capturas(request)),
        (IMPORTACION, _ve_los_importados(request), _de_la_importacion),
    )
    lista, origenes = [], []
    for origen, aplica, consultar in fuentes:
        if aplica:
            origenes.append(origen)
            lista += consultar()
    return lista, origenes


# ---------------------------------------------------------------- respuesta

def datos(request):
    """El cuerpo de GET /contabilidad/api/inicio/ para la empresa activa y el rol del usuario."""
    acceso = cap.capacidades(request)
    lista, origenes = pendientes(request, acceso)
    return {'empresa': acceso['empresa'], 'capacidades': capacidades_v9(acceso), 'acceso': acceso, 'etapas': etapas(acceso),
            'pendientes': lista, 'origenes': origenes}
