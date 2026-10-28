"""Vigencias de la Res. NAC-DGERCGC26-00000028 en el catálogo de retenciones (D0, Fase A): sin cambio fiscal.

Catálogo ATS del SRI (actualización 06/08/2026; sha256 bd3f7834…), tabla 3.10: el bloque «desde 01/03/2026» tiene el
310 en 1 y el 332E en 0; el bloque «desde 01/08/2026» los pone en «1 /0» y «0 /1 según resolución
NAC-DGERCGC26-00000028». El bloque 06/08/2026 solo cambia el texto del 3440. El DIMM ATS 1.19.0 tiene el 310 al 1,00
fijo hasta el 2026-07-31 y libre (base 0,00) desde el 2026-08-01; el 332E es libre desde 2018.

- 310: la fila de 0004 se cierra el 31/07/2026 y queda fija; la nueva, desde el 01/08/2026, sigue en 1,00 editable.
- 332E: igual, 0,00 editable en las dos filas.
- 3440: una sola fila; la fuente anota que su concepto es el del bloque 06/08/2026.
- Las demás filas quedan con vigente_desde NULL: inicio no documentado en esta revisión (no se inventan fechas).
Hoy (y desde el 01/08/2026) los porcentajes por defecto y la regla de % editable no cambian. Lo que admite cada
escenario de la resolución (dudas D0-b…f) es la Fase B.

Guardia: si el 310 o el 332E no tienen los valores de 0004 (se editaron en /plataforma/), se detiene sin tocar nada.
Vuelta: los detalles de retención que apunten a las filas nuevas quedan sin fila (NULL), esas filas se borran y las
de 0004 (las únicas sin inicio del código) se reabren aunque su cierre se haya movido (el 310 vuelve a ser editable).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import migrations

# Inicio de la vigencia nueva: el del Catálogo ATS y el DIMM, que validan por mes. Duda D0-a abierta: la resolución
# dice regir desde su firma (31/07/2026) y el art. 11 del Código Tributario apuntaría a su publicación en el Registro
# Oficial (03/08/2026) o al 01/09/2026. Sin efecto práctico: el sistema solo emite con la fecha del día y su primera
# retención es posterior a cualquiera de esas fechas.
INICIO_RES_28 = date(2026, 8, 1)
FIN_ANTERIOR = INICIO_RES_28 - timedelta(days=1)

# Lo que cargó 0004: (porcentaje, porcentaje editable, disponible, concepto).
CARGADO_EN_0004 = {
    '310': ('1.00', True, True, 'Servicio de transporte privado de pasajeros o transporte público o privado de carga'),
    '332E': ('0.00', True, True, 'Valores entregados por las cooperativas de transporte a sus socios'),
}

AYUDA = ('Desde el 01/08/2026 el Catálogo ATS admite {valores} en este código según la Res. NAC-DGERCGC26-00000028 '
         '(transporte terrestre comercial, excepto taxis). El porcentaje depende de quién paga a quién (operadora, socio o '
         'accionista, cliente) y de si el servicio se presta con unidades propias o de los socios; para las operadoras '
         'que continúan facturando a través de sus socios rige un régimen transitorio hasta el 31/12/2026. El sistema '
         'propone {defecto} %: confirma el porcentaje con tu contador.')
FUENTE = ('Catálogo ATS SRI (06/08/2026), tabla 3.10, bloque desde 01/08/2026: "{celda} según resolución '
          'NAC-DGERCGC26-00000028"; Res. NAC-DGERCGC26-00000028 (RO 5S 339, 03/08/2026)')
NUEVAS = {
    '310': dict(porcentaje='1.00', fuente=FUENTE.format(celda='1 /0'), ayuda=AYUDA.format(valores='1 % o 0 %', defecto=1)),
    '332E': dict(porcentaje='0.00', fuente=FUENTE.format(celda='0 /1'), ayuda=AYUDA.format(valores='0 % o 1 %', defecto=0)),
}
NOTA_3440 = '; concepto según bloque 06/08/2026'


def adelante(apps, schema_editor):
    CodigoRetencion = apps.get_model('comprobantes', 'CodigoRetencion')
    anteriores = {}
    for codigo, (porcentaje, editable, activo, concepto) in CARGADO_EN_0004.items():
        fila = CodigoRetencion.objects.filter(impuesto='1', codigo=codigo).first()
        if fila is None or (fila.porcentaje, fila.porcentaje_editable, fila.activo, fila.concepto) != \
                (Decimal(porcentaje), editable, activo, concepto):
            raise RuntimeError(f'0015_vigencias_res_28: el código de renta {codigo} no tiene los valores que cargó 0004 '
                               '(porcentaje, % editable, disponible y concepto): se editó en /plataforma/. No se aplica para no '
                               'pisar esa edición; revisa el catálogo y esta migración antes de volver a migrar.')
        anteriores[codigo] = fila
    for codigo, nueva in NUEVAS.items():
        anterior = anteriores[codigo]
        anterior.vigente_hasta = FIN_ANTERIOR
        if codigo == '310':
            anterior.porcentaje_editable = False   # DIMM: 1,00 fijo («N») hasta el 2026-07-31
        anterior.save(update_fields=['vigente_hasta', 'porcentaje_editable'])
        CodigoRetencion.objects.create(impuesto='1', codigo=codigo, concepto=anterior.concepto, porcentaje=nueva['porcentaje'],
                                       porcentaje_editable=True, comun=anterior.comun, activo=True, fuente=nueva['fuente'],
                                       orden=anterior.orden, vigente_desde=INICIO_RES_28, ayuda=nueva['ayuda'])
    for fila in CodigoRetencion.objects.filter(impuesto='1', codigo='3440').exclude(fuente__endswith=NOTA_3440):
        fila.fuente += NOTA_3440
        fila.save(update_fields=['fuente'])


def atras(apps, schema_editor):
    CodigoRetencion = apps.get_model('comprobantes', 'CodigoRetencion')
    RetencionDetalle = apps.get_model('comprobantes', 'RetencionDetalle')
    nuevas = CodigoRetencion.objects.filter(impuesto='1', codigo__in=NUEVAS, vigente_desde=INICIO_RES_28)
    posteriores = sorted(CodigoRetencion.objects.filter(vigente_desde__isnull=False).exclude(pk__in=nuevas)
                         .values_list('codigo', flat=True))
    if posteriores:
        raise RuntimeError('0015_vigencias_res_28: hay vigencias creadas después de esta migración (códigos '
                           f'{", ".join(posteriores)}). Quítalas en /plataforma/ antes de revertir: 0004 admite una fila por código.')
    if schema_editor.connection.vendor == 'postgresql':
        # Seguridad por filas: los detalles son de todas las empresas (como desplegar.sh, con app.platform = on).
        schema_editor.execute("SELECT set_config('app.platform', 'on', true)")
    RetencionDetalle.objects.filter(codigo_catalogo__in=nuevas).update(codigo_catalogo=None)
    nuevas.delete()
    for codigo in NUEVAS:
        cambios = {'vigente_hasta': None, **({'porcentaje_editable': True} if codigo == '310' else {})}
        # Por identidad (la fila sin inicio es la de 0004; hay una sola por código), no por su fecha de cierre.
        CodigoRetencion.objects.filter(impuesto='1', codigo=codigo, vigente_desde__isnull=True).update(**cambios)
    for fila in CodigoRetencion.objects.filter(impuesto='1', codigo='3440', fuente__endswith=NOTA_3440):
        fila.fuente = fila.fuente[:-len(NOTA_3440)]
        fila.save(update_fields=['fuente'])


class Migration(migrations.Migration):

    dependencies = [('comprobantes', '0014_codigoretencion_vigencias')]

    operations = [migrations.RunPython(adelante, atras)]
