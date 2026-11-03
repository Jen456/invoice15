"""Kardex por producto e inventario valorizado: páginas funcionales (el diseño lo hace Codex), API JSON, XLSX y
movimientos manuales. Ver `view_kardex`: Propietario, Administrador, Contador y Consulta. Registrar y anular movimientos
manuales: Propietario, Administrador y Contador. Plan pagado vigente (regla de /contabilidad/)."""
import io
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.contabilidad import kardex as kx, servicios as sv
from core.contabilidad.models import TIPOS_MANUALES, MovimientoManual
from core.security.mixins import GroupPermissionMixin
from core.tributario.views import EMPRESA_CAMBIADA, empresa_cambiada

VER = sv.VER
MAX_PRODUCTOS = 50


def _json(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if hasattr(valor, 'isoformat'):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json(v) for v in valor]
    return valor


def _producto(request, valor):
    from core.pos.models import Product
    try:
        pk = int(str(valor or '').strip())
    except ValueError:
        return None
    return Product.objects.filter(pk=pk, inventoried=True).first()


def _rango(request):
    hoy = timezone.localdate()
    hasta, hasta_ok = kx.fecha_de(request.GET.get('hasta'), hoy)
    desde, desde_ok = kx.fecha_de(request.GET.get('desde'), hasta.replace(day=1))
    if desde > hasta:
        desde, desde_ok = hasta.replace(day=1), False
    invalido = (bool(request.GET.get('desde')) and not desde_ok) or (bool(request.GET.get('hasta')) and not hasta_ok)
    return desde, hasta, invalido


def _error(e):
    datos = {'error': str(e), 'codigo': e.codigo}
    if e.errores:
        datos['errores'] = e.errores
    if e.movimiento is not None:
        datos['movimiento'] = sv.dict_movimiento(e.movimiento)
    return JsonResponse(datos, status=e.estado)


def _manuales(producto):
    return [sv.dict_movimiento(m) for m in MovimientoManual.objects.filter(producto=producto)
            .select_related('producto', 'creado_por', 'anulado_por').order_by('-fecha', '-id')[:200]]


class KardexPagina(GroupPermissionMixin, TemplateView):
    """GET: kardex del producto elegido. POST (formulario sin JavaScript): `accion=registrar` (campos del movimiento
    manual) o `accion=anular` (`movimiento`, `motivo`); vuelve a la misma pantalla con el resultado en mensajes."""
    template_name = 'contabilidad/kardex.html'
    permission_required = VER

    def get_context_data(self, **kwargs):
        import uuid

        from core.pos.models import Product
        context = super().get_context_data(**kwargs)
        desde, hasta, invalido = _rango(self.request)
        producto = _producto(self.request, self.request.GET.get('producto'))
        context.update({'title': 'Kardex por producto', 'desde': desde.isoformat(), 'hasta': hasta.isoformat(), 'rango_invalido': invalido,
                        'producto': producto, 'kardex': _json(kx.kardex(producto, desde, hasta)) if producto else None,
                        'manuales': _manuales(producto) if producto else [], 'capacidades': sv.capacidades(self.request),
                        'tipos': [{'id': c, 'name': n} for c, n in TIPOS_MANUALES], 'hoy': timezone.localdate().isoformat(),
                        'producto_pedido': bool(self.request.GET.get('producto')) and producto is None,
                        'productos': list(Product.objects.filter(inventoried=True).order_by('name', 'id').values('id', 'code', 'name')[:500]),
                        'clave_sugerida': uuid.uuid4().hex})
        return context

    def post(self, request, *args, **kwargs):
        from urllib.parse import urlencode

        from django.contrib import messages
        from django.http import HttpResponseRedirect
        try:
            if request.POST.get('accion') == 'anular':
                try:
                    pk = int(request.POST.get('movimiento') or 0)
                except ValueError:
                    pk = 0
                sv.anular(request, pk, request.POST.get('motivo'))
                messages.success(request, 'Movimiento anulado: el kardex ya no lo cuenta.')
            else:
                _, repetido = sv.registrar(request, request.POST)
                messages.success(request, 'Ese movimiento ya estaba registrado: no se repitió.' if repetido else 'Movimiento registrado.')
        except sv.ErrorKardex as e:
            messages.error(request, str(e))
        consulta = {k: request.POST.get(k, '') for k in ('producto', 'desde', 'hasta') if request.POST.get(k)}
        return HttpResponseRedirect('/contabilidad/kardex/' + (f'?{urlencode(consulta)}' if consulta else ''))


class KardexApi(GroupPermissionMixin, View):
    """GET /contabilidad/api/kardex/<producto_id>/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD[&empresa=<id>]."""
    permission_required = VER

    def get(self, request, producto_id):
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        producto = _producto(request, producto_id)
        if producto is None:
            return JsonResponse({'error': sv.MENSAJES['producto'], 'codigo': 'producto'}, status=404)
        desde, hasta, _ = _rango(request)
        return JsonResponse({**_json(kx.kardex(producto, desde, hasta)), 'manuales': _manuales(producto),
                             'capacidades': sv.capacidades(request)})


class ProductosApi(GroupPermissionMixin, View):
    """GET /contabilidad/api/kardex/productos/?q=texto → productos inventariados (código o nombre), máximo 50."""
    permission_required = VER

    def get(self, request):
        from django.db.models import Q

        from core.pos.models import Product
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        q = (request.GET.get('q') or '').strip()[:60]
        productos = Product.objects.filter(inventoried=True)
        if q:
            productos = productos.filter(Q(name__icontains=q) | Q(code__icontains=q))
        return JsonResponse({'productos': [{'id': p.pk, 'codigo': p.code, 'nombre': p.name, 'stock': p.stock}
                                           for p in productos.order_by('name', 'id')[:MAX_PRODUCTOS]]})


class InventarioPagina(GroupPermissionMixin, TemplateView):
    template_name = 'contabilidad/inventario.html'
    permission_required = VER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fecha, valida = kx.fecha_de(self.request.GET.get('fecha'))
        context.update({'title': 'Inventario valorizado', 'fecha': fecha.isoformat(),
                        'fecha_invalida': bool(self.request.GET.get('fecha')) and not valida, 'inventario': _json(kx.inventario(fecha))})
        return context


class InventarioApi(GroupPermissionMixin, View):
    """GET /contabilidad/api/inventario/?fecha=AAAA-MM-DD[&empresa=<id>]."""
    permission_required = VER

    def get(self, request):
        if empresa_cambiada(request):
            return JsonResponse({'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}, status=409)
        fecha, _ = kx.fecha_de(request.GET.get('fecha'))
        return JsonResponse(_json(kx.inventario(fecha)))


def _xlsx(hojas):
    """[(título, encabezados, filas [(valor, tipo)])] → XLSX sin fórmulas (los textos se escriben como texto)."""
    from openpyxl import Workbook

    from core.tributario.exportar import _escribir
    wb = Workbook()
    for n, (titulo, encabezados, filas) in enumerate(hojas):
        hoja = wb.active if n == 0 else wb.create_sheet()
        hoja.title = titulo[:31]
        for col, encabezado in enumerate(encabezados, start=1):
            _escribir(hoja, 1, col, encabezado, 'texto')
        for f, fila in enumerate(filas, start=2):
            for col, (valor, tipo) in enumerate(fila, start=1):
                if tipo == 'costo' and isinstance(valor, Decimal):
                    celda = hoja.cell(row=f, column=col, value=valor)
                    celda.number_format = '0.0000'
                else:
                    _escribir(hoja, f, col, valor, tipo)
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _descarga(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    respuesta['Cache-Control'] = 'private, no-store'
    respuesta['X-Content-Type-Options'] = 'nosniff'
    return respuesta


class ExportarKardex(GroupPermissionMixin, View):
    """GET ?producto=<id>&desde=&hasta=[&empresa=<id>] → XLSX del kardex del producto."""
    permission_required = VER

    def get(self, request):
        if empresa_cambiada(request):
            return HttpResponse(EMPRESA_CAMBIADA, status=409, content_type='text/plain; charset=utf-8')
        producto = _producto(request, request.GET.get('producto'))
        if producto is None:
            raise Http404
        desde, hasta, _ = _rango(request)
        k = kx.kardex(producto, desde, hasta)
        a = k['saldo_anterior']
        filas = [[(desde.isoformat(), 'texto'), ('Saldo anterior', 'texto'), ('', 'texto'), ('', 'texto'), ('', 'texto'),
                  ('', 'texto'), ('', 'texto'), (a['cantidad'], 'cantidad'), (a['costo_promedio'], 'costo'), (a['valor'], 'importe'), ('', 'texto')]]
        for m in k['movimientos']:
            filas.append([(m['fecha'].isoformat(), 'texto'), (m['tipo_nombre'], 'texto'), (m['documento']['numero'], 'texto'),
                          (m['entrada'] or '', 'cantidad'), (m['salida'] or '', 'cantidad'), (m['costo_unitario'], 'costo'),
                          (m['costo_total'], 'importe'), (m['saldo_cantidad'], 'cantidad'), (m['costo_promedio'], 'costo'),
                          (m['saldo_valor'], 'importe'), ('' if m['conocido'] else 'Costo desconocido', 'texto')])
        avisos = [[(x['texto'], 'texto')] for x in k['advertencias']]
        contenido = _xlsx([(f'Kardex {producto.code}', ['Fecha', 'Movimiento', 'Documento', 'Entrada', 'Salida', 'Costo unitario',
                                                        'Costo total', 'Saldo', 'Costo promedio', 'Valor del saldo', 'Observación'], filas),
                           ('Avisos', ['Aviso'], avisos)])
        codigo = re.sub(r'[^A-Za-z0-9_-]+', '-', producto.code or '').strip('-')[:20] or str(producto.pk)   # va en una cabecera
        return _descarga(contenido, f'kardex-{codigo}-{request.company.ruc}-{desde:%Y%m%d}-{hasta:%Y%m%d}.xlsx')


class ExportarInventario(GroupPermissionMixin, View):
    """GET ?fecha=AAAA-MM-DD[&empresa=<id>] → XLSX del inventario valorizado."""
    permission_required = VER

    def get(self, request):
        if empresa_cambiada(request):
            return HttpResponse(EMPRESA_CAMBIADA, status=409, content_type='text/plain; charset=utf-8')
        fecha, _ = kx.fecha_de(request.GET.get('fecha'))
        inv = kx.inventario(fecha)
        filas = [[(f['producto']['codigo'], 'texto'), (f['producto']['nombre'], 'texto'), (f['cantidad'], 'cantidad'),
                  (f['costo_promedio'], 'costo'), (f['valor'], 'importe'), ('' if f['conocido'] else 'Costo desconocido', 'texto'),
                  (f['stock_actual'] if f['stock_actual'] is not None else '', 'cantidad'),
                  (f['diferencia_stock'] if f['diferencia_stock'] is not None else '', 'cantidad')] for f in inv['filas']]
        t = inv['totales']
        filas.append([('', 'texto'), ('Total con costo conocido', 'texto'), ('', 'texto'), ('', 'texto'), (t['valor_conocido'], 'importe'),
                      (f'{t["sin_costo"]} sin costo conocido', 'texto'), ('', 'texto'), ('', 'texto')])
        contenido = _xlsx([(f'Inventario {fecha:%Y-%m-%d}', ['Código', 'Producto', 'Cantidad', 'Costo promedio', 'Valor', 'Observación',
                                                             'Stock actual', 'Diferencia con el stock'], filas)])
        return _descarga(contenido, f'inventario-{request.company.ruc}-{fecha:%Y%m%d}.xlsx')


def _datos(request):
    if (request.content_type or '').startswith('application/json'):
        try:
            datos = json.loads(request.body or b'{}')
        except ValueError:
            datos = {}
        return datos if isinstance(datos, dict) else {}
    return request.POST


class MovimientosApi(GroupPermissionMixin, View):
    """GET ?producto=<id> → movimientos manuales; POST → registra uno (clave, producto, tipo, fecha, cantidad,
    costo_unitario, documento, nota)."""
    permission_required = VER

    def get(self, request):
        producto = _producto(request, request.GET.get('producto'))
        if producto is None:
            return JsonResponse({'error': sv.MENSAJES['producto'], 'codigo': 'producto'}, status=404)
        return JsonResponse({'movimientos': _manuales(producto), 'capacidades': sv.capacidades(request)})

    def post(self, request):
        try:
            movimiento, repetido = sv.registrar(request, _datos(request))
        except sv.ErrorKardex as e:
            return _error(e)
        return JsonResponse({'movimiento': sv.dict_movimiento(movimiento), 'repetido': repetido}, status=200 if repetido else 201)


class AnularMovimiento(GroupPermissionMixin, View):
    """POST motivo → anula el movimiento manual (queda con quién, cuándo y por qué; el kardex deja de contarlo)."""
    permission_required = VER

    def post(self, request, pk):
        try:
            movimiento = sv.anular(request, pk, _datos(request).get('motivo'))
        except sv.ErrorKardex as e:
            return _error(e)
        return JsonResponse({'movimiento': sv.dict_movimiento(movimiento)})
