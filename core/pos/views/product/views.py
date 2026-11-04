import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

import xlsxwriter
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, TemplateView
from django.views.generic.base import View
from openpyxl import load_workbook

from core.pos.choices import NOMBRE_TARIFA_IVA, PORCENTAJE_IVA
from core.pos.forms import ProductForm, Product, Category
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

COLUMNA_TARIFA = {'4': '15 %', '5': '5 %', '0': '0 %', '7': 'Exento', '6': 'No objeto'}


def tarifa_desde_excel(valor):
    """Código de la columna «Tarifa de IVA» (15 %, 5 %, 0 %, Exento, No objeto); '' si está vacía o no se reconoce."""
    texto = ' '.join(str(valor if valor is not None else '').lower().replace('%', ' ').split())
    if texto.startswith('exento'):
        return '7'
    if texto.startswith('no objeto'):
        return '6'
    try:
        numero = Decimal(texto.replace(',', '.'))
    except InvalidOperation:
        return ''
    if 0 < numero < 1:
        numero *= 100   # celda con formato de porcentaje (0,15)
    return {Decimal('15'): '4', Decimal('5'): '5', Decimal('0'): '0'}.get(numero, '')


# Importación del catálogo (R3): cada efecto exige su permiso, como en las pantallas de alta, edición y ajuste de stock.
PERMISO_DEL_EFECTO = {'add_product': 'crear productos', 'change_product': 'modificar productos',
                      'adjust_product_stock': 'ajustar el stock', 'add_category': 'crear categorías'}
CAMPOS_DEL_CATALOGO = ('name', 'code', 'category_id', 'price', 'pvp', 'inventoried', 'tarifa_iva')


def _centavos(valor):
    return Decimal(str(valor)).quantize(Decimal('0.01'))


def plan_de_importacion(hoja):
    """Lee las filas sin escribir nada: [(fila, producto con los valores nuevos, stock anterior, categoría nueva o None,
    efectos {permiso: True})]. Un mismo id repetido reutiliza el producto, como el guardado fila por fila."""
    plan, productos = [], {}
    for cell in hoja.iter_rows(min_row=2, max_row=hoja.max_row):
        row = cell[0].row
        id = int(hoja.cell(row=row, column=1).value)
        if id not in productos:
            productos[id] = Product.objects.select_for_update().filter(pk=id).first()
        product = productos[id]
        nuevo = product is None or product.pk is None   # un id nuevo repetido en el archivo sigue siendo un alta
        if product is None:
            product = productos[id] = Product()
        anterior = product.stock if product.pk else 0
        antes = {campo: getattr(product, campo) for campo in CAMPOS_DEL_CATALOGO}
        product.name = str(hoja.cell(row=row, column=2).value)
        product.code = str(hoja.cell(row=row, column=3).value)
        nombre_categoria = str(hoja.cell(row=row, column=4).value)
        categoria = Category.objects.filter(name=nombre_categoria).first()
        if categoria is not None:
            product.category = categoria
        else:
            product.category_id = None
        product.price = _centavos(float(hoja.cell(row=row, column=5).value))
        product.pvp = _centavos(float(hoja.cell(row=row, column=6).value))
        product.stock = int(hoja.cell(row=row, column=7).value)
        product.inventoried = str(hoja.cell(row=row, column=8).value).lower() == 'si'
        # La columna «Tarifa de IVA» manda; los archivos sin ella usan «¿Se cobra impuesto?» y conservan
        # la tarifa del producto si sigue de acuerdo (un producto del 5 % sigue en 5 %).
        con_impuesto = str(hoja.cell(row=row, column=9).value).lower() == 'si'
        tarifa = tarifa_desde_excel(hoja.cell(row=row, column=10).value)
        if tarifa:
            product.tarifa_iva = tarifa
        elif not product.tarifa_iva or con_impuesto != (PORCENTAJE_IVA.get(product.tarifa_iva, 0) > 0):
            product.tarifa_iva = '4' if con_impuesto else '0'
        efectos = {}
        if nuevo:
            efectos['add_product'] = True   # el stock inicial va con el alta, como en el formulario de producto
        else:
            despues = {campo: getattr(product, campo) for campo in CAMPOS_DEL_CATALOGO}
            if categoria is None or any(antes[c] != despues[c] for c in CAMPOS_DEL_CATALOGO):
                efectos['change_product'] = True
            if product.stock != anterior:
                efectos['adjust_product_stock' if product.inventoried else 'change_product'] = True
        if categoria is None:
            efectos['add_category'] = True
        plan.append((row, product, anterior, product.stock, None if categoria is not None else nombre_categoria, efectos))
    return plan


def permisos_que_faltan(request, plan):
    """{permiso: [filas]} de los efectos que el rol no tiene."""
    grupo = get_group(request)
    tiene = set(grupo.permissions.values_list('codename', flat=True)) if grupo is not None else set()
    faltan = {}
    for row, _, _, _, _, efectos in plan:
        for permiso in efectos:
            if permiso not in tiene:
                faltan.setdefault(permiso, []).append(row)
    return faltan


class ProductListView(GroupPermissionMixin, TemplateView):
    template_name = 'product/list.html'
    permission_required = 'view_product'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in Product.objects.filter():
                    data.append(i.toJSON())
            elif action == 'upload_excel':
                with transaction.atomic():
                    archive = request.FILES['archive']
                    workbook = load_workbook(filename=archive, data_only=True)
                    # Primero se planifica todo sin escribir; si a una fila le falta un permiso, se rechaza el lote entero.
                    plan = plan_de_importacion(workbook[workbook.sheetnames[0]])
                    faltan = permisos_que_faltan(request, plan)
                    if faltan:
                        detalle = '; '.join(f"{PERMISO_DEL_EFECTO[permiso]} (filas {', '.join(map(str, filas[:10]))})"
                                            for permiso, filas in faltan.items())
                        return HttpResponse(json.dumps({
                            'error': f'Tu perfil no puede importar este archivo: le falta permiso para {detalle}. No se cambió nada.',
                            'codigo': 'sin_permiso', 'faltan': {permiso: filas for permiso, filas in faltan.items()}}),
                            status=403, content_type='application/json')
                    from core.contabilidad.servicios import registrar_ajuste
                    for row, product, anterior, stock, categoria_nueva, _ in plan:
                        if categoria_nueva is not None:
                            product.category = Category.objects.get_or_create(name=categoria_nueva)[0]
                        product.save()
                        if product.inventoried:   # kardex: el cambio de stock de la importación queda registrado
                            registrar_ajuste(product, anterior, stock, request.user, origen='importacion')
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Productos'
        context['create_url'] = reverse_lazy('product_create')
        return context


class ProductCreateView(GroupPermissionMixin, CreateView):
    model = Product
    template_name = 'product/create.html'
    form_class = ProductForm
    success_url = reverse_lazy('product_list')
    permission_required = 'add_product'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'add':
                # Alta desde la factura (Codex, 9e65aea): un código o nombre repetido por otra pestaña u otro usuario llega
                # hasta la restricción única; con un punto de guardado la respuesta es un mensaje claro y la transacción
                # sigue sana (en PostgreSQL, sin él, las consultas siguientes de la misma transacción fallaban).
                try:
                    with transaction.atomic():
                        data = self.get_form().save()
                except IntegrityError:
                    data = {'error': 'Ya existe un producto con ese código o nombre en esta empresa: búscalo en el catálogo.'}
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = Product.objects.all()
                pattern = request.POST['pattern']
                if pattern == 'pattern':
                    name = request.POST['name'].strip()
                    category = request.POST['category']
                    if len(category):
                        data['valid'] = not queryset.filter(name__iexact=name, category_id=category).exists()
                elif pattern == 'code':
                    data['valid'] = not queryset.filter(code__iexact=request.POST['code']).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Producto'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class ProductUpdateView(GroupPermissionMixin, UpdateView):
    model = Product
    template_name = 'product/create.html'
    form_class = ProductForm
    success_url = reverse_lazy('product_list')
    permission_required = 'change_product'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:   # sin sesión, el mixin lleva al login (antes: error 500)
            self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'edit':
                try:   # dentro de una transacción: un código repetido a la vez no deja nada a medias
                    with transaction.atomic():
                        data = self.get_form().save()
                except IntegrityError:
                    data = {'error': 'Ya existe un producto con ese código o nombre en esta empresa: búscalo en el catálogo.'}
            elif action == 'validate_data':
                data = {'valid': True}
                id = self.get_object().id
                queryset = Product.objects.all().exclude(id=id)
                pattern = request.POST['pattern']
                if pattern == 'name':
                    name = request.POST['name'].strip()
                    category = request.POST['category']
                    if len(category):
                        data['valid'] = not queryset.filter(name__iexact=name, category_id=category).exists()
                elif pattern == 'code':
                    data['valid'] = not queryset.filter(code__iexact=request.POST['code']).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición de un Producto'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class ProductDeleteView(GroupPermissionMixin, DeleteView):
    model = Product
    template_name = 'delete.html'
    success_url = reverse_lazy('product_list')
    permission_required = 'delete_product'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context


class ProductStockAdjustmentView(GroupPermissionMixin, TemplateView):
    template_name = 'product/stock_adjustment.html'
    permission_required = 'adjust_product_stock'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search_product':
                data = []
                ids = json.loads(request.POST['ids'])
                term = request.POST['term']
                queryset = Product.objects.filter(inventoried=True).exclude(id__in=ids).order_by('name')
                if len(term):
                    queryset = queryset.filter(Q(name__icontains=term) | Q(code__icontains=term))
                    queryset = queryset[0:10]
                for i in queryset:
                    item = i.toJSON()
                    item['value'] = i.get_full_name()
                    data.append(item)
            elif action == 'create':
                from core.contabilidad.servicios import ajustar_stock
                with transaction.atomic():
                    for i in json.loads(request.POST['products']):
                        ajustar_stock(i['id'], int(i['newstock']), request.user)   # kardex: el ajuste queda registrado
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Ajuste de Stock de Productos'
        return context


class ProductExportExcelView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        try:
            headers = {'Id': 15, 'Nombre': 75, 'Código': 20, 'Categoría': 20, 'Precio de Compra': 20, 'Precio de Venta': 20, 'Stock': 10, '¿Es inventariado?': 15, '¿Se cobra impuesto?': 15, 'Tarifa de IVA': 15}
            output = BytesIO()
            workbook = xlsxwriter.Workbook(output)
            worksheet = workbook.add_worksheet('productos')
            cell_format = workbook.add_format({'bold': True, 'align': 'center', 'border': 1})
            row_format = workbook.add_format({'align': 'center', 'border': 1})
            index = 0
            for name, width in headers.items():
                worksheet.set_column(first_col=index, last_col=index, width=width)
                worksheet.write(0, index, name, cell_format)
                index += 1
            row = 1
            for product in Product.objects.filter().order_by('id'):
                worksheet.write(row, 0, product.id, row_format)
                worksheet.write(row, 1, product.name, row_format)
                worksheet.write(row, 2, product.code, row_format)
                worksheet.write(row, 3, product.category.name, row_format)
                worksheet.write(row, 4, f'{product.price:.2f}', row_format)
                worksheet.write(row, 5, f'{product.pvp:.2f}', row_format)
                worksheet.write(row, 6, product.stock, row_format)
                worksheet.write(row, 7, 'Si' if product.inventoried else 'No', row_format)
                worksheet.write(row, 8, 'Si' if product.with_tax else 'No', row_format)
                worksheet.write(row, 9, COLUMNA_TARIFA.get(product.tarifa_iva, NOMBRE_TARIFA_IVA.get(product.tarifa_iva, '')), row_format)
                row += 1
            workbook.close()
            output.seek(0)
            response = HttpResponse(output, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f"attachment; filename=PRODUCTOS_{datetime.now().date().strftime('%d_%m_%Y')}.xlsx"
            return response
        except:
            pass
        return HttpResponseRedirect(reverse_lazy('product_list'))
