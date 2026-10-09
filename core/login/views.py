import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db import transaction
from django.forms.utils import ErrorDict
from django.http import HttpResponseRedirect, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import FormView, RedirectView, TemplateView

from config import settings
from core.login.forms import ResetPasswordForm, UpdatePasswordForm
from core.security.models import UserAccess
from core.security.session import client_ip
from core.tenancy.models import audit
from core.user.models import User


TOO_MANY_ATTEMPTS = 'Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.'


def _attempt_keys(request, username=None):
    ip = client_ip(request)
    keys = [f'fpa:login:ip:{ip}']
    if username:
        keys.append(f'fpa:login:usr:{ip}:{username.strip().lower()[:150]}')
    return keys


def _is_blocked(request, username=None):
    ip_key, *user_key = _attempt_keys(request, username)
    if cache.get(ip_key, 0) >= settings.FPA_LOGIN_MAX_INTENTOS * 4:
        return True
    return bool(user_key) and cache.get(user_key[0], 0) >= settings.FPA_LOGIN_MAX_INTENTOS


def _register_failure(request, username=None):
    for key in _attempt_keys(request, username):
        cache.add(key, 0, settings.FPA_LOGIN_BLOQUEO_SEGUNDOS)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, settings.FPA_LOGIN_BLOQUEO_SEGUNDOS)


class LoginAuthView(LoginView):
    form_class = AuthenticationForm
    template_name = 'login/login.html'

    def post(self, request, *args, **kwargs):
        if _is_blocked(request, request.POST.get('username')):
            # Se marca el error sin validar el formulario: validar llamaría a
            # authenticate() y el bloqueo no serviría de nada.
            form = self.get_form()
            form.cleaned_data = {}
            form._errors = ErrorDict()
            form.add_error(None, TOO_MANY_ATTEMPTS)
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        _register_failure(self.request, self.request.POST.get('username'))
        return super().form_invalid(form)

    def get_form(self, form_class=None):
        form = super(LoginAuthView, self).get_form(form_class)
        attrs = {
            'username': {'placeholder': 'Tu usuario', 'autocomplete': 'username', 'autocapitalize': 'none',
                         'spellcheck': 'false', 'autofocus': True},
            'password': {'placeholder': 'Tu contraseña', 'autocomplete': 'current-password'},
        }
        for name, field in form.fields.items():
            field.widget.attrs.update({'class': 'form-control', **attrs.get(name, {})})
        return form

    def get(self, request, *args, **kwargs):
        login_different = reverse_lazy('login_different')
        if request.user.is_authenticated and login_different != request.path:
            return HttpResponseRedirect(reverse_lazy('login_authenticated'))
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        for key in _attempt_keys(self.request, form.get_user().get_username())[1:]:
            cache.delete(key)
        login(self.request, form.get_user())
        if self.request.user.is_authenticated:
            UserAccess(user=self.request.user).save()
            audit(self.request, 'login')
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Ingresar · FacturaPorAquí'
        return context


class LoginResetPasswordView(FormView):
    template_name = 'login/reset_password.html'
    form_class = ResetPasswordForm
    success_url = settings.LOGIN_URL

    def post(self, request, *args, **kwargs):
        data = {}
        reset_key = f'fpa:reset:ip:{client_ip(request)}'
        if cache.get(reset_key, 0) >= settings.FPA_LOGIN_MAX_INTENTOS:
            return HttpResponse(json.dumps({'error': TOO_MANY_ATTEMPTS}), content_type='application/json')
        cache.add(reset_key, 0, settings.FPA_LOGIN_BLOQUEO_SEGUNDOS)
        cache.incr(reset_key)
        try:
            form = self.get_form()
            if form.is_valid():
                self.send_email_reset_password(form.get_user())
            else:
                data['error'] = form.errors
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def send_email_reset_password(self, user):
        with transaction.atomic():
            ABSOLUTE_ROOT_URL = self.request.build_absolute_uri('/').strip('/')
            user.is_change_password = True
            user.email_reset_token = user.generate_token_email()
            user.save()
            activate_account = f"{ABSOLUTE_ROOT_URL}{reverse_lazy('update_password', kwargs={'pk': user.email_reset_token})}"
            message = MIMEMultipart('alternative')
            message['Subject'] = 'Reseteo de contraseña'
            message['From'] = settings.EMAIL_HOST_USER
            message['To'] = user.email
            parameters = {
                'user': user,
                'link_reset_password': activate_account,
                'link_home': ABSOLUTE_ROOT_URL
            }
            html = render_to_string('login/password_reset_email.html', parameters)
            content = MIMEText(html, 'html')
            message.attach(content)
            server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.sendmail(settings.EMAIL_HOST_USER, user.email, message.as_string())
            server.quit()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Recuperar acceso · FacturaPorAquí'
        context['list_url'] = self.success_url
        return context


class LoginLogoutRedirectView(RedirectView):
    pattern_name = 'login'

    def dispatch(self, request, *args, **kwargs):
        logout(request)
        return super().dispatch(request, *args, **kwargs)


class LoginUpdatePasswordView(FormView):
    template_name = 'login/update_password.html'
    form_class = UpdatePasswordForm
    success_url = settings.LOGIN_URL

    def get_object(self):
        return User.objects.filter(email_reset_token=self.kwargs['pk'], is_change_password=True).first()

    def get(self, request, *args, **kwargs):
        if self.get_object() is not None:
            return super().get(request, *args, **kwargs)
        return HttpResponseRedirect(self.success_url)

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            form = self.get_form()
            if form.is_valid():
                user = self.get_object()
                user.is_change_password = False
                user.email_reset_token = None
                user.set_password(request.POST['password'])
                user.save()
            else:
                data['error'] = form.errors
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nueva contraseña · FacturaPorAquí'
        context['list_url'] = self.success_url
        return context


class LoginAuthenticatedView(TemplateView):
    template_name = 'login/login_authenticated.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Sesión activa'
        return context
