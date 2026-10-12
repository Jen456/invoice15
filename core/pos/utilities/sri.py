import base64
import os.path
import random
import smtplib
import string
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from itertools import cycle
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from django.core.files import File
from django.utils import timezone
from lxml import etree
from suds.client import Client

from config import settings
from core.pos.choices import VOUCHER_STAGE, INVOICE_STATUS
from core.pos.utilities.firma import ErrorFirma, firmar_xml


class SRI:
    def __init__(self):
        self.base_dir = os.path.dirname(__file__)

    def get_absolute_path(self, path):
        return str(Path(path).absolute())

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
        fecha = fecha or timezone.localdate()
        password_48 = f"{fecha.strftime('%d%m%Y')}{instance.receipt.voucher_type}{instance.company.ruc}{instance.company.environment_type}{instance.receipt.establishment_code}{instance.receipt.issuing_point_code}{instance.voucher_number}{self.generate_number()}{instance.company.emission_type}"
        module11 = self.compute_mod11(pass_key_48=password_48)
        if len(module11):
            return f'{password_48}{module11}'
        return None

    def get_receipt_url(self, instance):
        if instance.company.environment_type == 2:
            return 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl'
        return 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl'

    def get_authorization_url(self, instance):
        if instance.company.environment_type == 2:
            return 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl'
        return 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl'

    def check_sequential_error(self, errors):
        if 'error' in errors and isinstance(errors['error'], dict):
            if 'errors' in errors['error']:
                for error in errors['error']['errors']:
                    if 'mensaje' in error and error['mensaje'] == 'ERROR SECUENCIAL REGISTRADO':
                        return True
        return False

    def create_voucher_errors(self, instance, errors):
        from core.pos.models import VoucherErrors
        try:
            voucher_errors = VoucherErrors()
            voucher_errors.reference = instance.voucher_number_full
            voucher_errors.stage = errors['stage']
            voucher_errors.receipt = instance.receipt
            if type(errors) is str:
                voucher_errors.errors = {'error': errors}
            else:
                voucher_errors.errors = errors
            voucher_errors.environment_type = instance.environment_type
            voucher_errors.save()
        except:
            pass
        finally:
            if self.check_sequential_error(errors=errors):
                instance.status = INVOICE_STATUS[4][0]
                instance.edit()

    def create_xml(self, instance):
        response = {'resp': False, 'stage': VOUCHER_STAGE[1][0]}
        try:
            xml, access_code = instance.generate_xml()
            instance.access_code = access_code
            instance.save()
            response['resp'] = True
            response['xml'] = xml
        except Exception as e:
            response['error'] = str(e)
        finally:
            if 'error' in response:
                self.create_voucher_errors(instance, response)
        return response

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

    def validate_xml(self, instance, xml):
        response = {'resp': False, 'stage': VOUCHER_STAGE[2][0]}
        try:
            document = xml.strip().encode('utf-8')
            base64_binary_xml = base64.b64encode(document).decode('utf-8')
            sri_client = Client(self.get_receipt_url(instance))
            result = sri_client.service.validarComprobante(base64_binary_xml)
            status = result.estado
            if status == 'DEVUELTA':
                receipt = result.comprobantes.comprobante[0]
                response['error'] = {'access_code': receipt.claveAcceso, 'errors': []}
                for count, value in enumerate(receipt.mensajes):
                    message = value[1][count]
                    values = dict()
                    for name in ['identificador', 'informacionAdicional', 'mensaje', 'tipo']:
                        if name in message:
                            values[name] = message[name]
                    response['error']['errors'].append(values)
            elif status == 'RECIBIDA':
                response['resp'] = True
                response['xml'] = xml
        except Exception as e:
            response['error'] = str(e)
        finally:
            if 'error' in response:
                self.create_voucher_errors(instance, response)
        return response

    def authorize_xml(self, instance):
        response = {'resp': False, 'stage': VOUCHER_STAGE[3][0]}
        try:
            sri_client = Client(self.get_authorization_url(instance))
            result = sri_client.service.autorizacionComprobante(instance.access_code)
            if len(result):
                receipt = result[2].autorizacion[0]
                if receipt.estado == 'NO AUTORIZADO':
                    response['error'] = {'access_code': instance.access_code, 'stage': receipt.estado, 'authorization_date': str(receipt.fechaAutorizacion), 'errors': []}
                    for count, value in enumerate(receipt.mensajes):
                        message = value[1][count]
                        values = dict()
                        for name in ['identificador', 'informacionAdicional', 'mensaje', 'tipo']:
                            if name in message:
                                values[name] = message[name]
                        response['error']['errors'].append(values)
                else:
                    xml_authorization = etree.Element('autorizacion')
                    etree.SubElement(xml_authorization, 'estado').text = receipt.estado
                    etree.SubElement(xml_authorization, 'numeroAutorizacion').text = receipt.numeroAutorizacion
                    etree.SubElement(xml_authorization, 'fechaAutorizacion', attrib={'class': "fechaAutorizacion"}).text = str(receipt.fechaAutorizacion.strftime("%d/%m/%Y %H:%M:%S"))
                    voucher_sri = etree.SubElement(xml_authorization, 'comprobante')
                    voucher_sri.text = etree.CDATA(receipt.comprobante)
                    xml_text = etree.tostring(xml_authorization, encoding="utf8", xml_declaration=True).decode('utf8').replace("'", '"')
                    with NamedTemporaryFile(delete=True) as file_temp:
                        xml_path = f'xml/{instance.receipt.get_name_xml()}_{instance.access_code}.xml'
                        file_temp.write(xml_text.encode())
                        file_temp.flush()
                        instance.xml_authorized.save(name=xml_path, content=File(file_temp))
                        instance.authorization_date = receipt.fechaAutorizacion
                        instance.generate_pdf_authorized()
                        instance.status = INVOICE_STATUS[1][0]
                        instance.save()
                        response['resp'] = True
        except Exception as e:
            response['error'] = str(e)
        finally:
            if 'error' in response:
                self.create_voucher_errors(instance, response)
        return response

    def notify_by_email(self, instance, company, client):
        response = {'resp': False, 'stage': VOUCHER_STAGE[4][0]}
        try:
            if client.send_email_invoice:
                message = MIMEMultipart('alternative')
                message['Subject'] = f'Notificación de {instance.receipt.name} {instance.voucher_number_full}'
                message['From'] = company.email_host_user
                message['To'] = client.user.email
                content = f'Estimado(a)\n\n{client.user.names.upper()}\n\n'
                content += f'{company.tradename} informa sobre documento electrónico emitido adjunto en formato XML Y PDF.\n\n'
                content += f'DOCUMENTO: {instance.receipt.name} {instance.voucher_number_full}\n'
                content += f"FECHA: {instance.date_joined.strftime('%Y-%m-%d')}\n"
                content += f'MONTO: {str(float(round(instance.total, 2)))}\n'
                content += f'CÓDIGO DE ACCESO: {instance.access_code}\n'
                content += f'AUTORIZACIÓN: {instance.access_code}'
                part = MIMEText(content)
                message.attach(part)
                with instance.pdf_authorized.open('rb') as file:
                    part = MIMEApplication(file.read())
                    part.add_header('Content-Disposition', 'attachment', filename=f'{instance.access_code}.pdf')
                    message.attach(part)
                with instance.xml_authorized.open('rb') as file:
                    part = MIMEApplication(file.read())
                    part.add_header('Content-Disposition', 'attachment', filename=f'{instance.access_code}.xml')
                    message.attach(part)
                server = smtplib.SMTP(company.email_host, company.email_port)
                server.starttls()
                server.login(company.email_host_user, company.email_host_password)
                server.sendmail(company.email_host_user, message['To'], message.as_string())
                server.quit()
            instance.status = INVOICE_STATUS[2][0]
            instance.save()
            response['resp'] = True
        except Exception as e:
            response['error'] = str(e)
            self.create_voucher_errors(instance, response)
        return response

    def search_ruc_in_sri(self, ruc):
        response = {'error': 'El número de ruc es inválido'}
        url = f'https://srienlinea.sri.gob.ec/movil-servicios/api/v1.0/estadoTributario/{ruc}'
        r = requests.get(url)
        if r.status_code == requests.codes.ok:
            response = r.json()
        else:
            response['error'] = r.json()['mensaje']
        return response
