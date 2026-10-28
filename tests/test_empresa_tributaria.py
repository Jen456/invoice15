"""Datos tributarios de la empresa y calendario de vencimientos (Etapa 2, O2): campos sin indicar por defecto,
contribuyente especial, días por noveno dígito, paso al siguiente día hábil, 104 semestral y contribuyente especial sin
confirmar, 104 con la periodicidad sugerida (sin guardarla), 103 solo para agentes o si emitió retenciones, y sugerencias.
El formulario y la pantalla de Empresa se prueban con su vista en el paso siguiente."""
from datetime import date

import pytest

from core.comprobantes.models import Retencion
from core.pos import calendario_sri as cal
from core.pos.models import Company
from core.tenancy.context import company_context
from tests import helpers

pytestmark = pytest.mark.django_db


def ruc_con_noveno(digito, tercero='9'):
    """RUC de sociedad válido ('09' + tercer dígito 9 + … + 9.º dígito + '001')."""
    return f'09{tercero}00000{digito}0001'


class TestEmpresa:

    def test_campos_nuevos_sin_indicar(self, empresa):
        empresa.refresh_from_db()
        assert (empresa.tipo_contribuyente, empresa.periodicidad_iva) == ('', '')
        assert empresa.datos_tributarios_faltantes == ['tipo_contribuyente', 'periodicidad_iva']
        empresa.tipo_contribuyente = 'sociedad'
        assert empresa.datos_tributarios_faltantes == ['periodicidad_iva']
        assert 'tipo_contribuyente' in empresa.toJSON() and empresa.toJSON()['periodicidad_iva'] == ''

    @pytest.mark.parametrize('valor, especial', [('', False), ('000', False), (' 000 ', False), (None, False),
                                                 ('12345', True), ('5368', True)])
    def test_contribuyente_especial(self, valor, especial):
        assert Company(special_taxpayer=valor).es_contribuyente_especial is especial


class TestCalendario:

    @pytest.mark.parametrize('digito, dia', sorted(cal.DIA_POR_NOVENO_DIGITO.items()))
    def test_dia_por_noveno_digito(self, digito, dia):
        ruc = ruc_con_noveno(digito)
        assert ruc[8] == digito and cal.noveno_digito(ruc) == digito and cal.dia_de_vencimiento(ruc) == dia

    def test_ejemplos_de_la_norma(self):
        octubre = cal.vencimiento_104(ruc_con_noveno('1'), 'mensual', 2026, 10)
        assert (octubre.periodo, octubre.desde, octubre.hasta) == ('2026-10', date(2026, 10, 1), date(2026, 10, 31))
        assert octubre.fecha_nominal == octubre.fecha_limite == date(2026, 11, 10) and octubre.fecha_limite.weekday() == 1
        assert octubre.confirmado is True and octubre.feriados_cargados is False
        assert octubre.nota == 'Si la fecha cae en feriado nacional, el plazo pasa al siguiente día hábil.'
        noviembre = cal.vencimiento_103(ruc_con_noveno('2'), 2026, 11)
        assert noviembre.obligacion == '103' and noviembre.fecha_nominal == date(2026, 12, 12)      # sábado
        assert noviembre.fecha_limite == date(2026, 12, 14)                                         # lunes
        con_feriado = cal.vencimiento_103(ruc_con_noveno('2'), 2026, 11, feriados=(date(2026, 12, 14),))
        assert con_feriado.fecha_limite == date(2026, 12, 15) and con_feriado.feriados_cargados is True and con_feriado.nota == ''
        diciembre = cal.vencimiento_104(ruc_con_noveno('0'), 'mensual', 2026, 12)
        assert diciembre.fecha_nominal == date(2027, 1, 28)
        assert cal.siguiente_dia_habil(date(2026, 10, 31)) == date(2026, 11, 2)
        assert cal.FERIADOS_NACIONALES == {}

    def test_semestral_y_especial_sin_confirmar(self):
        s1 = cal.vencimiento_104(ruc_con_noveno('3'), 'semestral', 2026, 'S1')
        assert (s1.periodo, s1.desde, s1.hasta, s1.fecha_nominal) == ('2026-S1', date(2026, 1, 1), date(2026, 6, 30),
                                                                      date(2026, 7, 14))
        assert s1.confirmado is False and s1.nota.startswith(cal.NOTA_SEMESTRAL)
        s2 = cal.vencimiento_104(ruc_con_noveno('3'), 'semestral', 2026, 'S2')
        assert s2.fecha_nominal == date(2027, 1, 14) and s2.hasta == date(2026, 12, 31)
        especial = cal.vencimiento_104(ruc_con_noveno('1'), 'mensual', 2026, 10, especial=True)
        assert especial.confirmado is False and 'Contribuyente especial: confirma tu plazo.' in especial.nota
        with pytest.raises(ValueError):
            cal.vencimiento_104(ruc_con_noveno('1'), 'trimestral', 2026, 1)
        with pytest.raises(ValueError):
            cal.vencimiento_104(ruc_con_noveno('1'), 'mensual', 2026, 13)

    @pytest.mark.parametrize('ruc', ['0990000000000', '123', '', '0912345678001'])
    def test_ruc_invalido(self, ruc):
        with pytest.raises(ValueError, match='RUC inválido'):
            cal.noveno_digito(ruc)


class TestVencimientosDeEmpresa:

    def empresa(self, **datos):
        datos.setdefault('ruc', ruc_con_noveno('1'))
        return helpers.crear_empresa('CALENDARIO', **datos)

    def test_mensual_guardada(self):
        company = self.empresa(periodicidad_iva='mensual', tipo_contribuyente='sociedad', special_taxpayer='')
        vencimientos = cal.vencimientos_de_empresa(company, date(2026, 11, 1), date(2027, 1, 31))
        assert [(v.obligacion, v.periodo, v.fecha_limite, v.confirmado) for v in vencimientos] == [
            ('104', '2026-10', date(2026, 11, 10), True), ('104', '2026-11', date(2026, 12, 10), True),
            ('104', '2026-12', date(2027, 1, 11), True)]          # 10/01/2027 es domingo

    def test_sin_periodicidad_usa_la_sugerida_sin_guardarla(self):
        company = self.empresa(rimpe='emprendedor')
        [s2] = cal.vencimientos_de_empresa(company, date(2027, 1, 1), date(2027, 1, 31))
        assert (s2.periodo, s2.confirmado) == ('2026-S2', False)
        assert s2.nota.startswith('Periodicidad sugerida (semestral): complétala en Empresa.')
        company.refresh_from_db()
        assert company.periodicidad_iva == '' and company.tipo_contribuyente == ''
        mensual = self.empresa()
        v = cal.vencimientos_de_empresa(mensual, date(2026, 11, 1), date(2026, 11, 30))
        assert [(x.periodo, x.confirmado) for x in v] == [('2026-10', False)] and 'Periodicidad sugerida (mensual)' in v[0].nota

    def test_contribuyente_especial_no_confirmado(self):
        for valor, confirmado in (('', True), ('000', True), (' 000 ', True), ('12345', False)):
            company = self.empresa(periodicidad_iva='mensual', special_taxpayer=valor)
            [v] = cal.vencimientos_de_empresa(company, date(2026, 11, 1), date(2026, 11, 30))
            assert v.confirmado is confirmado, valor

    def test_103_solo_si_es_agente_o_emitio_retenciones(self, admin):
        normal = self.empresa(periodicidad_iva='mensual')
        assert {v.obligacion for v in cal.vencimientos_de_empresa(normal, date(2026, 11, 1), date(2026, 11, 30))} == {'104'}
        agente = self.empresa(periodicidad_iva='mensual', retention_agent='SI')
        assert [v.obligacion for v in cal.vencimientos_de_empresa(agente, date(2026, 11, 1), date(2026, 11, 30))] == ['103', '104']
        emisora = self.empresa(periodicidad_iva='mensual')
        helpers.configurar_facturacion(emisora)
        with company_context(emisora):
            from core.pos.models import Provider, Purchase, Receipt
            receipt = Receipt.objects.get(voucher_type='01')
            proveedor = Provider.objects.create(name='PROVEEDOR', ruc='0990000001001', mobile='0990000000',
                                                email='p@example.com', address='X')
            compra = Purchase.objects.create(number='1', provider=proveedor)
            ret = Retencion.objects.create(receipt=receipt, voucher_number='000000001', voucher_number_full='001-001-000000001',
                                           employee=admin, environment_type=2, status='authorized',
                                           emission_date=date(2026, 10, 15), purchase=compra, provider=proveedor,
                                           tipo_identificacion='04', identificacion='0990000001001', razon_social='PROVEEDOR',
                                           num_doc_sustento='001001000000001', fecha_doc_sustento=date(2026, 10, 1),
                                           aut_doc_sustento='1' * 10)
        assert [v.obligacion for v in cal.vencimientos_de_empresa(emisora, date(2026, 11, 1), date(2026, 11, 30))] == ['103', '104']
        with company_context(emisora):
            Retencion.objects.filter(pk=ret.pk).update(anulado_sri_fecha=date(2026, 10, 20))
        assert [v.obligacion for v in cal.vencimientos_de_empresa(emisora, date(2026, 11, 1), date(2026, 11, 30))] == ['104']

    def test_ruc_invalido_de_la_empresa(self):
        with pytest.raises(ValueError, match='RUC inválido'):
            cal.vencimientos_de_empresa(helpers.crear_empresa('RUC MALO', ruc='0990000000000'), date(2026, 11, 1),
                                        date(2026, 11, 30))


class TestSugerencias:

    @pytest.mark.parametrize('ruc, obligado, codigo', [
        ('0990000001001', 'NO', 'sociedad'), ('1760000000001', 'NO', 'sociedad'), ('0960000000001', 'NO', 'sociedad'),
        ('0912345675001', 'SI', 'pn_obligada'), ('0912345675001', 'NO', 'pn_no_obligada'), ('12', 'NO', ''),
    ])
    def test_tipo_de_contribuyente(self, ruc, obligado, codigo):
        sugerido, motivo = cal.sugerir_tipo_contribuyente(Company(ruc=ruc, obligated_accounting=obligado))
        assert sugerido == codigo and motivo
        if codigo == 'sociedad':
            assert motivo == 'RUC de sociedad o entidad pública'

    @pytest.mark.parametrize('agente, rimpe, codigo', [('SI', 'emprendedor', 'mensual'), ('NO', 'emprendedor', 'semestral'),
                                                       ('NO', 'negocio_popular', 'semestral'), ('NO', '', 'mensual')])
    def test_periodicidad(self, agente, rimpe, codigo):
        assert cal.sugerir_periodicidad_iva(Company(retention_agent=agente, rimpe=rimpe))[0] == codigo
