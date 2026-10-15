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
from django.views.generic import TemplateView, View

from core.importacion import limites, servicios as sv
from core.importacion.models import ArchivoImportado, DocumentoImportado, EntradaLote, LoteImportacion, ReglaImportacion
from core.importacion.xml_sri import _serializable
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

VER, IMPORTAR, REVISAR = 'view_documentoimportado', 'add_documentoimportado', 'change_documentoimportado'
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
        comprobante = (d.datos or {}).get('comprobante') or {}
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
            'acciones': acciones_posibles(d),
        })
    return _serializable(item)


def acciones_posibles(d):
    if d.estado_procesamiento != 'procesado':
        return ['verificar', 'descartar']
    acciones = ['verificar']
    if d.estado_revision == 'pendiente':
        if d.clasificacion in ('emitido', 'recibido'):
            acciones += ['aprobar', 'vincular_compra' if d.clasificacion == 'recibido' else 'vincular_venta']
        if d.clasificacion in ('revision_manual', 'pendiente'):
            acciones.append('clasificar')
        if d.clasificacion == 'recibido' and not d.proveedor_id:
            acciones.append('crear_proveedor')
        acciones.append('descartar')
    else:
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
