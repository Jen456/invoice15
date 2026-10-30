"""Compras con datos incompletos: informe y, con decisión escrita, completación desde el XML vinculado (§3.9).

    python manage.py compras_incompletas [--empresa ID | --todas] [--desde-xml] [--csv RUTA]
    python manage.py compras_incompletas --empresa ID --desde-xml --aplicar --decision "motivo y quién autorizó" --csv RUTA

Ensayo por defecto (no escribe nada). Con --desde-xml, para cada compra incompleta con un documento importado vinculado,
recibido, verificado en el SRI y del mismo proveedor, propone la cabecera y los importes del XML y muestra la diferencia
con el subtotal registrado. Con --aplicar completa SOLO las que difieren ≤ 0,02, con compras.completar_datos
(origen='orden', auditoría purchase_complete con la decisión y el informe): llena solo los datos vacíos (un dato ya
registrado que difiere del XML se informa como conflicto) y nunca cambia líneas, stock ni cuentas por pagar. No se
ejecuta en producción en esta fase.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from core.pos.management.commands import _ensayo

COLUMNAS = ['empresa', 'compra', 'proveedor', 'numero', 'subtotal', 'version_datos', 'faltantes', 'documento',
            'numero_xml', 'subtotal_xml', 'diferencia', 'propuesta', 'accion']
TOLERANCIA = Decimal('0.02')
CABECERA_XML = ('tipo_comprobante', 'estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision', 'forma_pago',
                'pago_loc_ext')


class Command(BaseCommand):
    help = 'Informe de compras con datos incompletos; con --desde-xml --aplicar (y --decision, --csv) las completa del XML.'

    def add_arguments(self, parser):
        _ensayo.agregar_opciones(parser)
        parser.add_argument('--desde-xml', action='store_true', dest='desde_xml',
                            help='Propone cabecera e importes desde el XML importado y vinculado a cada compra.')

    def handle(self, *args, **opciones):
        from core.pos.compras import faltantes
        from core.tenancy.context import company_context
        _ensayo.comprobar(opciones)
        if opciones['aplicar'] and not opciones['desde_xml']:
            raise CommandError('--aplicar exige --desde-xml: sin el XML no hay de dónde tomar los importes')
        lista = _ensayo.empresas(opciones)
        informe = _ensayo.Informe(opciones['csv'], COLUMNAS)
        resumen = {'incompletas': 0, 'con_xml': 0, 'completadas': 0}
        try:
            for empresa in lista:
                with company_context(empresa):
                    cuenta = self._empresa(empresa, opciones, informe, resumen, faltantes)
                self.stdout.write(f'Empresa {empresa.pk} ({empresa.business_name}): {cuenta} compras con datos incompletos.')
        finally:
            informe.cerrar()
        modo = (f'aplicado: {resumen["completadas"]} compras actualizadas desde el XML' if opciones['aplicar']
                else 'ensayo: no se cambió nada')
        self.stdout.write(f'Total: {resumen["incompletas"]} compras incompletas, {resumen["con_xml"]} con XML vinculado ({modo}).')

    def _empresa(self, empresa, opciones, informe, resumen, faltantes):
        from core.pos.models import Purchase
        compras = list(Purchase.objects.filter(datos_incompletos=True).select_related('provider').order_by('pk'))
        for compra in compras:
            fila = {'empresa': empresa.pk, 'compra': compra.pk, 'proveedor': compra.provider.name,
                    'numero': compra.numero_comprobante, 'subtotal': f'{Decimal(compra.subtotal):.2f}',
                    'version_datos': compra.version_datos, 'faltantes': ', '.join(c for c, _ in faltantes(compra))}
            if opciones['desde_xml']:
                fila.update(self._desde_xml(compra, opciones, resumen))
            informe.agregar(fila)
        resumen['incompletas'] += len(compras)
        return len(compras)

    def _desde_xml(self, compra, opciones, resumen):
        from core.importacion.compras import DatoNoReconocido, cabecera_de_documento, importes_de_documento
        from core.importacion.models import DocumentoImportado
        from core.pos import compras as sv
        documento = (DocumentoImportado.objects.filter(compra=compra, estado_revision='vinculado', clasificacion='recibido',
                                                       estado_verificacion='verificada_sri', cod_doc__in=('01', '04', '05'))
                     .order_by('pk').first())
        if documento is None or (documento.proveedor_id != compra.provider_id and documento.emisor_ruc != compra.provider.ruc):
            return {'accion': 'sin XML vinculado y verificado'}
        resumen['con_xml'] += 1
        try:
            importes = importes_de_documento(documento)
        except DatoNoReconocido as e:
            return {'documento': documento.pk, 'numero_xml': documento.numero, 'accion': f'no se aplica: {e}'}
        diferencia = importes['subtotal'] - Decimal(compra.subtotal)
        cabecera = cabecera_de_documento(documento)
        datos, conflictos = {}, []
        for campo in CABECERA_XML:
            actual, del_xml = getattr(compra, campo), cabecera[campo]
            if del_xml in ('', None):
                continue
            if actual in ('', None):
                datos[campo] = del_xml
            elif actual != del_xml:
                conflictos.append(campo)
        if compra.version_datos == 1 and compra.total is None:
            datos.update({c: importes[c] for c in sv.IMPORTES_EDITABLES + ('total_irbpnr',)})
        fila = {'documento': documento.pk, 'numero_xml': documento.numero, 'subtotal_xml': f'{importes["subtotal"]:.2f}',
                'diferencia': f'{diferencia:.2f}', 'propuesta': ', '.join(sorted(datos))}
        if conflictos:
            fila['accion'] = 'conflicto: difiere del XML ' + ', '.join(conflictos)
        elif abs(diferencia) > TOLERANCIA:
            fila['accion'] = 'no se aplica: difiere más de 0,02'
        elif not datos:
            fila['accion'] = 'sin datos que completar desde el XML'
        elif not opciones['aplicar']:
            fila['accion'] = 'se completaría'
        else:
            datos.update(confirmar_iva=True, confirmar_plazo_ats=True)   # el XML autorizado manda (DC4)
            try:
                actualizada = sv.completar_datos(compra, None, datos, origen='orden', decision=opciones['decision'].strip(),
                                                 informe=str(opciones['csv']))
            except sv.ErrorCompra as e:
                fila['accion'] = f'error: {e}'
            else:
                resumen['completadas'] += 1
                fila['accion'] = ('completada' if not actualizada.datos_incompletos else
                                  'actualizada; sigue incompleta: ' + ', '.join(c for c, _ in sv.faltantes(actualizada)))
        return fila
