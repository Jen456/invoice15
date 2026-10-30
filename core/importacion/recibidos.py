"""Comprobante de retención (07) recibido e importado: lectura, marca del documento y paso a «Retenciones recibidas».

Interfaz entre Compras (O1, dueña de este archivo e implementa las funciones) y Ventas (O2, que registra la retención
recibida con `core.comprobantes.retenciones_recibidas.registrar_desde_importacion`). El commit B0 del integrador deja
las dataclasses y las firmas (espec-etapa2-compras §3.7) para que las dos ramas trabajen contra el mismo contrato.

Reparto del flujo «07 importado → RetencionRecibida»: O1 lee el XML y entrega una RetencionLeida; O2 crea una
RetencionRecibida por sustento, todo o nada, y llama a marcar_incorporado una sola vez al final; al anular la última
retención registrada de ese documento, O2 llama a desmarcar_incorporado.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


@dataclass(frozen=True)
class RetencionLineaLeida:
    impuesto: str              # '1' renta, '2' IVA, '6' ISD (código del XML); O2 rechaza el 6 (impuesto_no_soportado)
    codigo_retencion: str
    base_imponible: Decimal
    porcentaje: Decimal
    valor_retenido: Decimal


@dataclass(frozen=True)
class SustentoLeido:
    cod_doc_sustento: str      # normalmente '01'
    num_doc_sustento: str      # 15 dígitos sin guiones (como en el XML)
    fecha_emision_doc_sustento: date | None
    num_aut_doc_sustento: str  # '' en v1.0.0
    cod_sustento: str          # '' en v1.0.0
    retenciones: tuple[RetencionLineaLeida, ...]

    @property
    def numero_con_guiones(self) -> str:   # 'EEE-PPP-SSSSSSSSS', como Sale.voucher_number_full
        n = self.num_doc_sustento
        return f'{n[:3]}-{n[3:6]}-{n[6:]}' if len(n) == 15 else n


@dataclass(frozen=True)
class RetencionLeida:
    documento_id: int
    clave_acceso: str
    ambiente: int              # 1 pruebas | 2 producción: DocumentoImportado.ambiente (dígito 24 de la clave)
    numero: str                # EEE-PPP-SSSSSSSSS del agente de retención
    fecha_emision: date
    periodo_fiscal: str        # 'mm/aaaa'
    agente_ruc: str
    agente_razon_social: str
    version: str               # '1.0.0' | '2.0.0'
    total_retenido: Decimal
    verificado_sri: bool       # estado_verificacion == 'verificada_sri'
    estado_verificacion: str   # el valor de DocumentoImportado.VERIFICACION
    sustentos: tuple[SustentoLeido, ...]


VERIFICACIONES_QUE_BLOQUEAN = ('no_autorizada_sri', 'no_encontrada_sri', 'discrepancia_sri')
URL_RETENCIONES_RECIBIDAS = '/comprobantes/retenciones-recibidas/'


def _error(mensaje, codigo=''):
    from core.importacion.servicios import ErrorImportacion
    return ErrorImportacion(mensaje, codigo=codigo)


def _fecha(valor):
    if isinstance(valor, date) or not valor:
        return valor or None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _decimal(valor):
    return Decimal(str(valor)) if valor not in (None, '') else Decimal('0.00')


def retencion_recibida_de(documento) -> RetencionLeida:
    """Lee el XML del 07 importado (v1.0.0 y v2.0.0) y lo entrega como RetencionLeida.

    Exige cod_doc '07', estado_procesamiento 'procesado', clasificación 'recibido' y una verificación que no sea
    no_autorizada_sri, no_encontrada_sri ni discrepancia_sri; si no, ErrorImportacion. v1.0.0: agrupa las líneas por
    (codDocSustento, numDocSustento, fechaEmisionDocSustento); v2.0.0: un SustentoLeido por docSustento. No mira el
    estado de revisión (lee también un documento ya vinculado).
    """
    from core.importacion.compras import comprobante_completo
    if documento.cod_doc != '07':
        raise _error('El documento no es un comprobante de retención (07).', 'no_es_07')
    if documento.estado_procesamiento != 'procesado':
        raise _error('El documento todavía no tiene su XML autorizado.', 'sin_xml')
    if documento.clasificacion != 'recibido':
        raise _error('Solo se registra una retención que recibió la empresa (la empresa es el sujeto retenido).', 'no_recibido')
    if documento.estado_verificacion in VERIFICACIONES_QUE_BLOQUEAN:
        raise _error(f'No se puede registrar: {documento.get_estado_verificacion_display().lower()}.', 'verificacion')
    retencion = comprobante_completo(documento).get('retencion') or {}
    docs = retencion.get('docs_sustento') or []
    if not docs:
        raise _error('No se pudo leer la retención del XML (sin documentos sustento).', 'sin_xml')
    sustentos = tuple(SustentoLeido(
        cod_doc_sustento=str(s.get('cod_doc_sustento') or ''), num_doc_sustento=str(s.get('num_doc_sustento') or ''),
        fecha_emision_doc_sustento=_fecha(s.get('fecha_emision_doc_sustento')),
        num_aut_doc_sustento=str(s.get('num_aut_doc_sustento') or ''), cod_sustento=str(s.get('cod_sustento') or ''),
        retenciones=tuple(RetencionLineaLeida(
            impuesto=str(r.get('codigo') or ''), codigo_retencion=str(r.get('codigo_retencion') or ''),
            base_imponible=_decimal(r.get('base_imponible')), porcentaje=_decimal(r.get('porcentaje_retener')),
            valor_retenido=_decimal(r.get('valor_retenido'))) for r in s.get('retenciones') or []))
        for s in docs)
    total = sum((r.valor_retenido for s in sustentos for r in s.retenciones), Decimal('0.00'))
    return RetencionLeida(
        documento_id=documento.pk, clave_acceso=documento.clave_acceso, ambiente=documento.ambiente, numero=documento.numero,
        fecha_emision=documento.fecha_emision, periodo_fiscal=str(retencion.get('periodo_fiscal') or ''),
        agente_ruc=documento.emisor_ruc, agente_razon_social=documento.emisor_razon_social,
        version=str(retencion.get('version') or documento.version or ''), total_retenido=total,
        verificado_sri=documento.estado_verificacion == 'verificada_sri', estado_verificacion=documento.estado_verificacion,
        sustentos=sustentos)


def marcar_incorporado(documento, usuario, descripcion: str) -> None:
    """Deja el documento «vinculado» al registrar sus retenciones recibidas (la llama O2 una vez por documento).

    Bloquea el documento (select_for_update(of=('self',))). Idempotente: si ya está vinculado, no hace nada.
    Descartado → ErrorImportacion('El documento está descartado: reábrelo antes'). Desde pendiente o aprobado pone
    vinculado, revisado_por/en y el evento «incorporado» con la descripción (p. ej. «Retenciones recibidas #12 y #13»).
    """
    from core.importacion.models import DocumentoImportado
    from core.importacion.servicios import evento
    with transaction.atomic():
        actual = DocumentoImportado.objects.select_for_update(of=('self',)).get(pk=documento.pk)
        if actual.estado_revision == 'vinculado':
            documento.estado_revision = actual.estado_revision
            return
        if actual.estado_revision == 'descartado':
            raise _error('El documento está descartado: reábrelo antes', 'descartado')
        ahora = timezone.now()
        DocumentoImportado.objects.filter(pk=actual.pk).update(estado_revision='vinculado', revisado_por=usuario,
                                                               revisado_en=ahora)
        evento('incorporado', descripcion or 'Registrado en Retenciones recibidas.', documento=actual, usuario=usuario)
    documento.estado_revision, documento.revisado_por, documento.revisado_en = 'vinculado', usuario, ahora


def desmarcar_incorporado(documento, usuario, motivo: str) -> None:
    """Devuelve a «pendiente» un documento vinculado cuando ya no le queda ninguna retención recibida registrada.

    Idempotente: si está vinculado, lo pasa a pendiente con el evento «desincorporado» y el motivo; en otro estado no
    hace nada. La llama O2 al anular la última retención recibida de ese documento.
    """
    from core.importacion.models import DocumentoImportado
    from core.importacion.servicios import evento
    with transaction.atomic():
        actual = DocumentoImportado.objects.select_for_update(of=('self',)).get(pk=documento.pk)
        if actual.estado_revision != 'vinculado':
            return
        ahora = timezone.now()
        DocumentoImportado.objects.filter(pk=actual.pk).update(estado_revision='pendiente', revisado_por=usuario,
                                                               revisado_en=ahora)
        evento('desincorporado', motivo or 'Se anuló la retención recibida: el documento vuelve a estar pendiente.',
               documento=actual, usuario=usuario)
    documento.estado_revision, documento.revisado_por, documento.revisado_en = 'pendiente', usuario, ahora


def bloqueos_retencion(documento) -> list[dict]:
    """[{codigo, texto}] que impiden registrar el 07 en «Retenciones recibidas» (para la pantalla, §6.J)."""
    bloqueos = []

    def bloqueo(codigo, texto, **extra):
        bloqueos.append({'codigo': codigo, 'texto': texto, **extra})

    if documento.cod_doc != '07':
        bloqueo('no_es_07', 'El documento no es un comprobante de retención (07).')
    if documento.clasificacion != 'recibido':
        bloqueo('no_recibido', 'Solo se registra una retención que recibió la empresa (la empresa es el sujeto retenido).')
    if documento.estado_procesamiento != 'procesado' or documento.archivo_xml_id is None:
        bloqueo('sin_xml', 'El documento todavía no tiene su XML autorizado.')
    if documento.estado_verificacion in VERIFICACIONES_QUE_BLOQUEAN:
        bloqueo('verificacion', f'No se puede registrar: {documento.get_estado_verificacion_display().lower()}.')
    if documento.estado_revision == 'descartado':
        bloqueo('descartado', 'El documento está descartado: reábrelo antes.')
    if documento.estado_revision == 'vinculado':
        bloqueo('ya_registrada', 'Esta retención ya está registrada en Retenciones recibidas.', url=URL_RETENCIONES_RECIBIDAS)
    return bloqueos


def exige_confirmar_sin_verificar(documento) -> bool:
    """Mismo criterio que la revisión de importación: sin verificación en el SRI y con la regla que la exige."""
    from core.importacion.servicios import reglas_de
    return documento.estado_verificacion != 'verificada_sri' and reglas_de(documento.company).exigir_verificacion


def _servicio_registro():
    """(función, clase de error) de O2. Indirección para que las pruebas de O1 la sustituyan antes de la fusión."""
    from core.comprobantes.retenciones_recibidas import ErrorRetencionRecibida, registrar_desde_importacion
    return registrar_desde_importacion, ErrorRetencionRecibida


def registrar_en_retenciones_recibidas(company, usuario, documento, *, confirmar_sin_verificar=False) -> list:
    """Registra el 07 en «Retenciones recibidas» con el servicio de Ventas (O2): una RetencionRecibida por sustento, todo o
    nada, y la marca del documento una sola vez (la hace O2 con marcar_incorporado). Devuelve lo que devuelva O2."""
    bloqueos = bloqueos_retencion(documento)
    if bloqueos:
        raise _error(bloqueos[0]['texto'], bloqueos[0]['codigo'])
    if exige_confirmar_sin_verificar(documento) and not confirmar_sin_verificar:
        raise _error('El documento no está verificado en el SRI. Verifícalo o confirma que lo registras sin verificar.',
                     'confirmar_sin_verificar')
    leida = retencion_recibida_de(documento)
    try:
        registrar, error_de_ventas = _servicio_registro()
    except ImportError:
        raise _error('El registro de retenciones recibidas todavía no está disponible', 'no_disponible')
    try:
        return registrar(company, usuario, documento, leida)
    except error_de_ventas as e:
        raise _error(str(e), getattr(e, 'codigo', '')) from e
