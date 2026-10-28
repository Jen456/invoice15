"""Ayudas de las pruebas de la Etapa 2 · ventas y empresa (O2), con datos ficticios. tests/helpers.py no se toca.

Las facturas «autorizadas» de estas ayudas se crean directamente (sin pasar por el SRI); las notas de crédito y de débito
pasan por la emisión real con el SRI falso de tests/test_emision_sri.py, que es lo que dispara comprobante_autorizado.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.test import RequestFactory
from django.utils import timezone

from core.importacion import clave_acceso, recibidos
from core.importacion.recibidos import RetencionLeida, RetencionLineaLeida, SustentoLeido
from core.pos import emision
from core.pos.models import CtasCollect, Product, Receipt, Sale, SaleDetail
from core.tenancy.context import company_context
from core.tenancy.models import Membership

_SIN_DATO = object()
RUC_AGENTE = '0991234567001'      # el del comprador de tests/test_emision_sri.py (cliente con RUC)


def factura_autorizada(empresa, cliente, empleado, producto, cantidad=2, credito=False, ambiente=2, fecha=None, tipo='01',
                       estado='authorized', emitida=_SIN_DATO, autorizada=None, vence=None):
    """Venta con su detalle y totales (2 × $10 + IVA 15 % = $23 con el producto P100). Si credito=True, con su CxC.

    emitida: fecha de emisión del SRI (por defecto `fecha`; None = venta antigua sin emission_date)."""
    fecha = fecha or timezone.localdate()
    with company_context(empresa):
        receipt, _ = Receipt.objects.get_or_create(voucher_type=tipo, environment_type=ambiente, establishment_code='001',
                                                   issuing_point_code='002', defaults={'sequence': 500})
        numero = receipt.reservar_numero()
        venta = Sale(client=cliente, receipt=receipt, employee=empleado, voucher_number=numero,
                     voucher_number_full=f'001-002-{numero}', iva=Decimal('0.15'), environment_type=ambiente,
                     date_joined=fecha, emission_date=fecha if emitida is _SIN_DATO else emitida, authorization_date=autorizada,
                     status=estado, payment_type='credito' if credito else 'efectivo', payment_method='20',
                     end_credit=vence or fecha + timedelta(days=30), create_electronic_invoice=tipo == '01')
        venta.save()
        SaleDetail.objects.create(sale=venta, product=producto, cant=cantidad, price=producto.pvp)
        venta.calculate_detail()
        venta.calculate_invoice()
        if producto.inventoried:
            Product.objects.filter(pk=producto.pk).update(stock=F('stock') - cantidad)
        if credito:
            CtasCollect.objects.create(sale=venta, date_joined=fecha, end_date=venta.end_credit, debt=venta.total,
                                       saldo=venta.total)
        venta.refresh_from_db()
        return venta


def cxc_de(venta):
    with company_context(venta.company):
        return CtasCollect.objects.filter(sale=venta).order_by('id').first()


def nota_credito_autorizada(venta, lineas=None, sri=None, motivo='Devolución de mercadería de prueba', autorizar=True):
    """Nota de crédito por la emisión real (notas_credito.crear + emision.preparar + emision.emitir) con el SRI falso."""
    from core.pos import notas_credito
    with company_context(venta.company):
        with transaction.atomic():
            nota = notas_credito.crear(venta.company, venta.pk, lineas, motivo)
            emision.preparar(nota)
        if sri is not None and autorizar:
            sri.respuestas_autorizacion.append('AUTORIZADO')
        emision.emitir(nota)
        nota.refresh_from_db()
        return nota


def nota_debito_autorizada(venta, valor, usuario, sri=None, autorizar=True):
    """Nota de débito por la emisión real, con tarifa 0 % (valor total = valor)."""
    from core.comprobantes import notas_debito as snd
    from core.configuracion import servicios as cfg
    with company_context(venta.company):
        if not Receipt.objects.filter(voucher_type='05').exists():
            cfg.configurar_otro_documento(venta.company, '05', 'otro_sistema', '001-002-000000003', True)
        with transaction.atomic():
            nota = snd.crear(venta.company, usuario, venta, {'tarifa_iva': '0.00'}, [('Interés por mora', str(valor))])
            emision.preparar(nota)
        if sri is not None and autorizar:
            sri.respuestas_autorizacion.append('AUTORIZADO')
        emision.emitir(nota)
        nota.refresh_from_db()
        return nota


def linea(impuesto='1', codigo='312', base='20.00', porcentaje=None, valor=None):
    from core.comprobantes.retenciones_recibidas import LineaRetencionRecibida
    return LineaRetencionRecibida(impuesto=impuesto, codigo=codigo, base_imponible=Decimal(base),
                                  porcentaje=None if porcentaje is None else Decimal(porcentaje),
                                  valor_retenido=None if valor is None else Decimal(valor))


def retencion_datos(**cambios):
    """Retención manual de renta 312 (2 % de 20,00 = 0,40) e IVA 1 (30 % de 3,00 = 0,90): total 1,30."""
    from core.comprobantes.retenciones_recibidas import DatosRetencionRecibida
    datos = dict(numero='001-001-000000123', autorizacion='1234567890', fecha_emision=timezone.localdate(),
                 lineas=[linea('1', '312', '20.00'), linea('2', '1', '3.00')])
    datos.update(cambios)
    return DatosRetencionRecibida(**datos)


def clave_acceso_ficticia(fecha, cod_doc='07', ruc=RUC_AGENTE, ambiente=2, estab='001', pto='001', sec='000000123'):
    primeros = f'{fecha:%d%m%Y}{cod_doc}{ruc}{ambiente}{estab}{pto}{sec}123456781'
    return primeros + clave_acceso.digito_verificador(primeros)


def sustento(venta, lineas=None, cod_doc='01', numero=None):
    """SustentoLeido de una factura (15 dígitos sin guiones, como en el XML): renta 312 sobre 20,00 e IVA 1 sobre 3,00."""
    lineas = lineas if lineas is not None else (RetencionLineaLeida('1', '312', Decimal('20.00'), Decimal('2.00'), Decimal('0.40')),
                                                RetencionLineaLeida('2', '1', Decimal('3.00'), Decimal('30.00'), Decimal('0.90')))
    return SustentoLeido(cod_doc_sustento=cod_doc, num_doc_sustento=(numero or venta.voucher_number_full).replace('-', ''),
                         fecha_emision_doc_sustento=venta.emission_date, num_aut_doc_sustento='', cod_sustento='01',
                         retenciones=tuple(lineas))


def documento_07(empresa, usuario, fecha=None, ruc=RUC_AGENTE, ambiente=2, sec='000000123', **cambios):
    """DocumentoImportado mínimo de un 07 recibido (sin pasar por la lectura de O1)."""
    from core.importacion.models import DocumentoImportado
    fecha = fecha or timezone.localdate()
    clave = clave_acceso_ficticia(fecha, '07', ruc, ambiente, '001', '001', sec)
    datos = dict(importado_por=usuario, origen='xml', clave_acceso=clave, cod_doc='07', version='2.0.0', ambiente=ambiente,
                 estab='001', pto_emi='001', secuencial=sec, numero=f'001-001-{sec}', fecha_emision=fecha, emisor_ruc=ruc,
                 emisor_razon_social='CLIENTE AGENTE DE RETENCIÓN S.A.', clasificacion='recibido', estado_revision='aprobado',
                 estado_verificacion='verificada_sri')
    datos.update(cambios)
    with company_context(empresa):
        return DocumentoImportado.objects.create(**datos)


def retencion_leida(documento, sustentos, ambiente=2, verificado_sri=True, isd=False):
    """RetencionLeida (dataclass de B0) construida a mano, como la entregará O1."""
    sustentos = list(sustentos)
    if isd:
        primero = sustentos[0]
        sustentos[0] = SustentoLeido(primero.cod_doc_sustento, primero.num_doc_sustento, primero.fecha_emision_doc_sustento,
                                     primero.num_aut_doc_sustento, primero.cod_sustento,
                                     primero.retenciones + (RetencionLineaLeida('6', '4580', Decimal('20.00'), Decimal('5.00'),
                                                                                Decimal('1.00')),))
    total = sum((l.valor_retenido for s in sustentos for l in s.retenciones), Decimal('0'))
    return RetencionLeida(documento_id=documento.pk, clave_acceso=documento.clave_acceso, ambiente=ambiente,
                          numero=documento.numero, fecha_emision=documento.fecha_emision,
                          periodo_fiscal=f'{documento.fecha_emision:%m/%Y}', agente_ruc=documento.emisor_ruc,
                          agente_razon_social=documento.emisor_razon_social, version='2.0.0', total_retenido=total,
                          verificado_sri=verificado_sri,
                          estado_verificacion='verificada_sri' if verificado_sri else 'declarada_en_archivo',
                          sustentos=tuple(sustentos))


def recibidos_falsos(monkeypatch):
    """Reemplaza marcar_incorporado y desmarcar_incorporado de O1 (aún NotImplementedError) por dobles que anotan."""
    llamadas = []
    monkeypatch.setattr(recibidos, 'marcar_incorporado',
                        lambda documento, usuario, descripcion: llamadas.append(('marcar', documento.pk, descripcion)))
    monkeypatch.setattr(recibidos, 'desmarcar_incorporado',
                        lambda documento, usuario, motivo: llamadas.append(('desmarcar', documento.pk, motivo)))
    return llamadas


def peticion(usuario, empresa):
    """Petición mínima con el rol de la membresía (para los servicios que reciben `request`)."""
    request = RequestFactory().post('/', REMOTE_ADDR='127.0.0.1')
    request.user = usuario
    request.company = empresa
    request.membership = Membership.objects.select_related('group').get(user=usuario, company=empresa)
    return request
