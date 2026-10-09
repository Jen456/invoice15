"""Registro propio de empresas: alta, confirmación del correo y reenvío del enlace.

El registro crea la empresa (con su RUC o cédula), el usuario INACTIVO y su
membresía de Propietario. La cuenta se activa al abrir el enlace firmado que se
envía por correo (válido FPA_REGISTRO_HORAS_ENLACE horas y de un solo uso:
deja de servir en cuanto la cuenta está activa o cambia el correo).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, TemplateView

from django.conf import settings
from core.login.forms import ReenviarConfirmacionForm, RegistroForm, registro_pendiente
from core.security.session import client_ip
from core.tenancy.models import ROLE_OWNER, Membership, audit
from core.user.models import User

logger = logging.getLogger(__name__)
SALT = 'fpa.registro.confirmar'
SESION = 'fpa_registro'


def token_confirmacion(user):
    return signing.TimestampSigner(salt=SALT).sign_object({'u': user.pk, 'e': (user.email or '').lower()})


def usuario_por_token(token):
    try:
        datos = signing.TimestampSigner(salt=SALT).unsign_object(
            token, max_age=timedelta(hours=settings.FPA_REGISTRO_HORAS_ENLACE))
    except signing.BadSignature:  # incluye SignatureExpired
        return None
    user = User.objects.filter(pk=datos.get('u')).first()
    if user is None or (user.email or '').lower() != datos.get('e') or not registro_pendiente(user):
        return None
    return user


def ocultar_correo(email):
    local, _, dominio = email.partition('@')
    return f'{local[:1]}•••@{dominio}'


def enviar_confirmacion(request, user, empresa_nombre):
    """Envía el enlace. Devuelve False (y lo registra) si el correo no sale."""
    if settings.EMAIL_BACKEND.endswith('smtp.EmailBackend') and not settings.EMAIL_HOST_USER:
        logger.warning('Correo de la plataforma sin configurar: no se envía la confirmación del usuario %s', user.pk)
        return False
    enlace = request.build_absolute_uri(reverse('registro_confirmar', args=[token_confirmacion(user)]))
    contexto = {'nombre': user.names or user.username, 'empresa': empresa_nombre, 'enlace': enlace,
                'horas': settings.FPA_REGISTRO_HORAS_ENLACE}
    try:
        send_mail('Confirma tu correo en FacturaPorAquí',
                  render_to_string('login/correo_confirmacion.txt', contexto),
                  settings.DEFAULT_FROM_EMAIL, [user.email],
                  html_message=render_to_string('login/correo_confirmacion.html', contexto))
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo de confirmación al usuario %s', user.pk)
        return False


def limite_superado(request, clave, maximo):
    llave = f'fpa:{clave}:ip:{client_ip(request)}'
    cache.add(llave, 0, 3600)
    try:
        intentos = cache.incr(llave)
    except ValueError:
        cache.set(llave, 1, 3600)
        intentos = 1
    return intentos > maximo


class RegistroView(FormView):
    template_name = 'login/registro.html'
    form_class = RegistroForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if limite_superado(request, 'registro', settings.FPA_REGISTRO_MAX_POR_HORA):
            form.is_valid()
            form.add_error(None, 'Se alcanzó el límite de registros desde tu conexión. Inténtalo dentro de una hora.')
            return self.form_invalid(form)
        return self.form_valid(form) if form.is_valid() else self.form_invalid(form)

    def form_valid(self, form):
        datos = form.cleaned_data
        from core.pos.models import Company
        with transaction.atomic():
            empresa = Company.objects.create(
                ruc=datos['identificacion'], business_name=datos['nombre'], tradename=datos['nombre'],
                main_address='', establishment_address='', establishment_code='001', issuing_point_code='001',
                special_taxpayer='', mobile=datos['celular'], phone='',
                email=datos['email'] if len(datos['email']) <= 50 else '', website='', iva=Decimal('15.00'),
                electronic_signature_key='', email_host_user='', email_host_password='')
            user = User(username=datos['username'], names=datos['nombre'], email=datos['email'],
                        phone=datos['celular'], is_active=False)
            user.set_password(datos['password'])
            user.save()
            Membership.objects.create(user=user, company=empresa, group=Group.objects.get(name=ROLE_OWNER))
            # El registro de auditoría se crea con el usuario explícito (no hay sesión todavía).
            from core.tenancy.models import AuditLog
            AuditLog.objects.create(user=user, company=empresa, action='signup', ip=client_ip(self.request) or None,
                                    detail={'identificacion': 'ruc' if len(datos['identificacion']) == 13 else 'cedula'})
        enviado = enviar_confirmacion(self.request, user, empresa.tradename)
        self.request.session[SESION] = {'correo': ocultar_correo(user.email), 'enviado': enviado}
        return HttpResponseRedirect(reverse('registro_enviado'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crea tu cuenta · FacturaPorAquí'
        return context


class RegistroEnviadoView(TemplateView):
    template_name = 'login/registro_enviado.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Confirma tu correo · FacturaPorAquí'
        context['registro'] = self.request.session.get(SESION, {})
        context['horas'] = settings.FPA_REGISTRO_HORAS_ENLACE
        return context


def confirmar(request, token):
    user = usuario_por_token(token)
    if user is not None:
        user.is_active = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=['is_active', 'email_verified_at'])
        membresia = Membership.objects.filter(user=user).select_related('company').first()
        from core.tenancy.models import AuditLog
        AuditLog.objects.create(user=user, company=membresia.company if membresia else None, action='email_verified',
                                ip=client_ip(request) or None)
    return render(request, 'login/registro_confirmado.html', {
        'title': 'Confirmación de correo · FacturaPorAquí', 'confirmado': user is not None})


class ReenviarConfirmacionView(FormView):
    template_name = 'login/registro_reenviar.html'
    form_class = ReenviarConfirmacionForm

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if limite_superado(request, 'registro-reenvio', settings.FPA_REGISTRO_MAX_POR_HORA):
            form.is_valid()
            form.add_error(None, 'Se alcanzó el límite de reenvíos desde tu conexión. Inténtalo dentro de una hora.')
            return self.form_invalid(form)
        return self.form_valid(form) if form.is_valid() else self.form_invalid(form)

    def form_valid(self, form):
        email = form.cleaned_data['email'].strip().lower()
        for user in User.objects.filter(email__iexact=email, is_active=False, email_verified_at__isnull=True):
            if registro_pendiente(user):
                membresia = Membership.objects.filter(user=user).select_related('company').first()
                enviar_confirmacion(self.request, user, membresia.company.tradename if membresia else '')
                audit(self.request, 'signup_resend', company=membresia.company if membresia else None, usuario=user.username)
        # Misma respuesta exista o no la cuenta: no se revela qué correos están registrados.
        return render(self.request, self.template_name, {'form': self.form_class(), 'enviado': True,
                                                         'title': 'Reenviar enlace · FacturaPorAquí'})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reenviar enlace · FacturaPorAquí'
        return context
