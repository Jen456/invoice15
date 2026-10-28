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


def retencion_recibida_de(documento) -> RetencionLeida:
    """Lee el XML del 07 importado (v1.0.0 y v2.0.0) y lo entrega como RetencionLeida.

    Exige cod_doc '07', estado_procesamiento 'procesado', clasificación 'recibido' y una verificación que no sea
    no_autorizada_sri, no_encontrada_sri ni discrepancia_sri; si no, ErrorImportacion. v1.0.0: agrupa las líneas por
    (codDocSustento, numDocSustento, fechaEmisionDocSustento); v2.0.0: un SustentoLeido por docSustento. No mira el
    estado de revisión (lee también un documento ya vinculado).
    """
    raise NotImplementedError('Lo implementa Compras (O1): espec-etapa2-compras §3.7.')


def marcar_incorporado(documento, usuario, descripcion: str) -> None:
    """Deja el documento «vinculado» al registrar sus retenciones recibidas (la llama O2 una vez por documento).

    Bloquea el documento (select_for_update(of=('self',))). Idempotente: si ya está vinculado, no hace nada.
    Descartado → ErrorImportacion('El documento está descartado: reábrelo antes'). Desde pendiente o aprobado pone
    vinculado, revisado_por/en y el evento «incorporado» con la descripción (p. ej. «Retenciones recibidas #12 y #13»).
    """
    raise NotImplementedError('Lo implementa Compras (O1): espec-etapa2-compras §3.7.')


def desmarcar_incorporado(documento, usuario, motivo: str) -> None:
    """Devuelve a «pendiente» un documento vinculado cuando ya no le queda ninguna retención recibida registrada.

    Idempotente: si está vinculado, lo pasa a pendiente con el evento «desincorporado» y el motivo; en otro estado no
    hace nada. La llama O2 al anular la última retención recibida de ese documento.
    """
    raise NotImplementedError('Lo implementa Compras (O1): espec-etapa2-compras §3.7.')
