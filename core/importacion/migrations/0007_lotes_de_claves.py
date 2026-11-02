"""Importación masiva de comprobantes recibidos: lotes de claves de acceso (pegadas o de un reporte del portal del SRI).

Solo columnas nuevas y opciones: `LoteImportacion.origen` y `.reporte`, `EntradaLote.clave` y `.sugerencias`, el tipo
'reporte' de ArchivoImportado, los orígenes 'lista' y 'reporte' de DocumentoImportado y la verificación 'en_proceso_sri'
(el SRI respondió EN PROCESO: se reintenta, no es un rechazo). Sin tablas nuevas (las políticas de
seguridad por filas de 0002 y 0006 siguen cubriendo las tablas). Al final, el módulo «Importar por claves o reporte del
SRI» en instalaciones existentes (core/security/menu.py), como en 0003 y 0004. La vuelta quita las columnas y el módulo
(la versión anterior no sirve su URL); sus permisos son los de la importación de siempre y se quedan.
"""
import django.db.models.deletion
from django.db import migrations, models


def menu(apps, schema_editor):
    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    Module = apps.get_model("security", "Module")
    if not Module.objects.exists():
        return
    organizar_menu(apps.get_model("security", "ModuleType"), Module, apps.get_model("auth", "Permission"), apps=apps)
    sync_roles(apps.get_model("auth", "Group"), Module, apps.get_model("security", "GroupModule"))


def quitar_menu(apps, schema_editor):
    apps.get_model("security", "Module").objects.filter(url="/importacion/claves/").delete()   # sus GroupModule caen en cascada


class Migration(migrations.Migration):

    dependencies = [
        ("importacion", "0006_seguridad_por_filas_equivalencia"),
    ]

    operations = [
        migrations.AddField(
            model_name="loteimportacion",
            name="origen",
            field=models.CharField(choices=[("archivos", "Archivos XML / RIDE"), ("claves", "Lista de claves de acceso"),
                                            ("reporte", "Reporte del portal del SRI")],
                                   default="archivos", max_length=10, verbose_name="Origen del lote"),
        ),
        migrations.AddField(
            model_name="loteimportacion",
            name="reporte",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                    to="importacion.archivoimportado", verbose_name="Reporte del SRI del que salieron las claves"),
        ),
        migrations.AlterField(
            model_name="loteimportacion",
            name="total_archivos",
            field=models.PositiveIntegerField(default=0, verbose_name="Entradas (archivos o claves)"),
        ),
        migrations.AlterField(
            model_name="archivoimportado",
            name="tipo",
            field=models.CharField(choices=[("xml", "XML"), ("pdf", "PDF"), ("reporte", "Reporte del portal del SRI (TXT, CSV o XLSX)")],
                                   max_length=10, verbose_name="Tipo"),
        ),
        migrations.AlterField(
            model_name="documentoimportado",
            name="origen",
            field=models.CharField(choices=[("xml", "Archivo XML"), ("pdf", "RIDE en PDF"), ("sri", "Consulta al SRI"),
                                            ("manual", "Clave escrita a mano"), ("lista", "Lista de claves de acceso"),
                                            ("reporte", "Reporte del portal del SRI")],
                                   max_length=10, verbose_name="Origen"),
        ),
        migrations.AlterField(
            model_name="documentoimportado",
            name="estado_verificacion",
            field=models.CharField(choices=[("sin_autorizacion", "El archivo no trae autorización"),
                                            ("declarada_en_archivo", "Autorización declarada en el archivo (sin verificar)"),
                                            ("verificada_sri", "Verificada en el SRI"), ("discrepancia_sri", "Difiere de lo autorizado en el SRI"),
                                            ("no_autorizada_sri", "El SRI no la autoriza"), ("no_encontrada_sri", "El SRI no tiene esa clave"),
                                            ("sri_no_disponible", "El SRI no respondió"), ("en_proceso_sri", "El SRI todavía la está procesando")],
                                   default="sin_autorizacion", max_length=25, verbose_name="Verificación"),
        ),
        migrations.AddField(
            model_name="entradalote",
            name="clave",
            field=models.CharField(blank=True, default="", max_length=49, verbose_name="Clave de acceso"),
        ),
        migrations.AddField(
            model_name="entradalote",
            name="sugerencias",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(menu, quitar_menu),
    ]
