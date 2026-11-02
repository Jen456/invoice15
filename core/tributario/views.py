"""Libros mensuales: página funcional (el diseño lo hace Codex), API JSON por libro y exportación a XLSX o CSV.
Permiso `view_libros` (Propietario, Administrador, Contador y Consulta) y plan pagado (regla de /tributario/)."""
from datetime import date, timedelta
from decimal import Decimal

from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.security.mixins import GroupPermissionMixin
from core.tributario import exportar, libros as lb
from core.tributario.models import ExportacionLibro

VER = 'view_libros'
MAX_FILAS_PANTALLA = 500


def mes_de(texto, hoy=None):
    """'AAAA-MM' → primer día del mes; vacío o inválido → el mes actual. Nunca un mes futuro."""
    hoy = hoy or timezone.localdate()
    try:
        anio, mes = (int(p) for p in (texto or '').strip().split('-'))
        inicio = date(anio, mes, 1)
    except (ValueError, TypeError):
        return hoy.replace(day=1), False
    if inicio > hoy.replace(day=1) or anio < 2000:
        return hoy.replace(day=1), False
    return inicio, True


def _json(valor):
    if isinstance(valor, Decimal):
        return f'{valor:.2f}'
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json(v) for v in valor]
    return valor


def libro_json(libro, totales, columnas, limite=None):
    filas = libro.filas if limite is None else libro.filas[:limite]
    return {'libro': libro.clave, 'nombre': libro.nombre, 'mes': f'{libro.mes:%Y-%m}',
            'columnas': [{'clave': c, 'encabezado': e, 'tipo': t} for c, e, t in columnas],
            'filas': [_json({**f, 'celdas': [{'clave': c, 'valor': lb.valor(f, c)} for c, _, _ in columnas]}) for f in filas],
            'total_filas': len(libro.filas), 'totales': _json(totales), 'excluidos': libro.excluidos,
            'advertencias': libro.advertencias}


EMPRESA_CAMBIADA = ('La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa '
                    'que tienes abierta ahora.')


def empresa_cambiada(request):
    """True si el enlace se armó para otra empresa (`empresa=<id>`) que ya no es la activa (otra pestaña la cambió)."""
    pedida = request.GET.get('empresa')
    return bool(pedida) and str(getattr(request, 'company', None) and request.company.pk) != pedida


class LibroApi(GroupPermissionMixin, View):
    """GET /tributario/api/libros/<libro>/?mes=AAAA-MM → el libro completo con columnas, filas, totales y exclusiones."""
    permission_required = VER

    def get(self, request, libro):
        if libro not in lb.LIBROS:
            return JsonResponse({'error': 'Libro desconocido.', 'codigo': 'libro'}, status=404)
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        inicio, _ = mes_de(request.GET.get('mes'))
        return JsonResponse(libro_json(*lb.construir(libro, inicio)))


class LibrosPagina(GroupPermissionMixin, TemplateView):
    template_name = 'tributario/libros.html'
    permission_required = VER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inicio, valido = mes_de(self.request.GET.get('mes'))
        clave = self.request.GET.get('libro') if self.request.GET.get('libro') in lb.LIBROS else 'ventas'
        todos = lb.resumen(inicio)
        libro, totales, columnas = todos[clave]
        anterior = (inicio - timedelta(days=1)).replace(day=1)
        siguiente = lb.siguiente_mes(inicio)
        context.update({
            'title': 'Libros mensuales', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}', 'mes_invalido': bool(self.request.GET.get('mes')) and not valido,
            'anterior': f'{anterior:%Y-%m}', 'siguiente': f'{siguiente:%Y-%m}' if siguiente <= timezone.localdate() else '',
            'libros': [{'clave': c, 'nombre': lb.LIBROS[c], 'totales': _json(t), 'filas': len(li.filas), 'excluidos': li.excluidos,
                        'advertencias': li.advertencias} for c, (li, t, _) in todos.items()],
            'actual': libro_json(libro, totales, columnas, MAX_FILAS_PANTALLA), 'clave': clave, 'max_filas': MAX_FILAS_PANTALLA,
            'exportaciones': ExportacionLibro.objects.select_related('generado_por').filter(mes=inicio)[:10],
        })
        return context


class ExportarLibro(GroupPermissionMixin, View):
    """GET ?mes=AAAA-MM&libro=<libro>|todos&formato=xlsx|csv → descarga (CSV solo de un libro). Queda registrada."""
    permission_required = VER

    def get(self, request):
        if empresa_cambiada(request):
            return HttpResponse(EMPRESA_CAMBIADA, status=409, content_type='text/plain; charset=utf-8')
        inicio, valido = mes_de(request.GET.get('mes'))
        if request.GET.get('mes') and not valido:
            raise Http404
        clave = request.GET.get('libro') or 'todos'
        formato = request.GET.get('formato') or 'xlsx'
        if (clave not in lb.LIBROS and clave != 'todos') or formato not in ('xlsx', 'csv') or (formato == 'csv' and clave == 'todos'):
            raise Http404
        claves = list(lb.LIBROS) if clave == 'todos' else [clave]
        construidos = [lb.construir(c, inicio) for c in claves]
        if formato == 'csv':
            contenido, tipo = exportar.a_csv(*construidos[0]), 'text/csv; charset=utf-8'
        else:
            contenido, tipo = exportar.a_xlsx(construidos), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ExportacionLibro.objects.create(libro=clave, mes=inicio, formato=formato, filas=sum(len(li.filas) for li, _, _ in construidos),
                                        totales={li.clave: _json(t) for li, t, _ in construidos}, sha256=exportar.huella(contenido),
                                        generado_por=request.user)
        respuesta = HttpResponse(contenido, content_type=tipo)
        nombre = (f'libros-{request.company.ruc}-{inicio:%Y-%m}' if clave == 'todos'
                  else f'libro-{clave.replace("_", "-")}-{request.company.ruc}-{inicio:%Y-%m}')
        respuesta['Content-Disposition'] = f'attachment; filename="{nombre}.{formato}"'
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        return respuesta


# ---------------------------------------------------------------- revisión del mes (entrega C)

class RevisionPagina(GroupPermissionMixin, TemplateView):
    """Observaciones del mes con su causa y enlace. No es un cierre ni bloquea nada (el diseño lo hace Codex)."""
    template_name = 'tributario/revision.html'
    permission_required = 'view_revision'

    def get_context_data(self, **kwargs):
        from core.tributario import revision
        context = super().get_context_data(**kwargs)
        inicio, valido = mes_de(self.request.GET.get('mes'))
        anterior = (inicio - timedelta(days=1)).replace(day=1)
        siguiente = lb.siguiente_mes(inicio)
        context.update({'title': 'Revisión del mes', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}',
                        'mes_invalido': bool(self.request.GET.get('mes')) and not valido, 'anterior': f'{anterior:%Y-%m}',
                        'siguiente': f'{siguiente:%Y-%m}' if siguiente <= timezone.localdate() else '',
                        'revision': revision.revisar(inicio, self.request.company, self.request),
                        'empresa_cambiada': empresa_cambiada(self.request)})
        return context


class RevisionApi(GroupPermissionMixin, View):
    """GET /tributario/api/revision/?mes=AAAA-MM[&empresa=<id>] → {mes, corte, observaciones, por_categoria, pendientes, …}."""
    permission_required = 'view_revision'

    def get(self, request):
        from core.tributario import revision
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        inicio, _ = mes_de(request.GET.get('mes'))
        return JsonResponse(revision.revisar(inicio, request.company, request))


def resumen_de_empresas(usuario, inicio):
    """[{empresa, ruc, rol, mes, pendientes, informativas, por_categoria}] de las membresías ACTIVAS del usuario cuyo rol
    puede ver la revisión. Cada empresa se lee dentro de su propio contexto (gestor por empresa y RLS): nunca con un acceso
    global. Una membresía revocada o una empresa inactiva no aparecen."""
    from core.tenancy.context import company_context
    from core.tenancy.models import Membership
    from core.tributario import revision
    filas = []
    for membresia in (Membership.objects.active().filter(user=usuario, group__permissions__codename='view_revision')
                      .select_related('company', 'group').order_by('company__business_name', 'company_id').distinct()):
        with company_context(membresia.company):
            datos = revision.revisar(inicio, membresia.company)
        filas.append({'empresa_id': membresia.company_id, 'empresa': membresia.company.business_name, 'ruc': membresia.company.ruc,
                      'rol': membresia.group.name, 'mes': datos['mes'], 'pendientes': datos['pendientes'],
                      'informativas': datos['informativas'],
                      'por_categoria': {c: v['revisar'] for c, v in datos['por_categoria'].items()}})
    return filas


class EmpresasPagina(GroupPermissionMixin, TemplateView):
    """Resumen del contador: sus empresas, el mes, los pendientes y el acceso a la revisión de cada una (cambiar de
    empresa pasa por /empresas/cambiar/, que vuelve a comprobar la membresía)."""
    template_name = 'tributario/empresas.html'
    permission_required = 'view_revision'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inicio, valido = mes_de(self.request.GET.get('mes'))
        context.update({'title': 'Revisión de mis empresas', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}',
                        'mes_invalido': bool(self.request.GET.get('mes')) and not valido,
                        'empresas': resumen_de_empresas(self.request.user, inicio), 'activa': self.request.company.pk})
        return context


class EmpresasApi(GroupPermissionMixin, View):
    permission_required = 'view_revision'

    def get(self, request):
        inicio, _ = mes_de(request.GET.get('mes'))
        return JsonResponse({'mes': f'{inicio:%Y-%m}', 'empresas': resumen_de_empresas(request.user, inicio), 'activa': request.company.pk})


# ---------------------------------------------------------------- ATS del mes (entrega D)

class AtsPagina(GroupPermissionMixin, TemplateView):
    """Pantalla funcional del ATS: compras incluidas y excluidas con su motivo, validación y advertencias."""
    template_name = 'tributario/ats.html'
    permission_required = VER

    def get_context_data(self, **kwargs):
        from core.tributario import ats
        context = super().get_context_data(**kwargs)
        inicio, valido = mes_de(self.request.GET.get('mes'))
        context.update({'title': 'ATS del mes', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}',
                        'mes_invalido': bool(self.request.GET.get('mes')) and not valido,
                        'ats': ats.informe(ats.generar(inicio, self.request.company))})
        return context


class AtsApi(GroupPermissionMixin, View):
    """GET /tributario/api/ats/?mes=AAAA-MM[&empresa=<id>] → informe del ATS (sin el XML)."""
    permission_required = VER

    def get(self, request):
        from core.tributario import ats
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        inicio, _ = mes_de(request.GET.get('mes'))
        return JsonResponse(ats.informe(ats.generar(inicio, request.company)))


class DescargarAts(GroupPermissionMixin, View):
    """GET ?mes=AAAA-MM[&empresa=<id>] → ATmmaaaa.zip solo si el XML valida contra el esquema; si no, 409 con los errores."""
    permission_required = VER

    def get(self, request):
        from core.tributario import ats
        if empresa_cambiada(request):
            return HttpResponse(EMPRESA_CAMBIADA, status=409, content_type='text/plain; charset=utf-8')
        inicio, valido = mes_de(request.GET.get('mes'))
        if request.GET.get('mes') and not valido:
            raise Http404
        resultado = ats.generar(inicio, request.company)
        if not resultado['valido']:
            return JsonResponse({'error': 'El ATS no valida contra el esquema oficial: corrige los errores antes de descargarlo.',
                                 'codigo': 'ats_invalido', 'errores_xsd': resultado['errores_xsd']}, status=409)
        contenido = ats.comprimido(resultado)
        ExportacionLibro.objects.create(libro='ats', mes=inicio, formato='zip', filas=len(resultado['incluidas']),
                                        totales={'incluidas': len(resultado['incluidas']), 'excluidas': len(resultado['excluidas']),
                                                 'esquema_sha256': resultado['esquema']['sha256']},
                                        sha256=exportar.huella(contenido), generado_por=request.user)
        respuesta = HttpResponse(contenido, content_type='application/zip')
        respuesta['Content-Disposition'] = f'attachment; filename="{resultado["nombre"]}.zip"'
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        return respuesta
