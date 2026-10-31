"""Asistente de configuración de facturación: /configuracion/facturacion/ (Propietario y Administrador), y
«Locales y puntos de emisión»: /configuracion/puntos/ (catálogo y autorizaciones para Propietario y Administrador;
selección del punto para cualquier usuario con rol)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from config import settings
from core.configuracion import puntos as pt
from core.configuracion import servicios as sv
from core.configuracion.forms import (AmbienteFirmaForm, AutorizacionForm, ConfirmacionForm, ConfirmarPuntoForm,
                                      EmpresaForm, EstablecimientoForm, NumeracionPuntoForm, PuntoForm, SecuenciaForm)
from core.pos.models import EmissionPoint, Establishment
from core.security.mixins import SessionGroupMixin
from core.tenancy.models import audit


def avisar(request, nivel, texto):
    """Mensaje que el asistente muestra en la propia página (etiqueta «configuracion»)."""
    messages.add_message(request, nivel, texto, extra_tags='configuracion')


def quiere_json(request):
    """Petición del frontend (fetch/XHR) que espera JSON en vez de redirección."""
    return (request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or request.headers.get('accept', '').startswith('application/json')
            or request.POST.get('formato') == 'json')


def destino_seguro(request, por_defecto=settings.LOGIN_REDIRECT_URL):
    """`next` del POST solo si es una ruta de este mismo sitio."""
    url = request.POST.get('next') or ''
    if url.startswith('/') and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                                               require_https=request.is_secure()):
        return url
    return por_defecto


class ConfiguracionAccessMixin(SessionGroupMixin):
    """Solo los roles con el módulo «Configuración de facturación» (Propietario y Administrador)."""

    def get_group_module(self, group):
        return group.groupmodule_set.filter(module__url=sv.URL).first()

    def has_access(self, group):
        return self.get_group_module(group) is not None


class InicioView(ConfiguracionAccessMixin, TemplateView):
    """Retoma el asistente en el primer paso pendiente."""

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(f'{sv.URL}paso/{sv.estado(request.company)["paso_actual"]}/')


class EstadoView(ConfiguracionAccessMixin, TemplateView):
    """Estado en JSON para el frontend (barra de progreso, avisos)."""

    def get(self, request, *args, **kwargs):
        e = sv.estado(request.company)
        return JsonResponse({
            'completo': e['completo'], 'paso_actual': e['paso_actual'], 'pasos': e['pasos'],
            'ambiente': e['ambiente'], 'punto': e['punto_codigo'], 'documentos': e['documentos'],
            'firma': e['firma'], 'requisitos': e['requisitos'],
        })


class PasoView(ConfiguracionAccessMixin, TemplateView):
    template_name = 'configuracion/asistente.html'

    def dispatch(self, request, *args, **kwargs):
        if kwargs['paso'] not in range(1, 6):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    # ------------------------------------------------------------ contexto

    def ambiente_elegido(self):
        valor = self.request.POST.get('ambiente') or self.request.GET.get('ambiente')
        return int(valor) if valor in ('1', '2') else self.request.company.environment_type

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.company
        paso = self.kwargs['paso']
        estado = sv.estado(company)
        context.update({'title': 'Configuración de facturación', 'paso': paso, 'estado': estado,
                        'titulo_paso': dict(sv.PASOS)[paso], 'mensajes': sv.MENSAJES})
        if paso == 1:
            context.setdefault('form', EmpresaForm(instance=company))
        elif paso == 2:
            context['establecimientos'] = Establishment.all_companies.filter(company=company).prefetch_related('points')
            context.setdefault('form_establecimiento', EstablecimientoForm(company=company))
            context.setdefault('form_punto', PuntoForm(company=company))
            context['puede_agregar_punto'] = context['form_punto'].fields['establishment'].queryset.exists()
            punto = estado['punto']
            context.setdefault('form_confirmar', ConfirmarPuntoForm(company=company, initial={'point': punto.pk if punto else None}))
        elif paso == 3:
            ambiente = self.ambiente_elegido()
            punto = estado['punto']
            context.update({'ambiente': ambiente, 'ambientes': sv.AMBIENTES, 'punto': punto})
            context.setdefault('documentos', self.documentos(company, punto, ambiente))
        elif paso == 4:
            from core.suscripciones.servicios import tiene_plan
            context.setdefault('form', AmbienteFirmaForm(initial={'environment_type': company.environment_type,
                                                                  'confirm_production': estado['setup'].production_confirmed}))
            context['firma_habilitada'] = tiene_plan(company)
        elif paso == 5:
            context.setdefault('form', ConfirmacionForm())
        return context

    def documentos(self, company, punto, ambiente, datos=None):
        filas = []
        for tipo, nombre in sv.DOCUMENTOS:
            r = sv.secuencia(company, punto, ambiente, tipo)
            inicial = {'mode': 'mantener', 'last_number': r.last_number_full()} if r else {'mode': 'nuevo'}
            form = SecuenciaForm(datos, prefix=tipo, initial=inicial) if datos is not None else SecuenciaForm(prefix=tipo, initial=inicial)
            filas.append({'tipo': tipo, 'nombre': nombre, 'secuencia': r, 'form': form,
                          'utilizada': bool(r and r.is_used), 'proximo': r.next_number_full() if r else ''})
        return filas

    # ------------------------------------------------------------ envío

    def post(self, request, *args, **kwargs):
        paso = self.kwargs['paso']
        manejador = getattr(self, f'post_paso_{paso}')
        return manejador(request, request.company)

    def siguiente(self, paso, mensaje):
        avisar(self.request, messages.SUCCESS, mensaje)
        return HttpResponseRedirect(f'{sv.URL}paso/{min(paso + 1, 5)}/')

    def post_paso_1(self, request, company):
        form = EmpresaForm(request.POST, instance=company)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        form.save()
        audit(request, 'company_change', company=company, campos=list(form.changed_data), origen='asistente')
        sv.marcar_paso(company, 1, request)
        return self.siguiente(1, 'Datos de la empresa guardados.')

    def post_paso_2(self, request, company):
        accion = request.POST.get('action')
        if accion == 'agregar_establecimiento':
            form = EstablecimientoForm(request.POST, company=company)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form_establecimiento=form))
            datos = form.cleaned_data
            with transaction.atomic():
                est = Establishment(company=company, code=datos['code'], name=datos['name'], address=datos['address'])
                est.save()
                punto = None
                if datos['point_code']:
                    punto = EmissionPoint(company=company, establishment=est, code=datos['point_code'],
                                          description=datos['point_description'])
                    punto.save()
            audit(request, 'billing_point_change', company=company, establecimiento=est.code, accion='agregar')
            if punto:
                audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='agregar')
                avisar(request, messages.SUCCESS, f'Establecimiento {est.code} y punto de emisión {punto.full_code} agregados.')
            else:
                avisar(request, messages.SUCCESS, f'Establecimiento {est.code} agregado.')
        elif accion == 'agregar_punto':
            form = PuntoForm(request.POST, company=company)
            if not form.fields['establishment'].queryset.exists():
                # Página abierta antes de tener establecimientos: el formulario de punto ya no se muestra
                avisar(request, messages.ERROR, sv.MENSAJES['elige_establecimiento'])
                return HttpResponseRedirect(f'{sv.URL}paso/2/')
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form_punto=form))
            punto = EmissionPoint(company=company, **form.cleaned_data)
            punto.save()
            audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='agregar')
            avisar(request, messages.SUCCESS, f'Punto de emisión {punto.full_code} agregado.')
        elif accion == 'desactivar_punto':
            punto = EmissionPoint.all_companies.filter(company=company, pk=request.POST.get('point')).first()
            if punto is None:
                raise Http404
            if punto.is_default or any(r.is_used for r in punto.sequences.all()):
                avisar(request, messages.ERROR, sv.MENSAJES['punto_en_uso'])
            else:
                punto.is_active = False
                punto.save(update_fields=['is_active'])
                audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='desactivar')
        elif accion == 'confirmar':
            form = ConfirmarPuntoForm(request.POST, company=company)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form_confirmar=form))
            sv.confirmar_punto(company, form.cleaned_data['point'], request)
            return self.siguiente(2, f'Emitirás desde {form.cleaned_data["point"].full_code}.')
        else:
            raise Http404
        return HttpResponseRedirect(f'{sv.URL}paso/2/')

    def post_paso_3(self, request, company):
        punto = sv.punto_predeterminado(company)
        if punto is None:
            avisar(request, messages.ERROR, sv.MENSAJES['falta_punto'])
            return HttpResponseRedirect(f'{sv.URL}paso/2/')
        ambiente = self.ambiente_elegido()
        filas = self.documentos(company, punto, ambiente, request.POST)
        invalida, hay_errores = False, False
        for fila in filas:
            form = fila['form']
            if not form.is_valid():
                hay_errores = True
                continue
            try:
                r = sv.configurar_secuencia(company, punto, ambiente, fila['tipo'], form.cleaned_data['mode'],
                                            form.cleaned_data['last_number'], form.cleaned_data['confirm'],
                                            request.user, request)
                invalida = invalida or r.confirmed_at is None
            except sv.ErrorConfiguracion as e:
                form.add_error(None, str(e))
                hay_errores = True
        if hay_errores:
            return self.render_to_response(self.get_context_data(documentos=self.documentos_con_errores(filas, company, punto, ambiente)))
        if ambiente == company.environment_type:
            sv.marcar_paso(company, 3, request, invalida=invalida)
            return self.siguiente(3, 'Numeración guardada.')
        avisar(request, messages.SUCCESS, f'Numeración de {sv.AMBIENTES[ambiente]} guardada.')
        return HttpResponseRedirect(f'{sv.URL}paso/3/?ambiente={ambiente}')

    def documentos_con_errores(self, filas, company, punto, ambiente):
        # Conserva lo escrito y los errores, con el estado actualizado de cada secuencia.
        for fila in filas:
            r = sv.secuencia(company, punto, ambiente, fila['tipo'])
            fila.update(secuencia=r, utilizada=bool(r and r.is_used), proximo=r.next_number_full() if r else '')
        return filas

    def post_paso_4(self, request, company):
        form = AmbienteFirmaForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        try:
            cambio = guardar_ambiente_y_firma(company, form.cleaned_data, request)
        except sv.ErrorConfiguracion as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form))
        sv.marcar_paso(company, 4, request, invalida=cambio)
        if cambio and not sv.paso_completo(company, sv.obtener_setup(company), 3):
            avisar(request, messages.WARNING, f'Configura la numeración para el ambiente {sv.AMBIENTES[company.environment_type]}.')
            return HttpResponseRedirect(f'{sv.URL}paso/3/')
        return self.siguiente(4, 'Ambiente y firma guardados.')

    def post_paso_5(self, request, company):
        form = ConfirmacionForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        try:
            sv.confirmar_configuracion(company, request.user, request)
        except sv.ErrorConfiguracion as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form))
        avisar(request, messages.SUCCESS, 'Configuración confirmada. Ya puedes emitir con la numeración revisada.')
        return HttpResponseRedirect(f'{sv.URL}paso/5/')


def guardar_ambiente_y_firma(company, datos, request):
    """Paso 4. Devuelve True si cambió el ambiente (exige revisar la numeración y confirmar de nuevo)."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    from core.suscripciones.servicios import tiene_plan
    archivo, clave = datos.get('electronic_signature'), datos.get('electronic_signature_key') or ''
    if archivo or clave:
        if archivo and not tiene_plan(company):
            raise sv.ErrorConfiguracion(sv.MENSAJES['firma_sin_plan'])
        if archivo:
            contenido = archivo.read()
            archivo.seek(0)
        elif company.electronic_signature:
            with open(company.electronic_signature.path, 'rb') as f:
                contenido = f.read()
        else:
            raise sv.ErrorConfiguracion('Sube el archivo de tu firma electrónica (.p12).')
        clave_efectiva = clave or company.electronic_signature_key
        if not clave_efectiva:
            raise sv.ErrorConfiguracion(sv.MENSAJES['firma_sin_clave'])
        try:
            pkcs12.load_key_and_certificates(contenido, clave_efectiva.encode())
        except Exception:  # noqa: BLE001 - archivo dañado o clave incorrecta
            raise sv.ErrorConfiguracion(sv.MENSAJES['firma_clave']) from None
        if archivo:
            company.electronic_signature.save(archivo.name, archivo, save=False)
        company.electronic_signature_key = clave_efectiva
    ambiente = datos['environment_type']
    cambio = company.environment_type != ambiente
    company.environment_type = ambiente
    company.save()
    setup = sv.obtener_setup(company)
    setup.production_confirmed = ambiente == sv.PRODUCCION and bool(datos.get('confirm_production'))
    setup.save(update_fields=['production_confirmed', 'updated_at'])
    audit(request, 'company_change', company=company, origen='asistente', ambiente=ambiente,
          firma_actualizada=bool(archivo), clave_actualizada=bool(clave))
    return cambio


class OtrosComprobantesView(ConfiguracionAccessMixin, TemplateView):
    """Numeración de los comprobantes opcionales (retención, …): se configura y confirma en un paso."""
    template_name = 'configuracion/otros.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.company
        punto, filas = sv.otros_documentos(company)
        enviado = kwargs.get('formularios', {})
        for fila in filas:
            r = fila['secuencia']
            inicial = {'mode': 'mantener', 'last_number': r.last_number_full()} if r else {'mode': 'nuevo'}
            fila['form'] = enviado.get(fila['tipo']) or SecuenciaForm(prefix=fila['tipo'], initial=inicial)
        context.update({'title': 'Otros comprobantes', 'punto': punto, 'documentos': filas,
                        'setup_completo': sv.obtener_setup(company).completed_at is not None,
                        'ambiente': sv.AMBIENTES.get(company.environment_type)})
        return context

    def post(self, request, *args, **kwargs):
        tipo = request.POST.get('tipo', '')
        if tipo not in dict(sv.OTROS_DOCUMENTOS):
            raise Http404
        form = SecuenciaForm(request.POST, prefix=tipo)
        if form.is_valid():
            try:
                r = sv.configurar_otro_documento(request.company, tipo, form.cleaned_data['mode'],
                                                 form.cleaned_data['last_number'], form.cleaned_data['confirm'],
                                                 request.user, request)
                avisar(request, messages.SUCCESS, f'Numeración de {sv.NOMBRE_DOCUMENTO[tipo]} confirmada: el próximo será '
                                                  f'{r.next_number_full()}.')
                return HttpResponseRedirect(sv.URL_OTROS)
            except sv.ErrorConfiguracion as e:
                form.add_error(None, str(e))
        return self.render_to_response(self.get_context_data(formularios={tipo: form}))



# ---------------------------------------------------------------- locales y puntos de emisión

class PuntosAccessMixin(SessionGroupMixin):
    """Solo los roles con el módulo «Locales y puntos de emisión» (Propietario y Administrador)."""

    def get_group_module(self, group):
        return group.groupmodule_set.filter(module__url=pt.URL).first()

    def has_access(self, group):
        return self.get_group_module(group) is not None


class PuntosView(PuntosAccessMixin, TemplateView):
    """Catálogo de locales y puntos, numeración por punto y puntos autorizados por usuario."""
    template_name = 'configuracion/puntos.html'

    def get_context_data(self, **kwargs):
        company = self.request.company
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Locales y puntos de emisión',
            'estado': pt.estado(self.request),
            'form_establecimiento': kwargs.get('form_establecimiento') or EstablecimientoForm(company=company),
            'form_punto': kwargs.get('form_punto') or PuntoForm(company=company),
            'form_numeracion': kwargs.get('form_numeracion') or NumeracionPuntoForm(company=company),
            'form_autorizacion': kwargs.get('form_autorizacion') or AutorizacionForm(company=company, activos=False),
            'mensajes': {**sv.MENSAJES, **pt.MENSAJES},
            'url_asistente': sv.URL, 'url_estado': pt.URL + 'estado.json', 'url_seleccionar': pt.URL_SELECCIONAR,
        })
        return context

    def respuesta(self, request, mensaje, form=None, nombre_form=None, estado_http=200):
        """Redirección con aviso (formularios normales) o JSON (fetch/XHR)."""
        if quiere_json(request):
            datos = {'ok': estado_http == 200, 'mensaje': mensaje}
            if form is not None and form.errors:
                datos['errores'] = form.errors.get_json_data()
            if estado_http == 200:
                datos['estado'] = pt.estado(request)
            return JsonResponse(datos, status=estado_http)
        if form is not None and form.errors:
            avisar(request, messages.ERROR, mensaje)
            return self.render_to_response(self.get_context_data(**{nombre_form: form}))
        avisar(request, messages.SUCCESS if estado_http == 200 else messages.ERROR, mensaje)
        return HttpResponseRedirect(pt.URL)

    def post(self, request, *args, **kwargs):
        company = request.company
        accion = request.POST.get('action')
        try:
            if accion == 'agregar_establecimiento':
                form = EstablecimientoForm(request.POST, company=company)
                if not form.is_valid():
                    return self.respuesta(request, 'Revisa los datos del establecimiento.', form, 'form_establecimiento', 400)
                datos = form.cleaned_data
                with transaction.atomic():
                    est = Establishment(company=company, code=datos['code'], name=datos['name'], address=datos['address'])
                    est.save()
                    punto = None
                    if datos['point_code']:
                        punto = EmissionPoint(company=company, establishment=est, code=datos['point_code'],
                                              description=datos['point_description'])
                        punto.save()
                audit(request, 'billing_point_change', company=company, establecimiento=est.code, accion='agregar')
                if punto:
                    audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='agregar')
                    return self.respuesta(request, f'Establecimiento {est.code} y punto de emisión {punto.full_code} agregados.')
                return self.respuesta(request, f'Establecimiento {est.code} agregado.')
            if accion == 'agregar_punto':
                form = PuntoForm(request.POST, company=company)
                if not form.is_valid():
                    return self.respuesta(request, 'Revisa los datos del punto de emisión.', form, 'form_punto', 400)
                punto = EmissionPoint(company=company, **form.cleaned_data)
                punto.save()
                audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='agregar')
                return self.respuesta(request, f'Punto de emisión {punto.full_code} agregado.')
            if accion in ('activar_punto', 'desactivar_punto'):
                punto = pt.activar_punto(request, request.POST.get('point'), accion == 'activar_punto')
                clave = 'punto_activado' if accion == 'activar_punto' else 'punto_desactivado'
                return self.respuesta(request, pt.MENSAJES[clave].format(punto=punto.full_code))
            if accion == 'numeracion':
                form = NumeracionPuntoForm(request.POST, company=company)
                if not form.is_valid():
                    return self.respuesta(request, 'Revisa los datos de la numeración.', form, 'form_numeracion', 400)
                d = form.cleaned_data
                r = pt.configurar_numeracion(request, d['point'].pk, d['tipo'], d['ambiente'], d['mode'], d['last_number'], d['confirm'])
                return self.respuesta(request, (f'Numeración de {sv.NOMBRE_DOCUMENTO[d["tipo"]]} de {d["point"].full_code} en '
                                                f'{sv.AMBIENTES[d["ambiente"]]} confirmada: próximo {r.next_number_full()}.'))
            if accion in ('autorizar', 'quitar_autorizacion'):
                form = AutorizacionForm(request.POST, company=company, activos=accion == 'autorizar')
                if not form.is_valid():
                    return self.respuesta(request, 'Elige un usuario de la empresa y un punto de emisión.', form, 'form_autorizacion', 400)
                if accion == 'autorizar':
                    usuario, punto = pt.autorizar(request, form.cleaned_data['user'].pk, form.cleaned_data['point'].pk)
                    return self.respuesta(request, f'{usuario.names or usuario.username} puede emitir desde {punto.full_code}.')
                usuario, punto = pt.quitar_autorizacion(request, form.cleaned_data['user'].pk, form.cleaned_data['point'].pk)
                return self.respuesta(request, f'{usuario.names or usuario.username} ya no tiene autorizado {punto.full_code}.')
        except (pt.ErrorPunto, sv.ErrorConfiguracion) as e:
            return self.respuesta(request, str(e), estado_http=400)
        raise Http404


class PuntosEstadoView(PuntosAccessMixin, View):
    """Catálogo en JSON para el frontend (Propietario y Administrador)."""

    def get(self, request, *args, **kwargs):
        return JsonResponse(pt.estado(request))


class SeleccionView(LoginRequiredMixin, View):
    """Punto activo y elegibles del usuario en la empresa activa (cualquier usuario con rol)."""

    def get(self, request, *args, **kwargs):
        return JsonResponse(pt.seleccion_json(request))


class SeleccionarView(LoginRequiredMixin, View):
    """POST punto=<id> [next=<ruta>]: fija el punto desde el que emite el usuario en la empresa activa. Solo cambia su
    preferencia: ni el predeterminado de la empresa ni la selección de otros usuarios ni los formularios ya abiertos."""

    def post(self, request, *args, **kwargs):
        try:
            pt.seleccionar(request, request.POST.get('punto'))
        except pt.ErrorPunto as e:
            if quiere_json(request):
                return JsonResponse({'error': str(e)}, status=400)
            messages.error(request, str(e))
            return HttpResponseRedirect(destino_seguro(request))
        if quiere_json(request):
            return JsonResponse({'ok': True, 'seleccion': pt.seleccion_json(request)})
        return HttpResponseRedirect(destino_seguro(request))
