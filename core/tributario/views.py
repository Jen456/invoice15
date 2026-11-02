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


class LibroApi(GroupPermissionMixin, View):
    """GET /tributario/api/libros/<libro>/?mes=AAAA-MM → el libro completo con columnas, filas, totales y exclusiones."""
    permission_required = VER

    def get(self, request, libro):
        if libro not in lb.LIBROS:
            return JsonResponse({'error': 'Libro desconocido.', 'codigo': 'libro'}, status=404)
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
        nombre = f'libros-{inicio:%Y-%m}' if clave == 'todos' else f'libro-{clave.replace("_", "-")}-{inicio:%Y-%m}'
        respuesta['Content-Disposition'] = f'attachment; filename="{nombre}.{formato}"'
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        return respuesta
