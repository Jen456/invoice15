"""Asistente de configuración de facturación: /configuracion/facturacion/ (Propietario y Administrador)."""
from django.contrib import messages
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.views.generic import TemplateView

from core.configuracion import servicios as sv
from core.configuracion.forms import (AmbienteFirmaForm, ConfirmacionForm, ConfirmarPuntoForm, EmpresaForm,
                                      EstablecimientoForm, PuntoForm, SecuenciaForm)
from core.pos.models import EmissionPoint, Establishment
from core.security.mixins import SessionGroupMixin
from core.tenancy.models import audit


def avisar(request, nivel, texto):
    """Mensaje que el asistente muestra en la propia página (etiqueta «configuracion»)."""
    messages.add_message(request, nivel, texto, extra_tags='configuracion')


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
            est = Establishment(company=company, **form.cleaned_data)
            est.save()
            audit(request, 'billing_point_change', company=company, establecimiento=est.code, accion='agregar')
            avisar(request, messages.SUCCESS, f'Establecimiento {est.code} agregado.')
        elif accion == 'agregar_punto':
            form = PuntoForm(request.POST, company=company)
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
