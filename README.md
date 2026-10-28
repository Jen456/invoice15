<div align="center">
  <img src="static/img/brand/isotipo-pie.png" alt="Colibrí Ingenioso de FacturaPorAquí" width="88">
  <h1>FacturaPorAquí</h1>
  <p><strong>Tu negocio, en orden.</strong></p>
  <p>Facturación electrónica y gestión empresarial para Ecuador.</p>
  <p>
    <a href="https://facturaporaqui.com">Conocer los planes</a> ·
    <a href="https://app.facturaporaqui.com">Ingresar a la aplicación</a> ·
    <a href="entregas/facturaporaqui/HANDOFF.md">Estado del proyecto</a>
  </p>
</div>

## Qué es FacturaPorAquí

Una plataforma web para gestionar comprobantes electrónicos, clientes, productos, compras, ventas, cobros y pagos. Permite trabajar con varias empresas mediante un selector, roles por empresa y aislamiento de datos.

Este repositorio contiene la aplicación Django, la landing comercial, pruebas, recursos de marca y documentación de desarrollo. **El contenido de una rama puede incluir propuestas aún no publicadas**: consulta [HANDOFF.md](entregas/facturaporaqui/HANDOFF.md) para conocer lo que está en producción.

## Funciones disponibles

| Área | Alcance |
| --- | --- |
| Comprobantes electrónicos | Facturas, notas de crédito, notas de débito, retenciones, liquidaciones de compra y guías de remisión. |
| Configuración de facturación | Asistente para configurar establecimientos, puntos de emisión y numeración. |
| Gestión comercial | Clientes, proveedores, productos, compras, ventas, inventario, cuentas por cobrar y por pagar. |
| Multiempresa | Empresas separadas, membresías, roles y selector de empresa activa. |
| Importación | Recepción y revisión de XML/RIDE; incluida en Ilimitado y Multiempresa. |
| Suscripciones | Planes anuales y pagos mediante PayPhone. |
| Documentos imprimibles | RIDE A4 y ticket térmico; consulta el estado de cada actualización visual en HANDOFF. |

## Planes anuales

Precios en dólares de Estados Unidos, **IVA incluido**.

| Plan | Precio anual | Empresas | Comprobantes | Importación XML/RIDE |
| --- | ---: | --- | --- | --- |
| Plan 1000 | $50 | 1 RUC | Hasta 1000 por año | No incluida |
| Ilimitado | $85 | 1 RUC | Ilimitados | Incluida |
| Multiempresa | $199 | Hasta 10 RUC distintos | Ilimitados | Incluida |

La mejora de Plan 1000 a Ilimitado cuesta **$35** y conserva el vencimiento del período actual: no inicia una nueva anualidad.

### Próximamente

- **Proformas**, incluidas en todos los planes pagados: cotizaciones en PDF y por correo, sin envío al SRI ni consumo del cupo; conversión a factura para revisión.
- **Complemento Contable**, con contratación aparte y **precio por anunciar**: bancos y caja, importación de extractos, conciliación, plan de cuentas, asientos, kardex, libros, balances y estados financieros.
- **Herramientas tributarias** del complemento: preparación de hojas del 104 y del 103, generación de XML del ATS y las etapas de apoyo al 101, ADI y pago a cuenta previstas en el plan.

El contribuyente revisa y presenta su información en **SRI en Línea**. Estas herramientas no se presentan como declaraciones automáticas ni como software homologado o certificado por el SRI.

Consulta el [plan de Proformas, Bancos y Contabilidad](entregas/facturaporaqui/PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md) y las [maquetas de la fase contable](entregas/facturaporaqui/propuestas/fase-contable/README.md). Son propuestas hasta que se confirme su implementación y publicación.

## Tecnología

- **Backend:** Python 3.12 y Django 5.2.
- **Base de datos:** PostgreSQL en el entorno multiempresa; SQLite para pruebas locales compatibles.
- **Interfaz:** plantillas Django, AdminLTE 3.2, Bootstrap 4.6, JavaScript y Chart.js.
- **Documentos:** XML y PDF, con WeasyPrint para impresión.
- **Infraestructura:** scripts de despliegue, servicios y temporizadores systemd; aplicación y landing en dominios separados.

Las bibliotecas de la app se sirven desde `static/lib`. Su inventario se encuentra en [MANIFIESTO.json](static/lib/MANIFIESTO.json); consulta también [DEPENDENCIAS-FRONTEND.md](entregas/facturaporaqui/DEPENDENCIAS-FRONTEND.md).

## Organización del repositorio

```text
core/                         Aplicaciones Django y lógica del negocio
config/                       Configuración y rutas del proyecto
templates/                    Plantillas compartidas y estilos/pie del RIDE
static/                       Tema, JavaScript, marca y bibliotecas locales
landing/                      Sitio comercial independiente
requirements/                 Dependencias fijadas con hashes
tests/                        Pruebas automatizadas
deploy/                       Herramientas de operación y despliegue
entregas/facturaporaqui/       Coordinación, informes, capturas y propuestas
```

### Ramas y coordinación

- **`plataforma`**: desarrollo del backend e integración a cargo de Claude.
- **`frontend/etapa3`**: diseño de la aplicación, marca y propuesta comercial a cargo de Codex.
- **`main`**: conserva la base histórica; no asumir que contiene la última versión operativa.

Antes de trabajar, leer [AGENTS.md](entregas/facturaporaqui/AGENTS.md) y [HANDOFF.md](entregas/facturaporaqui/HANDOFF.md). Integrar los cambios compartidos sin reescribir el historial y registrar cada entrega. Las propuestas de `entregas/` no son módulos desplegados.

## Preparar un entorno de pruebas

Se necesita acceso al repositorio privado, Python 3.12 y las bibliotecas de sistema requeridas por [WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html). Para validar PostgreSQL se requiere además una base dedicada a pruebas.

```bash
git clone --branch frontend/etapa3 https://github.com/Jen456/invoice15.git
cd invoice15
python3.12 -m venv .venv
```

Activar el entorno en Linux/macOS:

```bash
source .venv/bin/activate
```

En PowerShell, después de crear el entorno con Python 3.12:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias de aplicación y pruebas:

```bash
python -m pip install --require-hashes -r requirements/base.txt -r requirements/dev.txt
```

Ejecutar la suite local:

```bash
python -m pytest
```

`pytest.ini` selecciona `config.settings_test`: utiliza SQLite en memoria y correo en memoria. Las pruebas específicas de concurrencia y aislamiento por filas requieren PostgreSQL mediante `FPA_TEST_DATABASE_URL`, apuntando exclusivamente a una base de pruebas. Un resultado en SQLite no sustituye esas verificaciones.

Para una revisión acotada de recursos y rutas:

```bash
python -m pytest tests/test_estaticos.py tests/test_rutas.py
```

Estos pasos preparan **pruebas**, no un servidor de producción. La puesta en marcha de una instancia requiere su configuración de entorno, base de datos y almacenamiento privado. No crear migraciones como paso de instalación ni utilizar usuarios o contraseñas predeterminados.

### Ver la landing y las maquetas

Desde la raíz del repositorio:

```bash
python -m http.server 8031 --bind 127.0.0.1
```

- Landing: <http://localhost:8031/landing/>
- Maquetas contables: <http://localhost:8031/entregas/facturaporaqui/propuestas/fase-contable/>

Las maquetas usan datos ficticios. El formulario de contacto de la landing sigue siendo demostrativo mientras no se configure e integre un destino real; no implica captación persistente de solicitudes.

## Documentación y marca

- [Estado, contratos y pendientes entre agentes](entregas/facturaporaqui/HANDOFF.md).
- [Resultados y verificaciones del frontend](entregas/facturaporaqui/RESULTADOS-FRONTEND.md).
- [Importación de comprobantes](entregas/facturaporaqui/IMPORTACION-COMPROBANTES.md).
- [Plan de la fase contable](entregas/facturaporaqui/PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md).
- [Investigación normativa y puntos por confirmar](entregas/facturaporaqui/NORMA-CONTABLE-TRIBUTARIA-2026-10.md).
- [Propuesta RIDE A4](entregas/facturaporaqui/propuestas/ride-b/README.md) y [ticket térmico](entregas/facturaporaqui/propuestas/ticket-b/README.md).
- [Material comercial de la fase contable](entregas/facturaporaqui/redes/fase-contable/README.md).

La identidad utiliza el **colibrí Ingenioso**, coral `#CA462C`, celeste `#44BADD`, azul claro `#E5F1F6` y azul oscuro `#163B50`. Se priorizan lectura, contraste, foco visible, adaptación móvil y movimiento reducido.

## Publicación y contribuciones

Los procedimientos se mantienen en [desplegar.sh](deploy/scripts/desplegar.sh) y [publicar-landing.sh](deploy/scripts/publicar-landing.sh). La publicación requiere revisión, autorización de la propietaria, respaldo y verificación posterior. Un push a GitHub no equivale a un despliegue.

Trabajar con empresas y documentos ficticios. No incluir credenciales, claves privadas, firmas electrónicas ni datos de clientes en commits, documentación o capturas. Los cambios fiscales y de datos deben coordinarse con el responsable del backend.

Este proyecto evolucionó a partir de Sistema Invoice de AlgoriSoft. Se reconoce ese origen; la marca y las adaptaciones actuales corresponden a FacturaPorAquí. La disponibilidad del repositorio no concede por sí sola una licencia de redistribución: revisar los términos aplicables al proyecto original y a sus dependencias.
