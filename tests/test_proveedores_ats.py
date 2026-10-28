"""Proveedores con los datos del ATS (core/pos/proveedores.py, Provider.faltantes_ats y la orden proveedores_incompletos):
validación por tipo, tipo de sujeto derivado, parte relacionada sin valor inicial y completación con decisión escrita."""
import csv
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from core.pos.models import Provider
from core.pos.proveedores import sugerencia, sujeto_de_ruc, validar_proveedor
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests import ayuda_compras as ayuda

CEDULA = ayuda.cedula(4321)


class TestValidacion:

    @pytest.mark.parametrize('tipo, numero, sujeto, esperado', [
        ('04', '0990000001001', '', '02'),           # sociedad privada (tercer dígito 9)
        ('04', '0960000000001', '', '02'),           # entidad pública (tercer dígito 6)
        ('04', CEDULA + '001', '02', '01'),          # persona natural: el sujeto se deriva, no se elige
        ('05', CEDULA, '', '01'),
        ('06', 'AB 123456', '02', '02'),
        ('08', '155652251-2-2017', '01', '01'),
    ])
    def test_tipos_validos_y_sujeto(self, tipo, numero, sujeto, esperado):
        normalizado, tipo_sujeto, errores, _ = validar_proveedor(tipo, numero, sujeto, 'no')
        assert errores == [] and tipo_sujeto == esperado
        assert normalizado == numero.replace(' ', '') if tipo in ('04', '05') else normalizado == numero

    @pytest.mark.parametrize('tipo, numero, campo', [
        ('05', '0912345678', 'ruc'),                  # dígito verificador incorrecto
        ('04', '0912345678001', 'ruc'),
        ('06', '9999999999999', 'tipo_identificacion'),
        ('07', '9999999999999', 'tipo_identificacion'),   # un proveedor no es consumidor final
        ('', '0990000001001', 'tipo_identificacion'),
    ])
    def test_identificaciones_rechazadas(self, tipo, numero, campo):
        _, _, errores, _ = validar_proveedor(tipo, numero, '01', 'no')
        assert campo in [c for c, _ in errores]

    def test_pasaporte_y_exterior_exigen_sujeto_y_parte_relacionada_sin_inicial(self):
        _, _, errores, _ = validar_proveedor('06', 'AB123456', '', None)
        assert ('tipo_sujeto', 'Elige si es persona natural o sociedad') in errores
        assert ('parte_relacionada', 'Indica si es parte relacionada') in errores
        _, _, errores, _ = validar_proveedor('04', '0990000001001', '', '')
        assert errores == [('parte_relacionada', 'Indica si es parte relacionada')]
        assert validar_proveedor('04', '0990000001001', '', False)[2] == []
        assert validar_proveedor('04', '0990000001001', '', 'si')[2] == []

    def test_advertencia_de_14_caracteres_en_el_ats(self):
        _, _, errores, avisos = validar_proveedor('08', 'EXT-1234567890', '02', 'no')
        assert errores == [] and [c for c, _ in avisos] == ['ats_longitud']
        assert validar_proveedor('08', 'EXT-123456789', '02', 'no')[3] == []

    @pytest.mark.parametrize('ruc, sujeto', [('0990000001001', '02'), ('0960000000001', '02'), (CEDULA + '001', '01')])
    def test_sujeto_de_ruc(self, ruc, sujeto):
        assert sujeto_de_ruc(ruc) == sujeto


@pytest.mark.django_db
class TestModelo:

    def test_faltantes_ats_y_datos_completos(self, empresa):
        anterior = ayuda.crear_proveedor(empresa, tipo='')
        assert [c for c, _ in anterior.faltantes_ats()] == ['tipo_identificacion', 'parte_relacionada']
        assert not anterior.datos_completos and anterior.tipo_id_ats == ''
        pasaporte = ayuda.crear_proveedor(empresa, tipo='06', tipo_sujeto='')
        assert [c for c, _ in pasaporte.faltantes_ats()] == ['tipo_sujeto']
        invalido = ayuda.crear_proveedor(empresa, tipo='05', ruc='0912345678')
        assert [c for c, _ in invalido.faltantes_ats()] == ['identificacion_invalida']
        completo = ayuda.crear_proveedor(empresa, tipo='04', parte_relacionada=True)
        assert completo.faltantes_ats() == [] and completo.datos_completos and completo.tipo_id_ats == '01'

    def test_tojson_con_los_datos_del_ats(self, empresa):
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', ruc='0990000001001', nombre='<img src=x onerror=alert(1)>')
        item = proveedor.toJSON()
        assert item['tipo_identificacion'] == {'id': '04', 'name': 'RUC'}
        assert item['tipo_sujeto'] == {'id': '02', 'name': 'Sociedad'} and item['parte_relacionada'] is False
        assert item['tipo_id_ats'] == '01' and item['datos_completos'] is True and item['faltantes'] == []
        assert item['name'] == '<img src=x onerror=alert(1)>' and item['text'].startswith('<img')   # texto, sin interpretar
        anterior = ayuda.crear_proveedor(empresa, tipo='').toJSON()
        assert anterior['parte_relacionada'] is None and anterior['datos_completos'] is False
        assert [f['codigo'] for f in anterior['faltantes']] == ['tipo_identificacion', 'parte_relacionada']

    def test_sugerencia_solo_sin_ambiguedad(self, empresa):
        assert sugerencia(ayuda.crear_proveedor(empresa, tipo='', ruc='0990000001001')) == {
            'tipo_identificacion': '04', 'tipo_sujeto': '02'}
        assert sugerencia(ayuda.crear_proveedor(empresa, tipo='', ruc=CEDULA)) == {'tipo_identificacion': '05', 'tipo_sujeto': '01'}
        assert sugerencia(ayuda.crear_proveedor(empresa, tipo='', ruc='0912345678')) is None       # cédula inválida
        assert sugerencia(ayuda.crear_proveedor(empresa, tipo='', ruc='AB123456')) is None


@pytest.mark.django_db
class TestOrdenProveedoresIncompletos:

    @pytest.fixture
    def proveedores(self, empresa):
        return {'ruc': ayuda.crear_proveedor(empresa, tipo='', ruc='0990000001001'),
                'cedula': ayuda.crear_proveedor(empresa, tipo='', ruc=CEDULA),
                'pasaporte': ayuda.crear_proveedor(empresa, tipo='', ruc='AB123456'),
                'completo': ayuda.crear_proveedor(empresa, tipo='04')}

    def estado(self, empresa):
        return ayuda.en(empresa, lambda: sorted(Provider.objects.values_list('ruc', 'tipo_identificacion', 'tipo_sujeto',
                                                                               'parte_relacionada')))

    def test_ensayo_no_escribe_nada(self, empresa, proveedores, tmp_path):
        antes, auditorias = self.estado(empresa), AuditLog.objects.count()
        salida = StringIO()
        call_command('proveedores_incompletos', '--empresa', str(empresa.pk), '--csv', str(tmp_path / 'p.csv'), stdout=salida)
        assert self.estado(empresa) == antes and AuditLog.objects.count() == auditorias
        assert 'ensayo: no se cambió nada' in salida.getvalue() and '3 proveedores incompletos' in salida.getvalue()
        filas = list(csv.DictReader(open(tmp_path / 'p.csv', encoding='utf-8')))
        assert sorted(f['accion'] for f in filas) == ['se llenaría', 'se llenaría', 'sin cambios: revisar a mano']

    @pytest.mark.parametrize('argumentos, mensaje', [
        (['--aplicar', '--csv', 'x.csv'], '--empresa ID o --todas'),
        (['--todas', '--aplicar', '--csv', 'x.csv'], '--decision'),
        (['--todas', '--aplicar', '--decision', 'corto', '--csv', 'x.csv'], '--decision'),
        (['--todas', '--aplicar', '--decision', 'Autoriza la propietaria el 28/10'], '--csv'),
    ])
    def test_aplicar_exige_empresa_decision_e_informe(self, empresa, proveedores, argumentos, mensaje):
        with pytest.raises(CommandError, match=mensaje):
            call_command('proveedores_incompletos', *argumentos, stdout=StringIO())
        assert ayuda.en(empresa, lambda: Provider.objects.filter(tipo_identificacion='').count()) == 3

    def test_aplicar_llena_solo_lo_inequivoco_y_audita(self, empresa, proveedores, tmp_path):
        informe = tmp_path / 'proveedores.csv'
        decision = 'Autoriza la propietaria (prueba ficticia) el 28/10/2026'
        call_command('proveedores_incompletos', '--empresa', str(empresa.pk), '--aplicar', '--decision', decision,
                     '--csv', str(informe), stdout=StringIO())
        estado = {ruc: (tipo, sujeto, parte) for ruc, tipo, sujeto, parte in self.estado(empresa)}
        assert estado['0990000001001'] == ('04', '02', None)        # nunca la parte relacionada
        assert estado[CEDULA] == ('05', '01', None)
        assert estado['AB123456'] == ('', '', None)                 # ambiguo: a mano
        registro = AuditLog.objects.get(action='provider_type_fill', company=empresa)
        assert registro.detail == {'proveedores': sorted([proveedores['ruc'].pk, proveedores['cedula'].pk]), 'cantidad': 2,
                                   'decision': decision, 'informe': str(informe)}
        assert sorted(f['accion'] for f in csv.DictReader(open(informe, encoding='utf-8'))) == [
            'llenado', 'llenado', 'sin cambios: revisar a mano']


# ---------------------------------------------------------------- formulario y pantallas (paso 2: §6.D)

def _datos_proveedor(**cambios):
    datos = {'name': 'PROVEEDOR DE PANTALLA S.A.', 'tipo_identificacion': '04', 'ruc': '0990000001001', 'tipo_sujeto': '',
             'parte_relacionada': 'no', 'mobile': '0991112233', 'email': 'pantalla@example.com', 'address': 'Av. Ficticia 1'}
    datos.update(cambios)
    return datos


@pytest.mark.django_db
class TestFormulario:

    def formulario(self, empresa, datos, instancia=None):
        from core.pos.forms import ProviderForm
        with company_context(empresa):
            form = ProviderForm(datos, instance=instancia)
            return form, form.is_valid()

    def test_parte_relacionada_sin_valor_inicial_y_obligatoria(self, empresa):
        from core.pos.forms import ProviderForm
        assert ProviderForm()['parte_relacionada'].value() in ('', None)
        form, valido = self.formulario(empresa, _datos_proveedor(parte_relacionada=''))
        assert not valido and form.errors['parte_relacionada'] == ['Indica si es parte relacionada']
        form, valido = self.formulario(empresa, _datos_proveedor(tipo_identificacion=''))
        assert not valido and 'tipo_identificacion' in form.errors

    def test_sujeto_derivado_o_elegido_y_numero_segun_el_tipo(self, empresa):
        form, valido = self.formulario(empresa, _datos_proveedor(tipo_sujeto='01'))
        assert valido and form.cleaned_data['tipo_sujeto'] == '02' and form.cleaned_data['parte_relacionada'] is False
        form, valido = self.formulario(empresa, _datos_proveedor(tipo_identificacion='06', ruc='AB123456'))
        assert not valido and form.errors['tipo_sujeto'] == ['Elige si es persona natural o sociedad']
        form, valido = self.formulario(empresa, _datos_proveedor(tipo_identificacion='05', ruc='0912345678'))
        assert not valido and 'ruc' in form.errors
        form, valido = self.formulario(empresa, _datos_proveedor(tipo_identificacion='08', ruc='EXT-1234567890',
                                                                 tipo_sujeto='01', parte_relacionada='si'))
        assert valido and form.advertencias == [{'codigo': 'ats_longitud',
                                                 'texto': 'El ATS admite hasta 13 caracteres en la identificación del proveedor'}]

    def test_edicion_muestra_lo_guardado(self, empresa):
        from core.pos.forms import ProviderForm
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', parte_relacionada=True)
        assert ProviderForm(instance=proveedor)['parte_relacionada'].value() == 'si'
        anterior = ayuda.crear_proveedor(empresa, tipo='')
        assert ProviderForm(instance=anterior)['parte_relacionada'].value() in ('', None)


@pytest.mark.django_db
class TestPantallas:

    def entrar(self, client, empresa, admin):
        from tests import helpers
        helpers.iniciar_sesion(client, admin, empresa=empresa)

    def test_alta_por_la_pantalla_y_listado_con_insignia(self, client, empresa, admin):
        import json
        anterior = ayuda.crear_proveedor(empresa, tipo='', nombre='<img src=x onerror=alert(1)>')
        self.entrar(client, empresa, admin)
        assert client.get('/pos/provider/add/').status_code == 200
        data = json.loads(client.post('/pos/provider/add/', {**_datos_proveedor(parte_relacionada=''), 'action': 'add'}).content)
        assert 'Indica si es parte relacionada' in json.dumps(data['error'], ensure_ascii=False)
        data = json.loads(client.post('/pos/provider/add/', {**_datos_proveedor(), 'action': 'add'}).content)
        assert data['tipo_sujeto'] == {'id': '02', 'name': 'Sociedad'} and data['datos_completos'] is True
        filas = json.loads(client.post('/pos/provider/', {'action': 'search'}).content)
        fila = next(f for f in filas if f['id'] == anterior.pk)
        assert fila['name'] == '<img src=x onerror=alert(1)>' and fila['datos_completos'] is False
        assert fila['faltantes'][0] == {'codigo': 'tipo_identificacion', 'texto': 'Falta el tipo de identificación'}
        respuesta = client.get(f'/pos/provider/update/{anterior.pk}/')
        assert respuesta.status_code == 200 and respuesta.context['form']['parte_relacionada'].value() in ('', None)

    def test_modal_de_compra_crea_proveedor_completo(self, client, empresa, admin):
        import json
        self.entrar(client, empresa, admin)
        respuesta = client.get('/pos/purchase/add/')
        assert respuesta.context['frmProvider'].auto_id == 'fp_proveedor_%s'
        data = json.loads(client.post('/pos/purchase/add/', {**_datos_proveedor(tipo_identificacion='05', ruc=CEDULA),
                                                             'action': 'create_provider'}).content)
        assert data['datos_completos'] is True and data['tipo_identificacion']['id'] == '05'
        assert data['tipo_sujeto']['id'] == '01' and data['parte_relacionada'] is False and data['text']
        with company_context(empresa):
            assert Provider.objects.get(pk=data['id']).faltantes_ats() == []
        data = json.loads(client.post('/pos/purchase/add/', {'action': 'search_provider', 'term': CEDULA[:6]}).content)
        assert [p['ruc'] for p in data] == [CEDULA]
