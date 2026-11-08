"""«Configuración → Diseño de factura» (piloto): cinco plantillas de FacturaPorAquí y los colores del comercio para el RIDE
de las facturas NUEVAS.

- Piloto: FPA_DISENO_FACTURA_PILOTO (RUC), con la regla de complemento_habilitado (core/suscripciones/reglas.py): «*» solo
  en desarrollo y en las pruebas automáticas; un RUC de la lista que comparte otra empresa no habilita. Fuera del piloto el
  módulo no aparece en el menú, sus URL no abren y las facturas nuevas no reciben copia (RIDE original).
- DisenoFactura (core/configuracion/models.py): uno por empresa; sin fila, sin personalización.
- Copia en la factura: core/pos/emision.preparar() guarda diseno_efectivo() en Sale.ride_diseno en la PRIMERA firma; los
  reintentos no la cambian. Sale.ride_pdf() arma el RIDE desde esa copia; sin copia (históricas), el original.
- Logo y nombre comercial: los de la empresa, como hasta ahora. El establecimiento (Establishment) solo tiene nombre y
  dirección, y el RIDE debe coincidir con el XML autorizado, cuyo nombreComercial es company.tradename (lo compara
  core/comprobantes/fidelidad.py). Ningún estilo cambia un dato del comprobante: solo colores, bordes y espaciado.
"""
from django.conf import settings
from django.db import transaction

from core.comprobantes import ride_styles

URL = '/configuracion/diseno-factura/'
MENSAJE_NO_DISPONIBLE = 'El diseño de factura aún no está disponible para esta empresa.'
ERROR_ESTILO = 'Elige uno de los cinco estilos de FacturaPorAquí.'
ERROR_COLOR = 'El color {nombre} debe tener el formato #RRGGBB (por ejemplo, #CA462C).'


def diseno_habilitado(company):
    """La empresa está en el piloto (FPA_DISENO_FACTURA_PILOTO)."""
    from core.suscripciones.reglas import ENTORNOS_LOCALES
    if company is None:
        return False
    lista = {str(x).strip() for x in getattr(settings, 'FPA_DISENO_FACTURA_PILOTO', None) or [] if str(x).strip()}
    if '*' in lista and getattr(settings, 'FPA_ENTORNO', '') in ENTORNOS_LOCALES:
        return True
    if not company.ruc or company.ruc not in lista:
        return False
    from core.pos.models import Company
    # Un RUC de la lista que comparte otra empresa no habilita nada (como en complemento_habilitado).
    return not Company.objects.filter(ruc=company.ruc).exclude(pk=company.pk).exists()


def diseno_guardado(company):
    """DisenoFactura de la empresa o None. Debe correr con esa empresa activa (en PostgreSQL rige la RLS)."""
    from core.configuracion.models import DisenoFactura
    if company is None:
        return None
    return DisenoFactura.all_companies.filter(company_id=company.pk).first()


def diseno_efectivo(company):
    """{id, version, primary, secondary} que recibe una factura nueva, o None (fuera del piloto o sin diseño guardado)."""
    if not diseno_habilitado(company):
        return None
    diseno = diseno_guardado(company)
    if diseno is None:
        return None
    datos = ride_styles.normalize(diseno.estilo, diseno.color_principal, diseno.color_secundario)
    return {'id': datos['id'], 'version': diseno.version, 'primary': datos['primary'], 'secondary': datos['secondary']}


def actual(company):
    """Lo que muestra la pantalla: el diseño guardado (normalizado para leerlo) o la plantilla Clásica por defecto."""
    diseno = diseno_guardado(company)
    if diseno is None:
        return ride_styles.normalize('clasico')
    return ride_styles.normalize(diseno.estilo, diseno.color_principal, diseno.color_secundario)


def validar(estilo, principal, secundario):
    """Valores exactos del formulario → (datos, None) o (None, mensaje). No corrige nada: lo inválido no se guarda."""
    if not isinstance(estilo, str) or estilo not in ride_styles.STYLES:
        return None, ERROR_ESTILO
    for valor, nombre in ((principal, 'principal'), (secundario, 'secundario')):
        if not ride_styles.is_valid_color(valor):
            return None, ERROR_COLOR.format(nombre=nombre)
    return {'estilo': estilo, 'color_principal': principal.upper(), 'color_secundario': secundario.upper()}, None


def _como_registro(diseno):
    if diseno is None:
        return None
    return {'estilo': diseno.estilo, 'color_principal': diseno.color_principal, 'color_secundario': diseno.color_secundario}


def guardar(request, company, datos):
    """Guarda el diseño de la empresa activa (datos ya validados) y lo deja en la auditoría con el antes y el después."""
    from core.configuracion.models import DisenoFactura
    from core.tenancy.models import audit
    with transaction.atomic():
        previo = DisenoFactura.objects.select_for_update().filter(company=company).first()
        antes = _como_registro(previo)
        diseno, _ = DisenoFactura.objects.update_or_create(
            company=company,
            defaults={**datos, 'version': ride_styles.normalize(datos['estilo'])['version'], 'actualizado_por': request.user})
        audit(request, 'diseno_factura_guardado', company=company, antes=antes, despues=_como_registro(diseno))
    return diseno
