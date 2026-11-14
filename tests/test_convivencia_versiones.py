"""Convivencia de versiones (revisión del PR #1, R1; primera-entrega/plan-de-despliegue.md).

Mientras se publica, la versión de producción (importacion 0007, proformas 0003) sigue atendiendo sobre la base ya
migrada, y vuelve a hacerlo si se revierte el código sin restaurar la base. Sus INSERT no nombran las columnas nuevas: cada
columna NOT NULL que esta entrega agrega a una tabla existente lleva su valor por defecto en la propia base (db_default), no
solo en Django. Lo que esa versión verifica en el SRI después de importacion 0009 lo completa la tarea programada con las
mismas reglas de la migración. Datos ficticios, sin SRI; corre en SQLite y en PostgreSQL (con la RLS forzada)."""
import io

import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddField
from django.db.models import NOT_PROVIDED
from django.utils import timezone

from core.importacion import servicios as sv
from core.importacion.models import DocumentoImportado
from core.proformas.models import Proforma
from core.tenancy.context import company_context, platform_scope
from tests.ayudas_proformas import crear_proforma, datos_ejemplo, productos_por_tarifa
from tests.test_importacion_verificacion_sri import archivos_temporales, dueno, empresa  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

# Migraciones de esta entrega; producción (e0f2902) está en importacion 0007, proformas 0003 y tenancy 0012.
DE_ESTA_ENTREGA = [('importacion', '0008_estado_fuera_rango_sri'), ('importacion', '0009_verificacion_sri_ultimo_intento'),
                   ('proformas', '0004_borrador_factura'), ('tenancy', '0013_acciones_borrador_factura')]
NO_NULAS_AGREGADAS = {('importacion_documentoimportado', 'ultima_consulta_mensaje'),
                      ('importacion_documentoimportado', 'ultima_consulta_resultado'),
                      ('proformas_proforma', 'medio_pago_sugerido'), ('proformas_proforma', 'ocultar_vendedor')}


def modelo_de_produccion(app, migracion, modelo):
    """El modelo tal como lo ve la versión publicada (estado del grafo en su última migración)."""
    return MigrationLoader(connection).project_state([(app, migracion)]).apps.get_model(app, modelo)


def default_en_la_base(tabla, columna):
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute('SELECT column_default FROM information_schema.columns WHERE table_name = %s AND column_name = %s',
                           [tabla, columna])
            return cursor.fetchone()[0]
        cursor.execute(f'PRAGMA table_info({connection.ops.quote_name(tabla)})')
        return next(fila[4] for fila in cursor.fetchall() if fila[1] == columna)


def test_cada_columna_no_nula_que_agrega_la_entrega_tiene_su_default_en_la_base():
    loader = MigrationLoader(connection)
    agregadas = set()
    for clave in DE_ESTA_ENTREGA:
        for op in loader.disk_migrations[clave].operations:
            if isinstance(op, AddField) and not op.field.null:
                assert op.field.db_default is not NOT_PROVIDED, f'{clave}: {op.model_name}.{op.name} sin db_default'
                agregadas.add((f'{clave[0]}_{op.model_name}', op.name))
    assert agregadas == NO_NULAS_AGREGADAS
    for tabla, columna in sorted(agregadas):
        assert default_en_la_base(tabla, columna) is not None, (tabla, columna)


def test_modelos_y_migraciones_coinciden():
    call_command('makemigrations', check=True, dry_run=True, verbosity=0)   # SystemExit(1) si falta una migración


def test_la_version_anterior_importa_y_cotiza_sobre_la_base_migrada(empresa, dueno):  # noqa: F811
    Documento = modelo_de_produccion('importacion', '0007_lotes_de_claves', 'DocumentoImportado')
    Cotizacion = modelo_de_produccion('proformas', '0003_modulo_proformas', 'Proforma')
    base = crear_proforma(empresa, dueno, datos_ejemplo(productos_por_tarifa(empresa)))
    campos = {c.attname: getattr(base, c.attname) for c in Cotizacion._meta.concrete_fields if c.attname != 'id'}
    campos.update(numero=base.numero + 1, numero_completo='PRO-999999')
    with company_context(empresa), transaction.atomic():
        documento = Documento.objects.create(
            company_id=empresa.pk, importado_por_id=dueno.pk, ambiente=1, clave_acceso='2' * 49, origen='xml', cod_doc='01',
            estab='001', pto_emi='001', secuencial='000000002', numero='001-001-000000002',
            emisor_razon_social='EMISOR FICTICIO')
        Documento.objects.filter(pk=documento.pk).update(estado_verificacion='verificada_sri', verificado_en=timezone.now())
        cotizacion = Cotizacion.objects.create(**campos)
    with company_context(empresa):   # esta versión lee lo que escribió la anterior, con los valores por defecto de la base
        actual = DocumentoImportado.objects.get(pk=documento.pk)
        nueva = Proforma.objects.get(pk=cotizacion.pk)
    assert (actual.ultima_consulta_resultado, actual.ultima_consulta_mensaje, actual.ultima_consulta_por_id) == ('', '', None)
    assert (nueva.medio_pago_sugerido, nueva.ocultar_vendedor) == ('', False)


def test_lo_que_verifica_la_version_anterior_se_completa_con_las_reglas_de_0009(empresa, dueno):  # noqa: F811
    Documento = modelo_de_produccion('importacion', '0007_lotes_de_claves', 'DocumentoImportado')
    ahora = timezone.now()
    escritos = {   # secuencial: (estado que escribe la versión anterior, mensaje de su evento)
        '000000401': ('no_autorizada_sri', 'El SRI responde que la clave NO está autorizada.'),
        '000000402': ('no_encontrada_sri', 'La clave no es válida.'),
        '000000403': ('verificada_sri', 'Coincide con el comprobante autorizado en el SRI.'),
        '000000404': ('declarada_en_archivo', ''),
    }
    with company_context(empresa):
        for secuencial, (estado, mensaje) in escritos.items():   # importados y verificados por la versión anterior
            documento = Documento.objects.create(
                company_id=empresa.pk, importado_por_id=dueno.pk, ambiente=1, clave_acceso=secuencial.rjust(49, '3'),
                origen='xml', cod_doc='01', estab='001', pto_emi='001', secuencial=secuencial,
                numero=f'001-001-{secuencial}', emisor_razon_social='EMISOR FICTICIO', estado_verificacion=estado,
                verificado_en=ahora if mensaje else None)
            if mensaje:
                sv.evento('verificacion', mensaje, documento=DocumentoImportado.objects.get(pk=documento.pk), usuario=dueno,
                          mensajes=['[80] ERROR'] if estado == 'no_autorizada_sri' else [])
        propio = Documento.objects.create(   # y uno que verificó esta versión: ya tiene su resultado
            company_id=empresa.pk, importado_por_id=dueno.pk, ambiente=1, clave_acceso='4' * 49, origen='xml', cod_doc='01',
            estab='001', pto_emi='001', secuencial='000000405', numero='001-001-000000405',
            emisor_razon_social='EMISOR FICTICIO')
        DocumentoImportado.objects.filter(pk=propio.pk).update(
            estado_verificacion='no_autorizada_sri', verificado_en=ahora, respuesta_sri_en=ahora,
            ultima_consulta_resultado='no_autorizado', ultima_consulta_mensaje='Rechazo confirmado: NO AUTORIZADO')
    salida = io.StringIO()
    call_command('procesar_importaciones', stdout=salida)
    assert 'completados de la versión anterior: 3' in salida.getvalue()
    with company_context(empresa):
        quedan = {d.secuencial: (d.estado_verificacion, d.ultima_consulta_resultado, d.ultima_consulta_por_id,
                                 d.respuesta_sri_en is not None) for d in DocumentoImportado.objects.all()}
        rechazo = DocumentoImportado.objects.get(secuencial='000000401')
    assert quedan == {
        '000000401': ('no_autorizada_sri', 'rechazo_anterior', dueno.pk, True),
        '000000402': ('sri_no_disponible', 'clave_invalida', dueno.pk, False),
        '000000403': ('verificada_sri', 'autorizado', dueno.pk, True),
        '000000404': ('declarada_en_archivo', '', None, False),
        '000000405': ('no_autorizada_sri', 'no_autorizado', None, True),
    }
    assert rechazo.get_estado_verificacion_display() == 'El SRI no la autorizó (consulta anterior: vuelve a verificar)'
    assert '[80] ERROR' in rechazo.ultima_consulta_mensaje
    with platform_scope():   # una segunda vez no cambia nada
        assert sv.completar_consultas_de_la_version_anterior() == 0
    salida = io.StringIO()
    call_command('procesar_importaciones', stdout=salida)
    assert 'versión anterior' not in salida.getvalue()
