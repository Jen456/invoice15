import logging
import random
import string
from email.utils import parseaddr
from itertools import cycle

import requests
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from config import settings
from core.pos.choices import VOUCHER_STAGE
from core.pos.clientes import separar_correos
from core.pos.utilities.firma import ErrorFirma, firmar_xml

logger = logging.getLogger(__name__)


class SRI:
    """Clave de acceso, firma y correo al comprador. El envío y la autorización viven en core/pos/emision.py."""

    def compute_mod11(self, pass_key_48=''):
        if len(pass_key_48) > 48:
            return ''
        addition = 0
        factors = cycle((2, 3, 4, 5, 6, 7))
        for digit, factor in zip(reversed(pass_key_48), factors):
            addition += int(digit) * factor
        number = 11 - addition % 11
        if number == 11:
            number = 0
        elif number == 10:
            number = 1
        return str(number)

    def generate_number(self, amount=8):
        return ''.join(random.choices(list(string.digits), k=amount))

    def create_access_key(self, instance, fecha=None):
        """Clave de 49 dígitos con el ambiente del propio comprobante (no el que tenga hoy la empresa)."""
        fecha = fecha or timezone.localdate()
        password_48 = f"{fecha.strftime('%d%m%Y')}{instance.receipt.voucher_type}{instance.company.ruc}{instance.environment_type}{instance.receipt.establishment_code}{instance.receipt.issuing_point_code}{instance.voucher_number}{self.generate_number()}{instance.company.emission_type}"
        module11 = self.compute_mod11(pass_key_48=password_48)
        if len(module11):
            return f'{password_48}{module11}'
        return None

    def create_voucher_errors(self, instance, errors):
        """Historial de «Errores de comprobantes». Solo registra: el estado lo decide core/pos/emision.py."""
        from core.pos.models import VoucherErrors
        try:
            voucher_errors = VoucherErrors()
            voucher_errors.reference = instance.voucher_number_full
            voucher_errors.stage = errors['stage']
            voucher_errors.receipt = instance.receipt
            voucher_errors.errors = errors
            voucher_errors.environment_type = instance.environment_type
            voucher_errors.save()
        except Exception:
            logger.exception('No se pudo registrar el error del comprobante %s', getattr(instance, 'voucher_number_full', ''))

    def firm_xml(self, instance, xml):
        """Firma XAdES-BES en el propio proceso (core.pos.utilities.firma)."""
        response = {'resp': False, 'stage': VOUCHER_STAGE[1][0]}
        try:
            company = instance.company
            if not company.electronic_signature:
                raise ErrorFirma('Sube tu firma electrónica (.p12) en «Configuración de facturación», paso 4.')
            with company.electronic_signature.open('rb') as archivo:
                contenido = archivo.read()
            response['xml'] = firmar_xml(xml, contenido, company.electronic_signature_key)
            response['resp'] = True
        except ErrorFirma as e:
            response['error'] = str(e)
        except Exception as e:
            response['error'] = f'No se pudo firmar el comprobante ({e.__class__.__name__}).'
        finally:
            if 'error' in response:
                self.create_voucher_errors(instance, response)
        return response

    @staticmethod
    def _remitente(nombre, direccion):
        nombre = ' '.join(str(nombre or '').replace('"', '').replace('<', '').replace('>', '').split())
        return f'"{nombre}" <{direccion}>'   # Django codifica el nombre (acentos) al enviar

    def _correo_saliente(self, company):
        """Conexión, remitente y responder-a: el SMTP propio de la empresa si lo configuró; si no, el de la plataforma."""
        responder = [company.email] if '@' in (company.email or '') else []
        if company.email_host and company.email_host_user and company.email_host_password:
            puerto = int(company.email_port or 587)
            conexion = get_connection('django.core.mail.backends.smtp.EmailBackend', host=company.email_host, port=puerto,
                                      username=company.email_host_user, password=company.email_host_password,
                                      use_tls=puerto != 465, use_ssl=puerto == 465, timeout=20, fail_silently=False)
            return conexion, self._remitente(company.tradename or company.business_name, company.email_host_user), responder
        _, direccion = parseaddr(settings.DEFAULT_FROM_EMAIL)
        return get_connection(fail_silently=False), self._remitente(f'{company.tradename or company.business_name} vía FacturaPorAquí', direccion), responder

    def notify_by_email(self, instance, company, client):
        """Entrega al comprador el XML autorizado y el RIDE (Res. NAC-DGERCGC18-00000233, art. 6)."""
        response = {'resp': False, 'stage': VOUCHER_STAGE[4][0]}
        try:
            destinatarios = [c for c in separar_correos(client.user.email, getattr(client, 'extra_emails', '')) if '@' in c]
            if not client.send_email_invoice or not destinatarios:
                response['resp'] = True
                response['mensaje'] = 'El cliente no recibe comprobantes por correo: entrégale el RIDE impreso.'
                return response
            if not instance.xml_authorized or not instance.pdf_authorized:
                raise ValueError('el comprobante aún no tiene el XML autorizado y el RIDE')
            conexion, remitente, responder = self._correo_saliente(company)
            total = getattr(instance, 'total', None)
            if total is not None:
                monto = f'Total: USD {total:.2f}\n'
            elif hasattr(instance, 'total_retenido'):
                monto = f'Total retenido: USD {instance.total_retenido:.2f}\n'
            else:
                monto = ''   # guía de remisión: no tiene importes
            contenido = (f'Estimado(a) {client.user.names}:\n\n'
                         f'{company.tradename or company.business_name} le envía el siguiente comprobante electrónico '
                         f'autorizado por el SRI, en formato XML y PDF (RIDE).\n\n'
                         f'Documento: {instance.receipt.name} {instance.voucher_number_full}\n'
                         f'Fecha de emisión: {(instance.emission_date or instance.date_joined):%d/%m/%Y}\n'
                         f'{monto}'
                         f'Clave de acceso y número de autorización: {instance.access_code}\n')
            correo = EmailMessage(subject=f'{instance.receipt.name.capitalize()} {instance.voucher_number_full} - '
                                          f'{company.tradename or company.business_name}',
                                  body=contenido, from_email=remitente, to=destinatarios, reply_to=responder, connection=conexion)
            with instance.pdf_authorized.open('rb') as archivo:
                correo.attach(f'{instance.access_code}.pdf', archivo.read(), 'application/pdf')
            with instance.xml_authorized.open('rb') as archivo:
                correo.attach(f'{instance.access_code}.xml', archivo.read(), 'application/xml')
            correo.send()
            instance.status = 'authorized_and_sent_by_email'
            type(instance).all_companies.filter(pk=instance.pk).update(status=instance.status)
            response['resp'] = True
        except Exception as e:
            response['error'] = (f'{instance.receipt.name.capitalize()} {instance.voucher_number_full}: autorizado por el SRI, pero no se '
                                 f'pudo enviar el correo al destinatario ({e.__class__.__name__}: {str(e)[:200]}).')
            self.create_voucher_errors(instance, response)
        return response

    def search_ruc_in_sri(self, ruc):
        response = {'error': 'El número de ruc es inválido'}
        url = f'https://srienlinea.sri.gob.ec/movil-servicios/api/v1.0/estadoTributario/{ruc}'
        r = requests.get(url, timeout=15)
        if r.status_code == requests.codes.ok:
            response = r.json()
        else:
            response['error'] = r.json()['mensaje']
        return response
