"""Importación de comprobantes: API JSON (contrato en HANDOFF) y páginas de los módulos del menú.

La empresa es siempre la activa de la sesión (request.company, validada por membresía); ningún parámetro del navegador
la cambia. Los objetos se buscan con el gestor de empresa: un id de otra empresa responde 404.
"""
import json
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from core.importacion import compras as desde_xml, limites, recibidos, servicios as sv
from core.importacion.forms import RetencionRecibidaDesdeDocumentoForm
from core.importacion.models import ArchivoImportado, DocumentoImportado, EntradaLote, LoteImportacion, ReglaImportacion
from core.importacion.xml_sri import _serializable
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

VER, IMPORTAR, REVISAR = 'view_documentoimportado', 'add_documentoimportado', 'change_documentoimportado'
CREAR_COMPRA = (REVISAR, 'add_purchase')
REGISTRAR_RETENCION = (REVISAR, 'add_retencionrecibida')      # permiso de Ventas (O2): «Retenciones recibidas»
TIPOS_IMPORTADOS = ('01', '04', '05', '07')
BANDEJAS = {
    'pendientes': Q(estado_revision='pendiente', estado_procesamiento='procesado') & ~Q(clasificacion='ajeno'),
    'recibidos': Q(clasificacion='recibido'),
    'emitidos': Q(clasificacion='emitido'),
    'ajenos': Q(clasificacion='ajeno'),
    'sin_xml': Q(estado_procesamiento='pendiente_xml'),
    'todos': Q(),
}
CAMPOS_REGLA = ('verificar_con_sri', 'exigir_verificacion', 'naturaleza_compra', 'tratamiento_iva', 'cuenta_gasto', 'cuenta_inventario',
                'cuenta_activo_fijo', 'cuenta_iva_compras', 'cuenta_proveedores', 'cuenta_retencion_renta', 'cuenta_retencion_iva',
                'cuenta_ventas', 'cuenta_iva_ventas', 'cuenta_clientes')


def tiene_permiso(request, codigo):
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename=codigo).exists()


def datos_peticion(request):
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body or b'{}')
        except ValueError:
            return {}
    return request.POST.dict()


def error(mensaje, estado=400, **extra):
    return JsonResponse({'error': mensaje, **extra}, status=estado)


# ------------------------------------------------------------------ serialización

def archivo_dict(archivo):
    if archivo is None:
        return None
    return {'id': archivo.pk, 'tipo': archivo.tipo, 'origen': archivo.origen, 'tamano': archivo.tamano, 'sha256': archivo.sha256,
            'nombre': archivo.nombre_original, 'descarga': reverse('importacion_descargar', args=[archivo.pk])}


def documento_dict(d, detalle=False):
    item = {
        'id': d.pk, 'clave_acceso': d.clave_acceso, 'cod_doc': d.cod_doc, 'tipo_documento': d.get_cod_doc_display(), 'version': d.version,
        'ambiente': d.ambiente, 'numero': d.numero, 'fecha_emision': d.fecha_emision, 'numero_autorizacion': d.numero_autorizacion,
        'fecha_autorizacion': d.fecha_autorizacion, 'origen': {'id': d.origen, 'nombre': d.get_origen_display()},
        'emisor': {'ruc': d.emisor_ruc, 'razon_social': d.emisor_razon_social, 'nombre_comercial': d.emisor_nombre_comercial},
        'receptor': {'tipo_identificacion': d.receptor_tipo_identificacion, 'identificacion': d.receptor_identificacion,
                     'razon_social': d.receptor_razon_social},
        'moneda': d.moneda,
        'importes': {'total_sin_impuestos': d.total_sin_impuestos, 'total_descuento': d.total_descuento, 'propina': d.propina,
                     'total_iva': d.total_iva, 'total_ice': d.total_ice, 'total_irbpnr': d.total_irbpnr, 'importe_total': d.importe_total},
        'estados': {
            'procesamiento': {'id': d.estado_procesamiento, 'nombre': d.get_estado_procesamiento_display()},
            'verificacion': {'id': d.estado_verificacion, 'nombre': d.get_estado_verificacion_display(), 'en': d.verificado_en},
            'clasificacion': {'id': d.clasificacion, 'nombre': d.get_clasificacion_display()},
            'revision': {'id': d.estado_revision, 'nombre': d.get_estado_revision_display()},
            'contable': {'id': d.estado_contable, 'nombre': d.get_estado_contable_display()},
        },
        'proveedor': {'id': d.proveedor_id, 'nombre': d.proveedor.name} if d.proveedor_id else None,
        'cliente': {'id': d.cliente_id, 'nombre': d.cliente.user.names} if d.cliente_id else None,
        'compra_id': d.compra_id, 'venta_id': d.venta_id, 'advertencias': d.advertencias, 'creado': d.creado,
    }
    if detalle:
        comprobante = desde_xml.comprobante_completo(d) if d.estado_procesamiento == 'procesado' else {}
        acciones = acciones_posibles(d)
        item.update({
            'impuestos': [{'codigo': i.codigo, 'codigo_porcentaje': i.codigo_porcentaje, 'impuesto': i.impuesto, 'categoria': i.categoria,
                           'tarifa': i.tarifa, 'base_imponible': i.base_imponible, 'valor': i.valor,
                           'descuento_adicional': i.descuento_adicional, 'valor_devolucion_iva': i.valor_devolucion_iva}
                          for i in d.impuestos.all()],
            'bases_por_tarifa': comprobante.get('bases_por_tarifa', []), 'pagos': comprobante.get('pagos', []),
            'lineas': comprobante.get('lineas', 0), 'info_adicional': comprobante.get('info_adicional', {}),
            'archivos': {'xml': archivo_dict(d.archivo_xml), 'pdf': archivo_dict(d.archivo_pdf)},
            'candidatos': sv.candidatos_conciliacion(d) if d.estado_procesamiento == 'procesado' else [],
            'retenciones': [{'id': r.pk, 'numero': r.voucher_number_full, 'estado': r.get_status_display(),
                             'total_retenido': r.total_retenido} for r in sv.retenciones_relacionadas(d)],
            'propuesta_contable': d.propuesta_contable, 'nota_revision': d.nota_revision,
            'eventos': [{'tipo': e.tipo, 'mensaje': e.mensaje, 'creado': e.creado,
                         'usuario': e.usuario.username if e.usuario_id else None} for e in d.eventos.select_related('usuario')],
            'acciones': acciones,
            'detalles': comprobante.get('detalles') or [], 'doc_modificado': comprobante.get('doc_modificado'),
            'motivos': comprobante.get('motivos') or [], 'retencion': comprobante.get('retencion'),
            'aviso_contable': sv.AVISO_RETENCION if d.cod_doc == '07' else '',
            'motivo_sin_reabrir': sv.motivo_sin_reabrir(d) if d.estado_revision != 'pendiente' else '',
            'urls': {'compra': reverse('importacion_compra', args=[d.pk]) if 'crear_compra' in acciones else None,
                     'retencion_recibida': (reverse('importacion_retencion_recibida', args=[d.pk])
                                            if d.cod_doc == '07' and d.clasificacion == 'recibido'
                                            and d.estado_procesamiento == 'procesado' else None),
                     'retenciones_recibidas': recibidos.URL_RETENCIONES_RECIBIDAS if d.cod_doc == '07' else None},
        })
    return _serializable(item)


def acciones_posibles(d):
    """Acciones que hoy admite el servidor (espec-etapa2-compras §3.8): recibidos 01/04/05 pendientes → aprobar, vincular
    o crear la compra; 07 recibido → aprobar y registrar la retención recibida (sin compra); emitidos 04/05/07 → solo
    aprobar. Un documento cuya compra salió de él, o un 07 ya registrado, no se reabre aquí."""
    if d.estado_procesamiento != 'procesado':
        return ['verificar', 'descartar']
    acciones = ['verificar']
    if d.cod_doc == '07' and d.clasificacion == 'recibido':
        if d.estado_revision == 'pendiente':
            acciones += ['aprobar', 'registrar_retencion', 'descartar']
        elif d.estado_revision == 'aprobado':
            acciones += ['registrar_retencion', 'reabrir']
        elif d.estado_revision == 'descartado':
            acciones.append('reabrir')
        return acciones
    if d.estado_revision == 'pendiente':
        if d.clasificacion == 'recibido':
            acciones += ['aprobar', 'vincular_compra']
            if d.cod_doc in desde_xml.CODIGOS_DE_COMPRA and not d.compra_id:
                acciones.append('crear_compra')
        elif d.clasificacion == 'emitido':
            acciones += ['aprobar', 'vincular_venta'] if d.cod_doc == '01' else ['aprobar']
        if d.clasificacion in ('revision_manual', 'pendiente'):
            acciones.append('clasificar')
        if d.clasificacion == 'recibido' and not d.proveedor_id:
            acciones.append('crear_proveedor')
        acciones.append('descartar')
    elif not sv.motivo_sin_reabrir(d):
        acciones.append('reabrir')
    return acciones


def entrada_dict(e):
    return _serializable({'id': e.pk, 'nombre': e.nombre, 'tamano': e.tamano, 'tipo': e.tipo, 'orden': e.orden,
                          'estado': {'id': e.estado, 'nombre': e.get_estado_display()}, 'errores': e.errores, 'advertencias': e.advertencias,
                          'candidatas': e.candidatas, 'documento_id': e.documento_id, 'procesado_en': e.procesado_en,
                          'sha256': e.archivo.sha256 if e.archivo_id else None})


def lote_dict(lote, entradas=False):
    conteo = dict(lote.entradas.values_list('estado').annotate(n=Count('id')))
    item = {'id': lote.pk, 'estado': {'id': lote.estado, 'nombre': lote.get_estado_display()}, 'total_archivos': lote.total_archivos,
            'pendientes': conteo.get('en_cola', 0) + conteo.get('procesando', 0), 'por_estado': conteo,
            'creado': lote.creado, 'terminado': lote.terminado, 'usuario': lote.usuario.username,
            'progreso': round(100 * (lote.total_archivos - conteo.get('en_cola', 0) - conteo.get('procesando', 0)) / max(lote.total_archivos, 1))}
    if entradas:
        item['entradas'] = [entrada_dict(e) for e in lote.entradas.select_related('archivo')]
    return _serializable(item)


# ------------------------------------------------------------------ API JSON

class ApiMixin(GroupPermissionMixin):
    """La API responde siempre JSON: sin permiso, 403 (también en GET, donde las pantallas redirigen)."""

    def deny(self, request):
        return JsonResponse({'error': 'Tu perfil no cuenta con el permiso necesario.'}, status=403)


class LotesApi(ApiMixin, View):
    permission_required = VER

    def get(self, request):
        pagina = Paginator(LoteImportacion.objects.select_related('usuario').order_by('-id'), 25).get_page(request.GET.get('pagina'))
        return JsonResponse({'lotes': [lote_dict(l) for l in pagina], 'pagina': pagina.number, 'paginas': pagina.paginator.num_pages})

    def post(self, request):
        if not tiene_permiso(request, IMPORTAR):
            return error('Tu perfil no puede importar documentos.', 403)
        archivos = request.FILES.getlist('archivos')
        if sum(a.size for a in archivos) > limites.MAX_BYTES_POR_PETICION:
            return error(f'Sube como máximo {limites.MAX_BYTES_POR_PETICION // limites.MB} MB por vez.', 413)
        try:
            lote = sv.crear_lote(request.company, request.user, [(a.name, a.read()) for a in archivos])
        except sv.ErrorImportacion as e:
            return error(str(e))
        return JsonResponse({'lote': lote_dict(lote, entradas=True)}, status=201)


class LoteApi(ApiMixin, View):
    permission_required = VER

    def get(self, request, pk):
        return JsonResponse({'lote': lote_dict(get_object_or_404(LoteImportacion, pk=pk), entradas=True)})


class ArchivosLoteApi(ApiMixin, View):
    """Agrega archivos a un lote existente (subida por partes: nginx limita cada petición a 10 MB)."""
    permission_required = IMPORTAR

    def post(self, request, pk):
        lote = get_object_or_404(LoteImportacion, pk=pk)
        try:
            lote = sv.agregar_archivos(lote, request.user, [(a.name, a.read()) for a in request.FILES.getlist('archivos')])
        except sv.ErrorImportacion as e:
            return error(str(e))
        return JsonResponse({'lote': lote_dict(lote, entradas=True)}, status=201)


class ProcesarLoteApi(ApiMixin, View):
    permission_required = IMPORTAR

    def post(self, request, pk):
        lote = sv.procesar_lote(get_object_or_404(LoteImportacion, pk=pk), request.user)
        return JsonResponse({'lote': lote_dict(lote, entradas=True)})


class ClaveEntradaApi(ApiMixin, View):
    permission_required = IMPORTAR

    def post(self, request, pk):
        entrada = get_object_or_404(EntradaLote, pk=pk)
        if entrada.estado not in ('pendiente_clave', 'pendiente_xml'):
            return error('Este archivo no espera una clave.')
        try:
            entrada = sv.usar_clave_manual(entrada, request.user, datos_peticion(request).get('clave', ''))
        except sv.ErrorImportacion as e:
            return error(str(e))
        return JsonResponse({'entrada': entrada_dict(entrada)})


class DocumentosApi(ApiMixin, View):
    permission_required = VER

    def get(self, request):
        bandeja = request.GET.get('bandeja', 'pendientes')
        if bandeja not in BANDEJAS:
            return error('Bandeja no válida.')
        consulta = DocumentoImportado.objects.select_related('proveedor', 'cliente__user').filter(BANDEJAS[bandeja])
        cod_doc = (request.GET.get('cod_doc') or '').strip()
        if cod_doc:
            if cod_doc not in TIPOS_IMPORTADOS:
                return error('Tipo de comprobante no válido.')
            consulta = consulta.filter(cod_doc=cod_doc)
        texto = (request.GET.get('q') or '').strip()
        if texto:
            consulta = consulta.filter(Q(numero__icontains=texto) | Q(emisor_razon_social__icontains=texto) | Q(emisor_ruc=texto) |
                                       Q(receptor_identificacion=texto) | Q(clave_acceso=texto))
        pagina = Paginator(consulta.order_by('-id'), 50).get_page(request.GET.get('pagina'))
        return JsonResponse({'bandeja': bandeja, 'documentos': [documento_dict(d) for d in pagina], 'total': pagina.paginator.count,
                             'pagina': pagina.number, 'paginas': pagina.paginator.num_pages})


class DocumentoApi(ApiMixin, View):
    permission_required = VER

    def get(self, request, pk):
        return JsonResponse({'documento': documento_dict(get_object_or_404(DocumentoImportado, pk=pk), detalle=True)})


class VerificarDocumentoApi(ApiMixin, View):
    permission_required = REVISAR

    def post(self, request, pk):
        documento = sv.verificar_en_sri(get_object_or_404(DocumentoImportado, pk=pk), request.user)
        return JsonResponse({'documento': documento_dict(documento, detalle=True)})


class RevisarDocumentoApi(ApiMixin, View):
    permission_required = REVISAR

    def post(self, request, pk):
        datos = datos_peticion(request)
        try:
            documento = sv.revisar(get_object_or_404(DocumentoImportado, pk=pk), request.user, datos.get('accion'), datos)
        except sv.ErrorImportacion as e:
            return error(str(e))
        return JsonResponse({'documento': documento_dict(documento, detalle=True)})


class ReglasApi(ApiMixin, View):
    permission_required = 'view_reglaimportacion'

    def get(self, request):
        regla = sv.reglas_de(request.company)
        return JsonResponse({'reglas': {c: getattr(regla, c) for c in CAMPOS_REGLA}, 'puede_editar': tiene_permiso(request, 'change_reglaimportacion'),
                             'opciones': {'naturaleza_compra': ReglaImportacion.NATURALEZAS, 'tratamiento_iva': ReglaImportacion.TRATAMIENTOS_IVA}})

    def post(self, request):
        if not tiene_permiso(request, 'change_reglaimportacion'):
            return error('Tu perfil no puede cambiar las reglas.', 403)
        try:
            regla = guardar_reglas(request, datos_peticion(request))
        except ValueError as e:
            return error(str(e))
        return JsonResponse({'reglas': {c: getattr(regla, c) for c in CAMPOS_REGLA}})


def guardar_reglas(request, datos, formulario=False):
    """En un formulario HTML una casilla sin marcar no viaja (= False); en la API solo cambia lo que se envía."""
    regla = sv.reglas_de(request.company)
    for campo in CAMPOS_REGLA:
        if campo in ('verificar_con_sri', 'exigir_verificacion'):
            if formulario or campo in datos:
                setattr(regla, campo, str(datos.get(campo, '')).lower() in ('1', 'true', 'on', 'si', 'sí'))
        elif campo in datos:
            valor = str(datos[campo]).strip()[:30]
            opciones = {'naturaleza_compra': ReglaImportacion.NATURALEZAS, 'tratamiento_iva': ReglaImportacion.TRATAMIENTOS_IVA}.get(campo)
            if opciones and valor not in dict(opciones):
                raise ValueError(f'Valor no válido para {campo}.')
            setattr(regla, campo, valor)
    regla.actualizado_por = request.user
    regla.save()
    return regla


class DescargarArchivo(GroupPermissionMixin, View):
    """Único acceso a los XML y PDF importados (carpeta privada): empresa activa y permiso del módulo."""
    permission_required = VER

    def get(self, request, pk):
        archivo = get_object_or_404(ArchivoImportado, pk=pk)
        tipo = 'application/xml' if archivo.tipo == 'xml' else 'application/pdf'
        respuesta = FileResponse(archivo.archivo.open('rb'), content_type=tipo, as_attachment=True,
                                 filename=f'{archivo.sha256[:16]}.{archivo.tipo}')
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return respuesta


# ------------------------------------------------------------------ páginas de los módulos (diseño: Codex)

class Pagina(GroupPermissionMixin, TemplateView):
    titulo = ''
    bandeja = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': self.titulo, 'limites': limites, 'puede_importar': tiene_permiso(self.request, IMPORTAR),
                        'puede_revisar': tiene_permiso(self.request, REVISAR), 'bandeja': self.bandeja})
        if self.bandeja:
            context['documentos'] = (DocumentoImportado.objects.select_related('proveedor').filter(BANDEJAS[self.bandeja])
                                     .order_by('-id')[:200])
        return context


class NuevaImportacion(Pagina):
    template_name = 'importacion/nueva.html'
    permission_required = IMPORTAR
    titulo = 'Nueva importación XML / RIDE'

    def post(self, request):
        archivos = request.FILES.getlist('archivos')
        try:
            lote = sv.crear_lote(request.company, request.user, [(a.name, a.read()) for a in archivos])
        except sv.ErrorImportacion as e:
            messages.error(request, str(e))
            return HttpResponseRedirect(reverse('importacion_nueva'))
        return HttpResponseRedirect(reverse('importacion_lote', args=[lote.pk]))


class Lotes(Pagina):
    template_name = 'importacion/lotes.html'
    permission_required = VER
    titulo = 'Lotes e historial de importación'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['lotes'] = [lote_dict(l) for l in LoteImportacion.objects.select_related('usuario').order_by('-id')[:100]]
        return context


class Lote(Pagina):
    template_name = 'importacion/lote.html'
    permission_required = VER
    titulo = 'Lote de importación'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lote = get_object_or_404(LoteImportacion, pk=self.kwargs['pk'])
        context.update({'lote': lote, 'resumen': lote_dict(lote, entradas=True)})
        return context

    def post(self, request, pk):
        lote = get_object_or_404(LoteImportacion, pk=pk)
        if not tiene_permiso(request, IMPORTAR):
            messages.error(request, 'Tu perfil no puede importar documentos.')
        elif request.POST.get('action') == 'clave':
            entrada = get_object_or_404(EntradaLote, pk=request.POST.get('entrada'), lote=lote)
            try:
                sv.usar_clave_manual(entrada, request.user, request.POST.get('clave', ''))
            except sv.ErrorImportacion as e:
                messages.error(request, str(e))
        else:
            sv.procesar_lote(lote, request.user)
        return HttpResponseRedirect(reverse('importacion_lote', args=[pk]))


class Pendientes(Pagina):
    template_name = 'importacion/bandeja.html'
    permission_required = VER
    titulo = 'Documentos pendientes de revisión'
    bandeja = 'pendientes'


class Recibidos(Pagina):
    template_name = 'importacion/bandeja.html'
    permission_required = VER
    titulo = 'Documentos recibidos'
    bandeja = 'recibidos'


class Documento(Pagina):
    template_name = 'importacion/documento.html'
    permission_required = VER
    titulo = 'Documento importado'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        documento = get_object_or_404(DocumentoImportado, pk=self.kwargs['pk'])
        context.update({'documento': documento, 'detalle': documento_dict(documento, detalle=True)})
        return context

    def post(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        if not tiene_permiso(request, REVISAR):
            messages.error(request, 'Tu perfil no puede revisar documentos.')
            return HttpResponseRedirect(reverse('importacion_documento', args=[pk]))
        datos = request.POST.dict()
        try:
            if datos.get('accion') == 'verificar':
                sv.verificar_en_sri(documento, request.user)
            else:
                sv.revisar(documento, request.user, datos.get('accion'), datos)
            messages.success(request, 'Listo.')
        except sv.ErrorImportacion as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse('importacion_documento', args=[pk]))


class Reglas(Pagina):
    template_name = 'importacion/reglas.html'
    permission_required = 'view_reglaimportacion'
    titulo = 'Reglas de importación y contabilización'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'regla': sv.reglas_de(self.request.company), 'puede_editar': tiene_permiso(self.request, 'change_reglaimportacion'),
                        'naturalezas': ReglaImportacion.NATURALEZAS, 'tratamientos': ReglaImportacion.TRATAMIENTOS_IVA})
        return context

    def post(self, request):
        if not tiene_permiso(request, 'change_reglaimportacion'):
            messages.error(request, 'Tu perfil no puede cambiar las reglas.')
        else:
            try:
                guardar_reglas(request, request.POST.dict(), formulario=True)
                messages.success(request, 'Reglas guardadas.')
            except ValueError as e:
                messages.error(request, str(e))
        return HttpResponseRedirect(reverse('importacion_reglas'))


# ------------------------------------------------------------------ crear la compra desde el XML (§3.6, §6.G)

def opciones_compra():
    from core.pos.catalogos_sri import FORMAS_PAGO, SUSTENTOS
    from core.pos.models import TypeExpense
    return {'sustentos': [list(s) for s in SUSTENTOS], 'formas_pago': [list(f) for f in FORMAS_PAGO],
            'tipos_gasto': [{'id': t.pk, 'nombre': t.name, 'cod_sustento': t.cod_sustento} for t in TypeExpense.objects.order_by('name')]}


def compra_creada_dict(compra):
    return {'id': compra.pk, 'numero': compra.numero_comprobante, 'url': reverse('purchase_list')}


class CompraDesdeDocumentoApi(ApiMixin, View):
    """GET: propuesta para crear la compra (sin guardar). POST (JSON): crea la compra con las elecciones del usuario."""
    permission_required = CREAR_COMPRA

    def get(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        propuesta = desde_xml.propuesta_compra(documento)
        return JsonResponse({'documento': documento_dict(documento, detalle=True), 'puede_crear': not propuesta['bloqueos'],
                             'propuesta': propuesta, 'opciones': opciones_compra()})

    def post(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        datos = datos_peticion(request)
        if not isinstance(datos, dict):
            return error('Los datos no tienen un formato válido.')
        try:
            compra = desde_xml.crear_compra_desde_documento(documento, request.user, datos)
        except sv.ErrorImportacion as e:
            return error(str(e), codigo=e.codigo) if e.codigo else error(str(e))
        return JsonResponse({'compra': compra_creada_dict(compra), 'documento': documento_dict(compra.documento, detalle=True)},
                            status=201)


class CompraDesdeDocumento(Pagina):
    """Página de servidor (§6.G): cabecera, una elección por línea del XML (formset «lineas») y el botón «crear»."""
    template_name = 'importacion/compra.html'
    permission_required = CREAR_COMPRA
    titulo = 'Crear compra desde el XML'

    def formularios(self, documento, propuesta, datos=None):
        from core.pos.forms import CompraDesdeDocumentoForm, LineasCompraFormSet
        from core.pos.models import Product, TypeExpense
        tipos_gasto = list(TypeExpense.objects.order_by('name'))
        productos = list(Product.objects.order_by('name')) if not propuesta['agrupar_obligatorio'] else []
        iniciales = {'date_joined': timezone.localdate(), 'payment_type': propuesta['payment_type_sugerido'],
                     'end_credit': propuesta['end_credit_sugerido'] or '', 'forma_pago': propuesta['forma_pago_del_xml'] or '',
                     'parte_relacionada': ('' if propuesta['parte_relacionada'] is None
                                           else 'si' if propuesta['parte_relacionada'] else 'no'),
                     'agrupar_por_tarifa': propuesta['agrupar_obligatorio']}
        form = CompraDesdeDocumentoForm(datos, initial=iniciales, tipos_gasto=tipos_gasto)
        lineas_iniciales = [] if propuesta['agrupar_obligatorio'] else [
            {'indice': l['indice'], 'modo': l['modo_sugerido'],
             'product': str(l['producto_sugerido']['id']) if l['producto_sugerido'] and l['origen_sugerencia'] == 'equivalencia' else ''}
            for l in propuesta['lineas']]
        lineas = LineasCompraFormSet(datos, prefix='lineas', initial=lineas_iniciales,
                                     form_kwargs={'productos': productos, 'tipos_gasto': tipos_gasto})
        return form, lineas

    def contexto(self, documento, propuesta, form, lineas):
        filas = list(zip(propuesta['lineas'], lineas.forms)) if not propuesta['agrupar_obligatorio'] else []
        return self.get_context_data(documento=documento_dict(documento, detalle=True), propuesta=propuesta, form=form,
                                     lineas=lineas, filas=filas, puede_crear=not propuesta['bloqueos'],
                                     url_documento=reverse('importacion_documento', args=[documento.pk]))

    def get(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        propuesta = desde_xml.propuesta_compra(documento)
        return self.render_to_response(self.contexto(documento, propuesta, *self.formularios(documento, propuesta)))

    def post(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        propuesta = desde_xml.propuesta_compra(documento)
        form, lineas = self.formularios(documento, propuesta, request.POST)
        if request.POST.get('action') == 'crear' and form.is_valid() and (propuesta['agrupar_obligatorio'] or lineas.is_valid()):
            datos = form.datos()
            if not propuesta['agrupar_obligatorio']:
                datos['lineas'] = [f.eleccion() for f in lineas.forms]
            if documento.proveedor_id or desde_xml.proveedor_del_documento(documento):
                datos.pop('proveedor_nuevo')
            try:
                compra = desde_xml.crear_compra_desde_documento(documento, request.user, datos)
            except sv.ErrorImportacion as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f'Compra #{compra.pk} creada desde el XML')
                return HttpResponseRedirect(reverse('purchase_list'))
        elif request.POST.get('action') != 'crear':
            form.add_error(None, 'Acción no válida.')
        return self.render_to_response(self.contexto(documento, propuesta, form, lineas))


# ------------------------------------------------------------------ registrar la retención recibida desde un 07 (§6.J)

def leida_dict(leida):
    return _serializable({
        'numero': leida.numero, 'fecha_emision': leida.fecha_emision, 'periodo_fiscal': leida.periodo_fiscal,
        'agente_ruc': leida.agente_ruc, 'agente_razon_social': leida.agente_razon_social, 'version': leida.version,
        'ambiente': leida.ambiente, 'total_retenido': f'{leida.total_retenido:.2f}', 'verificado_sri': leida.verificado_sri,
        'sustentos': [{'numero_con_guiones': s.numero_con_guiones, 'cod_doc_sustento': s.cod_doc_sustento,
                       'fecha_emision_doc_sustento': s.fecha_emision_doc_sustento, 'num_aut_doc_sustento': s.num_aut_doc_sustento,
                       'cod_sustento': s.cod_sustento,
                       'retenciones': [{'impuesto': r.impuesto, 'codigo_retencion': r.codigo_retencion,
                                        'base_imponible': f'{r.base_imponible:.2f}', 'porcentaje': f'{r.porcentaje:.2f}',
                                        'valor_retenido': f'{r.valor_retenido:.2f}'} for r in s.retenciones]}
                      for s in leida.sustentos]})


class RetencionRecibidaDesdeDocumento(Pagina):
    """Página de servidor (§6.J): resumen del 07 leído y «registrar» con el servicio de Ventas (todo o nada)."""
    template_name = 'importacion/retencion_recibida.html'
    permission_required = REGISTRAR_RETENCION
    titulo = 'Registrar retención recibida'

    def contexto(self, documento, form):
        leida, error_lectura = None, ''
        try:
            leida = leida_dict(recibidos.retencion_recibida_de(documento))
        except sv.ErrorImportacion as e:
            error_lectura = str(e)
        bloqueos = recibidos.bloqueos_retencion(documento)
        return self.get_context_data(
            documento=documento_dict(documento, detalle=True), leida=leida, error_lectura=error_lectura, bloqueos=bloqueos,
            exige_confirmar_sin_verificar=recibidos.exige_confirmar_sin_verificar(documento), form=form,
            puede_registrar=leida is not None and not bloqueos,
            url_documento=reverse('importacion_documento', args=[documento.pk]),
            url_retenciones_recibidas=recibidos.URL_RETENCIONES_RECIBIDAS)

    def get(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        return self.render_to_response(self.contexto(documento, RetencionRecibidaDesdeDocumentoForm()))

    def post(self, request, pk):
        documento = get_object_or_404(DocumentoImportado, pk=pk)
        form = RetencionRecibidaDesdeDocumentoForm(request.POST)
        if request.POST.get('action') != 'registrar' or not form.is_valid():
            messages.error(request, 'Acción no válida.')
            return self.render_to_response(self.contexto(documento, form))
        try:
            registradas = recibidos.registrar_en_retenciones_recibidas(
                request.company, request.user, documento, confirmar_sin_verificar=form.cleaned_data['confirmar_sin_verificar'])
        except sv.ErrorImportacion as e:
            messages.error(request, str(e))
            documento.refresh_from_db()
            return self.render_to_response(self.contexto(documento, form))
        cantidad = len(registradas or [])
        messages.success(request, f'Retención recibida registrada ({cantidad} documentos sustento)')
        return HttpResponseRedirect(reverse('importacion_documento', args=[documento.pk]))
