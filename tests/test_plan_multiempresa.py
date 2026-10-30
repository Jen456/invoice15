"""Plan Multiempresa (suscripción): un pago de la empresa titular cubre hasta 10 RUC distintos con documentos ilimitados."""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.pos.models import Company, Sale
from core.suscripciones import servicios as sv
from core.suscripciones.cupo import PlanRequerido, verificar_disponible
from core.suscripciones.models import EmpresaAdicional, Plan, SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ADMIN, ROLE_OWNER, Membership
from tests import helpers

pytestmark = pytest.mark.django_db

RUCS = ["0990000001001", "0990000002001", "0990000003001", "0990000004001", "0990000005001",
        "0990000006001", "0990000007001", "0990000008001", "0990000009001", "0990000010001"]


def datos(ruc, nombre="ADICIONAL"):
    return {"ruc": ruc, "business_name": f"{nombre} {ruc[-6:]}", "tradename": "", "main_address": "Guayaquil",
            "email": "adicional@example.com", "mobile": "0990000000"}


@pytest.fixture
def titular():
    empresa = helpers.crear_empresa("TITULAR", plan=None)
    helpers.dar_plan(empresa, "multiempresa")
    return empresa


@pytest.fixture
def dueno(titular):
    return helpers.crear_usuario("dueno.multi", titular, ROLE_OWNER)


class TestPlan:

    def test_plan_publicado(self):
        plan = Plan.objects.get(code="multiempresa")
        assert (plan.price_cents, plan.company_limit, plan.document_limit, plan.months, plan.is_active) == (19900, 10, None, 12, True)
        assert plan.multiempresa and [p.code for p in sv.planes_de_pago()] == ["plan-1000", "ilimitado", "multiempresa"]
        assert not Plan.objects.get(code="ilimitado").multiempresa and Plan.objects.get(code="plan-1000").company_limit == 1


class TestCobertura:

    def test_hasta_10_ruc_contando_al_titular(self, titular, dueno):
        periodo = sv.periodo_vigente(titular)
        empresas = [sv.agregar_empresa(titular, dueno, datos(r)) for r in RUCS[:9]]
        for empresa in empresas:
            assert sv.periodo_vigente(empresa) == periodo
            estado = sv.estado_empresa(empresa)
            assert estado.codigo == "activa" and estado.titular == titular and estado.periodo.plan.code == "multiempresa"
            assert Membership.objects.filter(user=dueno, company=empresa, group__name=ROLE_OWNER).exists()
        with pytest.raises(sv.ReglaPlan, match="cubre hasta 10 RUC y ya tienes 10"):
            sv.agregar_empresa(titular, dueno, datos(RUCS[9]))
        assert not Company.objects.filter(ruc=RUCS[9]).exists()

    def test_ruc_repetido_o_invalido(self, titular, dueno):
        helpers.crear_empresa("AJENA", plan=None, ruc=RUCS[0])
        with pytest.raises(sv.ReglaPlan, match="ya está registrado"):
            sv.agregar_empresa(titular, dueno, datos(RUCS[0]))
        with pytest.raises(sv.ReglaPlan, match="RUC válido"):
            sv.agregar_empresa(titular, dueno, datos("0912345678"))

    def test_sin_multiempresa_no_se_agregan_ruc(self, dueno):
        sencilla = helpers.crear_empresa("SENCILLA", plan="ilimitado")
        with pytest.raises(sv.ReglaPlan, match="plan multiempresa vigente"):
            sv.agregar_empresa(sencilla, dueno, datos(RUCS[1]))

    def test_al_vencer_el_titular_las_adicionales_pierden_el_plan(self, titular, dueno):
        adicional = sv.agregar_empresa(titular, dueno, datos(RUCS[2]))
        SubscriptionPeriod.objects.filter(company=titular).update(ends_at=timezone.now() - timedelta(minutes=1))
        assert sv.periodo_vigente(adicional) is None
        estado = sv.estado_empresa(adicional)
        assert estado.titular == titular and not estado.pagado

    def test_plan_propio_tiene_prioridad(self, titular, dueno):
        adicional = sv.agregar_empresa(titular, dueno, datos(RUCS[3]))
        propio = helpers.dar_plan(adicional, "plan-1000")
        assert sv.periodo_vigente(adicional) == propio and sv.estado_empresa(adicional).titular is None

    def test_la_adicional_no_paga_mientras_esta_cubierta(self, titular, dueno):
        adicional = sv.agregar_empresa(titular, dueno, datos(RUCS[4]))
        with pytest.raises(sv.ReglaPlan, match="la gestiona esa empresa titular"):
            sv.modos_de_pago(adicional, Plan.objects.get(code="ilimitado"))

    def test_emite_con_el_plan_del_titular(self, titular, dueno):
        adicional = sv.agregar_empresa(titular, dueno, datos(RUCS[5]))
        Company.objects.filter(pk=adicional.pk).update(environment_type=2)
        adicional.refresh_from_db()
        with company_context(adicional):
            verificar_disponible(Sale(company=adicional, environment_type=2))   # cubierta: sin PlanRequerido

    def test_vincular_una_empresa_que_ya_administra(self, titular, dueno):
        otra = helpers.crear_empresa("PROPIA", plan=None)
        Membership.objects.create(user=dueno, company=otra, group=Membership.objects.filter(user=dueno).first().group)
        assert list(sv.empresas_vinculables(titular, dueno)) == [otra]
        sv.vincular_empresa(titular, dueno, otra)
        assert sv.estado_empresa(otra).titular == titular
        ajena = helpers.crear_empresa("AJENA2", plan=None)
        with pytest.raises(sv.ReglaPlan, match="Solo puedes agregar empresas que administras"):
            sv.vincular_empresa(titular, dueno, ajena)


class TestCambioDePlan:

    def test_de_plan_1000_a_multiempresa_empieza_un_ano_nuevo(self, dueno):
        empresa = helpers.crear_empresa("CAMBIO", plan="plan-1000")
        anterior = sv.periodo_vigente(empresa)
        multi = Plan.objects.get(code="multiempresa")
        assert sv.modos_de_pago(empresa, multi) == ["inmediato"]
        pago, periodo = sv.activar_manual(empresa, multi, dueno, "inmediato", "cambio a multiempresa")
        anterior.refresh_from_db()
        assert anterior.status == "reemplazada" and periodo.plan == multi and periodo.status == "activa"
        assert periodo.starts_at <= timezone.now() < periodo.ends_at and (periodo.ends_at - periodo.starts_at).days >= 365
        assert (pago.amount_cents, pago.base_cents + pago.iva_cents) == (19900, 19900)

    def test_del_multiempresa_a_un_ruc_es_al_vencer(self, titular):
        assert sv.modos_de_pago(titular, Plan.objects.get(code="ilimitado")) == ["programado"]


class TestPantallas:

    def test_plan_y_pagos_muestra_tres_planes_y_el_cambio(self, client):
        empresa = helpers.crear_empresa("TRES", plan="plan-1000")
        helpers.iniciar_sesion(client, helpers.crear_usuario("dueno.tres", empresa), empresa=empresa)
        html = client.get("/suscripcion/").content.decode()
        assert "Plan anual para 1 RUC" in html and "Hasta 10 RUC distintos" in html
        assert "Cambiar a Plan Multiempresa por $199.00" in html and "Mejorar por $35.00" in html

    def test_titular_agrega_empresa_desde_la_app(self, client, titular, dueno):
        helpers.iniciar_sesion(client, dueno, empresa=titular)
        assert "RUC en tu plan: <strong>1 de 10</strong>" in client.get("/suscripcion/").content.decode()
        respuesta = client.post("/suscripcion/empresas/", {"accion": "nueva", **datos(RUCS[6])}, follow=True)
        html = respuesta.content.decode()
        assert html.count("ya está incluida en tu plan") == 1 and "RUC en tu plan: 2 de 10" in html   # una sola vez
        nueva = Company.objects.get(ruc=RUCS[6])
        assert EmpresaAdicional.objects.filter(titular=titular, company=nueva).exists()
        # En la empresa nueva: incluida, sin botones de pago, y puede entrar a ventas (ruta de pago).
        client.post("/empresas/cambiar/", {"company": nueva.id})
        html = client.get("/suscripcion/").content.decode()
        assert "Esta empresa está incluida en el" in html and "suscripcion/pagar" not in html
        assert client.get("/pos/sale/admin/").status_code == 200

    def test_solo_el_propietario_agrega(self, client, titular):
        administrador = helpers.crear_usuario("admin.multi", titular, ROLE_ADMIN)
        helpers.iniciar_sesion(client, administrador, empresa=titular)
        client.post("/suscripcion/empresas/", {"accion": "nueva", **datos(RUCS[7])})
        assert not Company.objects.filter(ruc=RUCS[7]).exists()
