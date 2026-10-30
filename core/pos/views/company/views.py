import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from django.http import HttpResponse
from django.views.generic import UpdateView

from config import settings
from core.pos.forms import CompanyForm, Company
from core.security.mixins import GroupPermissionMixin
from core.suscripciones.servicios import tiene_plan

# Etapa 2 (O2): datos tributarios que se auditan con company_change al cambiar y días que cubre el calendario.
CAMPOS_TRIBUTARIOS = ('tipo_contribuyente', 'periodicidad_iva')
DIAS_VENCIMIENTOS = 90


class CompanyUpdateView(GroupPermissionMixin, UpdateView):
    template_name = 'company/create.html'
    form_class = CompanyForm
    model = Company
    permission_required = 'change_company'
    success_url = settings.LOGIN_REDIRECT_URL

    def get_object(self, queryset=None):
        # Solo la empresa activa; las empresas se crean desde el panel de plataforma.
        return self.request.company

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'create_or_edit':
                instance = self.get_object()
                antes = {campo: getattr(instance, campo) or '' for campo in CAMPOS_TRIBUTARIOS} if instance.pk else None
                if instance.pk is not None:
                    form = CompanyForm(request.POST, request.FILES, instance=instance)
                else:
                    form = CompanyForm(request.POST, request.FILES)
                data = form.save()
                if antes is not None and 'error' not in data:
                    self.auditar_tributarios(request, form.instance, antes)
            elif action == 'load_certificate':
                instance = self.get_object()
                if not tiene_plan(instance):
                    raise ValueError('Para cargar tu firma electrónica (.p12) primero activa un plan en «Plan y pagos».')
                # Sin clave escrita se usa la guardada (el formulario ya no la muestra).
                electronic_signature_key = request.POST.get('electronic_signature_key', '') or instance.electronic_signature_key
                archive = None
                if 'certificate' in request.FILES:
                    archive = request.FILES['certificate'].file
                elif instance.pk is not None:
                    archive = open(instance.electronic_signature.path, 'rb')
                if archive:
                    with archive as file:
                        private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(file.read(), electronic_signature_key.encode())
                        for s in certificate.subject:
                            data[s.oid._name] = s.value
                        public_key = certificate.public_key().public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo).decode('utf-8')
                        data['public_key'] = public_key
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    @staticmethod
    def auditar_tributarios(request, company, antes):
        """company_change con {campo: [antes, después]} si cambió el tipo de contribuyente o la periodicidad (solo str)."""
        from core.tenancy.models import audit
        cambios = {campo: [str(antes[campo]), str(getattr(company, campo) or '')] for campo in CAMPOS_TRIBUTARIOS
                   if (getattr(company, campo) or '') != antes[campo]}
        if cambios:
            audit(request, 'company_change', company=company, campos=cambios)

    def contexto_tributario(self, company):
        """Sugerencias (nunca se guardan) y vencimientos de los próximos 90 días (Etapa 2, O2)."""
        from dataclasses import asdict
        from datetime import timedelta

        from django.utils import timezone

        from core.pos import calendario_sri
        from core.pos.choices import PERIODICIDAD_IVA, TIPO_CONTRIBUYENTE
        tipo = calendario_sri.sugerir_tipo_contribuyente(company)
        periodicidad = calendario_sri.sugerir_periodicidad_iva(company)
        sugerencias = {'tipo': tipo, 'periodicidad': periodicidad, 'faltan': company.datos_tributarios_faltantes,
                       'tipo_nombre': dict(TIPO_CONTRIBUYENTE).get(tipo[0], ''),
                       'periodicidad_nombre': dict(PERIODICIDAD_IVA).get(periodicidad[0], '')}
        hoy = timezone.localdate()
        try:
            vencimientos = [asdict(v) for v in calendario_sri.vencimientos_de_empresa(company, hoy,
                                                                                      hoy + timedelta(days=DIAS_VENCIMIENTOS))]
            aviso = ''
        except ValueError:   # RUC inválido: no se puede calcular el noveno dígito
            vencimientos = []
            aviso = 'Revisa el RUC de la empresa: con él se calculan tus fechas de vencimiento.'
        return {'sugerencias_tributarias': sugerencias, 'vencimientos': vencimientos, 'vencimientos_aviso': aviso}

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context.update(self.contexto_tributario(self.request.company))
        context['title'] = 'Configuración de la Compañia'
        context['list_url'] = self.success_url
        context['action'] = 'create_or_edit'
        context['firma_habilitada'] = tiene_plan(self.request.company)
        from core.configuracion.servicios import estado
        context['config_facturacion'] = estado(self.request.company)
        return context
