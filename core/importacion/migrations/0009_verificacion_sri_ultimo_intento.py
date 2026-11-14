"""«Verificar en el SRI»: el último intento de consulta y estados que no confunden una consulta fallida con un rechazo
(entregas/facturaporaqui/primera-entrega/verificar-sri.md).

Estructura (solo columnas nuevas, opcionales o con valor por defecto; la política de seguridad por filas de 0002 cubre la
fila entera): `ultima_consulta_por`, `ultima_consulta_resultado`, `ultima_consulta_mensaje`, `respuesta_sri_en` y
`consulta_en_curso` en DocumentoImportado. Las dos de texto son NOT NULL con `db_default=''`: el valor por defecto queda en
la base (no solo en Django), porque la versión anterior (0007) sigue insertando sin nombrarlas mientras atiende durante el
cambio de versión, o si se vuelve a ella sin restaurar la base (tests/test_convivencia_versiones.py). En PostgreSQL es un
ADD COLUMN con un DEFAULT constante: no reescribe la tabla. Cambian los textos de `estado_verificacion` (no sus códigos) y el de
`verificado_en`, que sigue siendo la fecha del último intento con cualquier resultado. 'fuera_rango_sri' (0008, nunca
publicada) deja de ser un estado: es una consulta fallida ('sri_no_disponible' con el resultado 'fuera_de_rango').

Datos, ida. El resultado del último intento sale del estado anterior y de la última entrada de la bitácora de la
verificación ('verificacion', 'xml_no_recuperado' o 'xml_recibido'), de la que también salen el usuario y el mensaje:
- verificada_sri → igual, resultado 'autorizado'.
- no_autorizada_sri → igual (sigue sin poder incorporarse), resultado 'rechazo_anterior': el código anterior no guardaba
  el estado exacto que devolvió el SRI (una consulta rechazada por la fecha de emisión también quedaba así), así que no se
  presenta como «rechazo confirmado» y se pide volver a verificar.
- no_encontrada_sri → igual, resultado 'no_encontrado'; si el mensaje era «La clave no es válida», 'sri_no_disponible' con
  'clave_invalida' (no se había consultado al SRI).
- discrepancia_sri → igual, resultado 'discrepancia'; si el SRI devolvió un XML que no se pudo validar (o el documento aún
  no tenía XML con el que comparar), 'sri_no_disponible' con 'respuesta_inesperada': no era una diferencia del archivo.
- sri_no_disponible → igual, resultado 'sin_respuesta' (antes solo lo dejaba una consulta sin respuesta).
- fuera_rango_sri → 'sri_no_disponible', resultado 'fuera_de_rango'.
- en_proceso_sri → igual, resultado 'en_proceso'.
- declarada_en_archivo y sin_autorizacion → iguales, sin intento.
`respuesta_sri_en` = `verificado_en` en las respuestas concluyentes. No se borra ni se recalcula nada más.

`completar()` toca solo los documentos con un estado consultado y sin resultado: al migrar son todos; después solo puede
dejarlos la versión anterior, que no conoce estas columnas, si verifica mientras sigue atendiendo. Por eso la tarea
programada (procesar_importaciones → servicios.completar_consultas_de_la_version_anterior) la vuelve a aplicar con estas
mismas reglas; lo que ya tiene resultado (lo escribió esta versión) no cambia.

Vuelta: 'sri_no_disponible' con 'fuera_de_rango' vuelve a 'fuera_rango_sri' y con 'clave_invalida' a 'no_encontrada_sri'
(lo que hacía el código anterior); los demás códigos existen en 0008 y se quedan. Después se quitan las columnas: el
historial de cada intento sigue en la bitácora.

En PostgreSQL, con la RLS forzada, se ven las filas de todas las empresas con app.platform = 'on' (desplegar.sh migra con
PGOPTIONS="-c app.platform=on"). Si falta, se activa solo dentro de la transacción de esta migración y se restaura.
"""
from contextlib import contextmanager

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

TIPOS_DE_CONSULTA = ('verificacion', 'xml_no_recuperado', 'xml_recibido')
CONCLUYENTES = ('autorizado', 'discrepancia', 'no_autorizado', 'no_encontrado', 'rechazo_anterior')
XML_NO_VALIDADO = ('El XML que devolvió el SRI no se pudo validar', 'El SRI devolvió un XML que no se pudo validar')
NOTA_RECHAZO_ANTERIOR = ('Consulta anterior a esta versión: el SRI devolvió un estado distinto de AUTORIZADO y entonces no '
                         'se guardaba cuál (una consulta rechazada por la fecha de emisión también quedaba así). Vuelve a '
                         'verificar para confirmarlo.')
VERIFICACION = [('sin_autorizacion', 'El XML no trae autorización (sin verificar en el SRI)'),
                ('declarada_en_archivo', 'Autorización declarada en el XML (sin confirmar en el SRI)'),
                ('verificada_sri', 'Autorización confirmada en el SRI'),
                ('discrepancia_sri', 'Difiere de lo autorizado en el SRI'),
                ('no_autorizada_sri', 'Rechazo confirmado por el SRI (NO AUTORIZADO)'),
                ('no_encontrada_sri', 'El SRI no tiene esa clave'),
                ('sri_no_disponible', 'No se pudo verificar en el SRI'),
                ('en_proceso_sri', 'El SRI todavía la está procesando')]
RESULTADOS = [('autorizado', 'Autorización confirmada'),
              ('discrepancia', 'Autorizada en el SRI, pero el archivo importado difiere'),
              ('no_autorizado', 'Rechazo confirmado: NO AUTORIZADO'),
              ('no_encontrado', 'El SRI no tiene un comprobante con esa clave'),
              ('en_proceso', 'El SRI todavía la está procesando'),
              ('fuera_de_rango', 'No se pudo verificar: fecha fuera del rango de la consulta del SRI'),
              ('tiempo_agotado', 'No se pudo verificar: tiempo de espera agotado'),
              ('sin_conexion', 'No se pudo verificar: error de red'),
              ('servicio_no_disponible', 'No se pudo verificar: servicio del SRI no disponible'),
              ('error_sri', 'No se pudo verificar: error del servicio del SRI'),
              ('respuesta_inesperada', 'No se pudo verificar: respuesta inesperada del SRI'),
              ('clave_invalida', 'No se consultó: la clave de acceso no es válida'),
              ('sin_respuesta', 'No se pudo verificar: sin respuesta del SRI'),
              ('rechazo_anterior', 'El SRI no la autorizó en una consulta anterior a esta versión (sin el estado exacto)')]


@contextmanager
def todas_las_empresas(conexion):
    if conexion.vendor != 'postgresql':
        yield
        return
    with conexion.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.platform', true)")
        antes = cursor.fetchone()[0] or ''
        cursor.execute("SELECT set_config('app.platform', 'on', true)")
    try:
        yield
    finally:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT set_config('app.platform', %s, true)", [antes])


def nuevo_estado(documento, evento):
    """(estado_verificacion, ultima_consulta_resultado, mensaje) de un documento migrado."""
    estado, texto = documento.estado_verificacion, (evento.mensaje if evento else '')
    if estado == 'verificada_sri':
        return estado, 'autorizado', texto
    if estado == 'no_autorizada_sri':
        detalle = '; '.join(str(m) for m in ((evento.datos or {}).get('mensajes') or [])) if evento else ''
        return estado, 'rechazo_anterior', ' '.join(filter(None, (NOTA_RECHAZO_ANTERIOR, texto, detalle)))
    if estado == 'no_encontrada_sri':
        if texto.startswith('La clave no es válida'):
            return 'sri_no_disponible', 'clave_invalida', texto
        return estado, 'no_encontrado', texto
    if estado == 'discrepancia_sri':
        if documento.estado_procesamiento == 'pendiente_xml' or texto.startswith(XML_NO_VALIDADO):
            return 'sri_no_disponible', 'respuesta_inesperada', texto
        return estado, 'discrepancia', texto
    if estado == 'sri_no_disponible':
        return estado, 'sin_respuesta', texto
    if estado == 'fuera_rango_sri':
        return 'sri_no_disponible', 'fuera_de_rango', texto
    if estado == 'en_proceso_sri':
        return estado, 'en_proceso', texto
    return estado, '', ''   # declarada_en_archivo, sin_autorizacion: nunca se consultó


def completar(documentos, eventos, conexion):
    """Aplica las reglas de arriba a los documentos con un estado consultado y sin resultado del último intento y devuelve
    cuántos completó. `documentos` y `eventos`: managers que ven todas las empresas. El UPDATE vuelve a exigir el resultado
    vacío: si esta versión verificó el documento entretanto, gana lo suyo."""
    completados = 0
    with todas_las_empresas(conexion):
        pendientes = documentos.filter(ultima_consulta_resultado='').exclude(
            estado_verificacion__in=('declarada_en_archivo', 'sin_autorizacion')).order_by('pk')
        for documento in pendientes.iterator():
            evento = eventos.filter(documento_id=documento.pk, tipo__in=TIPOS_DE_CONSULTA).order_by('-pk').first()
            estado, resultado, mensaje = nuevo_estado(documento, evento)
            completados += documentos.filter(pk=documento.pk, ultima_consulta_resultado='').update(
                estado_verificacion=estado, ultima_consulta_resultado=resultado, ultima_consulta_mensaje=mensaje[:500],
                ultima_consulta_por_id=evento.usuario_id if evento else None,
                respuesta_sri_en=documento.verificado_en if resultado in CONCLUYENTES else None)
    return completados


def adelante(apps, schema_editor):
    completar(apps.get_model('importacion', 'DocumentoImportado').objects,
              apps.get_model('importacion', 'EventoImportacion').objects, schema_editor.connection)


def atras(apps, schema_editor):
    Documento = apps.get_model('importacion', 'DocumentoImportado')
    with todas_las_empresas(schema_editor.connection):
        Documento.objects.filter(estado_verificacion='sri_no_disponible', ultima_consulta_resultado='fuera_de_rango') \
            .update(estado_verificacion='fuera_rango_sri')
        Documento.objects.filter(estado_verificacion='sri_no_disponible', ultima_consulta_resultado='clave_invalida') \
            .update(estado_verificacion='no_encontrada_sri')


class Migration(migrations.Migration):

    dependencies = [
        ('importacion', '0008_estado_fuera_rango_sri'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='documentoimportado',
            name='consulta_en_curso',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Consulta al SRI en curso desde'),
        ),
        migrations.AddField(
            model_name='documentoimportado',
            name='respuesta_sri_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Última respuesta concluyente del SRI'),
        ),
        migrations.AddField(
            model_name='documentoimportado',
            name='ultima_consulta_mensaje',
            field=models.CharField(blank=True, db_default='', default='', max_length=500,
                                   verbose_name='Detalle de la última consulta al SRI'),
        ),
        migrations.AddField(
            model_name='documentoimportado',
            name='ultima_consulta_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                                    to=settings.AUTH_USER_MODEL, verbose_name='Última consulta al SRI hecha por'),
        ),
        migrations.AddField(
            model_name='documentoimportado',
            name='ultima_consulta_resultado',
            field=models.CharField(blank=True, choices=RESULTADOS, db_default='', default='', max_length=25,
                                   verbose_name='Resultado de la última consulta al SRI'),
        ),
        migrations.AlterField(
            model_name='documentoimportado',
            name='verificado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Última consulta al SRI'),
        ),
        migrations.AlterField(
            model_name='documentoimportado',
            name='estado_verificacion',
            field=models.CharField(choices=VERIFICACION, default='sin_autorizacion', max_length=25, verbose_name='Verificación'),
        ),
        migrations.RunPython(adelante, atras),
    ]
