"""Tarea programada de respaldo: avanza los lotes con archivos en cola (RIDE en PDF) y reintenta recuperar del SRI el XML
de los documentos que quedaron pendientes porque el SRI no respondió o aún los estaba procesando. No reintenta sola las claves
que el SRI no admite consultar por su fecha (fuera de rango) ni las claves no válidas: no cambiarían. El navegador también avanza
los lotes (POST /importacion/api/lotes/<id>/procesar/); esta tarea cubre lo que quedó a medias. No emite ni toca numeraciones.

Antes completa lo que verificó la versión anterior después de importacion 0009 (servicios.completar_consultas_de_la_version_anterior)."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.importacion import servicios as sv
from core.importacion.models import DocumentoImportado, LoteImportacion
from core.tenancy.context import company_context, platform_scope


class Command(BaseCommand):
    help = 'Procesa los lotes de importación en cola y reintenta los XML que el SRI no entregó.'

    def add_arguments(self, parser):
        parser.add_argument('--maximo', type=int, default=20, help='Entradas por lote en esta ejecución.')

    def handle(self, *args, **opciones):
        hace_un_rato = timezone.now() - timedelta(minutes=10)
        with platform_scope():
            completados = sv.completar_consultas_de_la_version_anterior()
            lotes = list(LoteImportacion.all_companies.select_related('company', 'usuario').filter(estado='procesando')[:50])
            pendientes = list(DocumentoImportado.all_companies.select_related('company', 'importado_por').filter(
                estado_procesamiento='pendiente_xml', estado_verificacion__in=sv.REINTENTABLES_AUTOMATICOS,
                verificado_en__lt=hace_un_rato).exclude(ultima_consulta_resultado__in=sv.SIN_REINTENTO_AUTOMATICO)[:50])
        for lote in lotes:
            with company_context(lote.company):
                sv.procesar_lote(lote, lote.usuario, maximo=opciones['maximo'], presupuesto=None)   # sin corte de gunicorn
        for documento in pendientes:
            with company_context(documento.company):
                sv.recuperar_xml(documento, documento.importado_por)
        resumen = f'lotes: {len(lotes)} · reintentos de XML: {len(pendientes)}'
        if completados:
            resumen += f' · completados de la versión anterior: {completados}'
        self.stdout.write(resumen)
