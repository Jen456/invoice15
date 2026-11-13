# Convertir en factura (primera entrega)

13/11/2026 · Rama `fase/pe-convertir-factura`, sobre `96d39e1` (= producción `e0f2902` más documentación). Sin publicar.

Criterio de la propietaria: «Convertir en factura» carga cliente, líneas, cantidades, precios, descuentos, notas y forma de
pago en un borrador; permite revisar el IVA por línea sin cambiar el catálogo; conserva el vínculo con la proforma y evita
duplicados; la emisión al SRI es una acción explícita; el PDF de la proforma puede ocultar al vendedor sin perder quién la
preparó (§1, §3, §4 y §13 del documento de aceptación).

## Flujo

1. **Convertir.** En la lista y en la ficha, una proforma enviada y vigente, o aceptada, muestra «Convertir en factura»
   (código de acción `facturar`, como antes). El botón hace `POST /proformas/` con `action=convertir`. El servidor bloquea
   la proforma, comprueba que se puede facturar y crea su **factura en borrador** (`BorradorFactura`). Si ya existe, la
   devuelve. Responde `{url, creado, borrador_id, mensaje}` y el navegador abre `url`.
2. **Qué copia.**
   - El cliente, o los datos del prospecto.
   - Las líneas, con la cantidad, el precio y el descuento de la proforma y la tarifa de IVA actual del producto. Se
     aplican las reglas de siempre: no se cargan los productos eliminados ni los que no tienen stock, y si hay menos stock
     que lo cotizado se carga lo que hay, con aviso.
   - La forma de pago del SRI, el medio («Transferencia bancaria»…) y la condición «Contado».
   - En la información adicional, «Proforma: PRO-…» y las condiciones como «Notas». Este campo admite 300 caracteres y
     ningún salto de línea, como `<campoAdicional>`; si el texto se recorta, la pantalla lo avisa.
   - Se audita `proforma_convertida`.
3. **Revisar.** `/pos/sale/admin/add/?borrador=<id>` abre la venta de siempre con el borrador. Ahí se revisan el
   cliente, las cantidades, los precios, los descuentos, el pago y la información adicional. Cada línea tiene un selector
   «IVA» que vale **solo para esta factura**: al cambiarlo se recalculan los totales. «Guardar borrador» guarda los
   cambios sin emitir y «Descartar borrador» lo borra. `?proforma=<id>` sigue abriendo la precarga de solo lectura de
   antes, pero si la proforma ya tiene un borrador lleva a ese borrador.
4. **Emitir.** «Emitir factura» envía el `POST action=add` de siempre, con `proforma_id` y `borrador_id`. La transacción
   es la de hoy: proforma, luego número, venta, firma (`emision.preparar`) y `marcar_facturada`, que además borra el
   borrador. Después se envía al SRI (`emitir_con_cupo`). Es la **única** acción que firma o envía: convertir, abrir,
   guardar y descartar no llaman a `preparar`, a `emitir` ni a la firma.
5. **Después.** La proforma queda «facturada». La ficha dice «Ya facturada con la factura N», con un enlace directo a esa
   factura (`venta.url_factura`): el RIDE si está autorizada y, si no, el comprobante impreso. Convertir otra vez responde
   409 «ya se facturó con la factura N». Si la factura se elimina (solo cuando no salió al SRI),
   `liberar_por_venta_eliminada` devuelve la proforma a «aceptada» o «enviada», como siempre, y se puede convertir de
   nuevo.

## Decisiones

- **El borrador es una tabla aparte, no una `Sale` sin número.** `Sale` exige número y secuencia (restricción única) y la
  usan el ATS, los libros, las cuentas por cobrar, el kardex y los listados. Una venta sin número habría tocado todo eso.
  `BorradorFactura` guarda lo que se ve en pantalla; la venta se crea solo al emitir, con el código de siempre.
- **No hay duplicados.** Cada proforma tiene como mucho un borrador, por la restricción `OneToOne`. Además, la conversión
  bloquea antes la proforma (`select_for_update`): dos conversiones a la vez (doble clic, dos pestañas) se ordenan y la
  segunda recibe el mismo borrador. En SQLite, el INSERT que pierde falla y se devuelve el que ganó. Emitir dos veces
  sigue fallando con «ya se facturó» y no gasta número, como hasta ahora.
- **Mientras hay borrador, la proforma no se edita, no se rechaza y no se anula** (409 `con_borrador`): el borrador
  quedaría desfasado. Sí se puede ver, descargar en PDF, duplicar, reenviar y aceptar. La ficha y `acciones[]` ofrecen
  `descartar_borrador`.
- **Descartar libera la proforma.** Se borra el borrador y se audita `proforma_borrador_descartado`. La proforma nunca
  cambió de estado, así que no hay nada que restaurar: vuelven editar, rechazar y anular, y se puede convertir de nuevo.
  Es coherente con `liberar_por_venta_eliminada`.
- **IVA por línea.**
  - La tarifa elegida se guarda en el borrador y luego en `SaleDetail.codigo_porcentaje`, de donde ya salían el XML (por
    línea y `totalConImpuestos`), el RIDE y los totales. `Product` nunca cambia.
  - Cambiarla exige el mismo permiso que cambiar el precio, `change_product` (Propietario y Administrador). Quien no lo
    tiene ve la tarifa y puede emitir la que ya quedó guardada en el borrador, pero no ponerla distinta del catálogo.
  - La venta normal ignora cualquier tarifa que envíe el navegador.
  - `proforma_facturada` añade `borrador_id` y `tarifas_revisadas` (por ejemplo `["C1: 15 % → 0 %"]`) solo cuando se
    emite desde un borrador.
- **Medio de pago.**
  - `Proforma.medio_pago_sugerido` dice cómo se lee el pago en el documento comercial: «Transferencia bancaria» en el PDF
    y en la ficha.
  - El código del SRI sale de `FORMA_PAGO_SRI_DE_MEDIO`, el mapa que ya usaban los cobros: transferencia, depósito y
    cheque dan `20`, «OTROS CON UTILIZACION DEL SISTEMA FINANCIERO» (verificado en `PAYMENT_METHOD`).
  - Al convertir, el medio pasa a `Sale.medio_cobro` y el código a `<formaPago>`.
  - Las proformas anteriores, sin medio, se ven como antes.
- **Ocultar al vendedor: por proforma, no por empresa.**
  - El caso de PRO-000001 viene de una cuenta con acceso a dos empresas que se llama como la otra. La misma empresa puede
    querer mostrar al vendedor en unas proformas y no en otras.
  - Una opción por proforma no toca «Configuración», que comparte pantalla con el diseño de factura, de otra entrega.
  - Se marca en el editor («Ocultar el vendedor en el PDF»), se copia al duplicar y vale para el PDF y su copia por
    correo.
  - `vendedor` y `creada_por` se siguen guardando y se ven en la ficha («Vendedor … oculto en el PDF», «Preparada por»),
    en el JSON y en la auditoría.
  - El emisor del PDF y de la ficha es siempre la empresa de la proforma.

## Qué consume cupo y cuándo

| Acción | Número | Cupo | Stock | SRI |
|---|---|---|---|---|
| Convertir, abrir, guardar o descartar el borrador | no | no | no | no |
| Emitir factura | se reserva en la transacción | `preparar` comprueba el plan y el cupo; `emitir_con_cupo` reserva al enviar, consume si el SRI autoriza y libera si rechaza (en PRUEBAS no descuenta) | baja en la transacción | firma y envía |

- Con el **cupo agotado**, «Convertir en factura» aparece deshabilitado con el aviso del plan y el `POST` responde 403. El
  borrador tampoco se abre, porque la venta está en `RUTAS_DE_EMISION`, pero se puede descartar desde la ficha.
- Con el **plan vencido**, la proforma queda en solo consulta, como ya pasaba.

## Migraciones (aditivas y reversibles)

- `proformas 0004_borrador_factura`:
  - `Proforma.medio_pago_sugerido` y `Proforma.ocultar_vendedor`, con `db_default` (`''` y `False`). Las filas existentes
    no cambian y un INSERT que no las nombre sigue valiendo.
  - La tabla `proformas_borradorfactura`, con la seguridad por filas forzada y la política `fpa_empresa`, como las demás
    tablas de proformas.
  - Depende solo de `proformas 0003`.
- `tenancy 0013_acciones_borrador_factura`: las choices `proforma_convertida` y `proforma_borrador_descartado`.
- **Vuelta:** `migrate proformas 0003_modulo_proformas` (borra los borradores; ninguno salió al SRI) y `migrate tenancy
  0012_accion_diseno_factura`. La vuelta de la fase en `tests/test_migracion_vuelta_fase.py` pasa de 41 a 43 pendientes.
  La vuelta documentada del diseño de factura (`tenancy 0011`) también deshace `tenancy 0013`, y la prueba lo incluye.

## Cómo se verificó

Pruebas nuevas en `tests/test_proformas_borrador.py` (SRI simulado, correo en memoria y datos ficticios):

- `test_convertir_crea_el_borrador_sin_firmar_ni_enviar`: `preparar`, `emitir` y `firmar_xml` sustituidos por funciones
  que fallan; ni número, ni cupo, ni stock, ni SRI.
- `test_el_borrador_lleva_cliente_lineas_precios_descuentos_notas_y_pago`.
- `test_notas_largas_y_prospecto`.
- `test_tres_conceptos_con_iva_revisado_y_transferencia_llegan_a_la_factura`: el caso de §13. El total mostrado, el
  guardado y el `importeTotal` del XML coinciden; la venta siguiente del mismo producto lleva el 15 %.
- `test_vendedor_sin_change_product_no_cambia_la_tarifa_pero_emite_la_revisada`.
- `test_venta_de_siempre_ignora_la_tarifa_del_navegador`.
- `test_convertir_otra_vez_o_doble_clic_abre_el_mismo_borrador`.
- `test_carrera_sin_bloqueo_de_filas_devuelve_el_borrador_que_gano`.
- `test_emitir_factura_es_la_accion_explicita_y_deja_ya_facturada`: el total de 75,24 coincide con cinco tarifas,
  cantidades mayores que 1 y descuentos.
- `test_fallo_al_emitir_conserva_el_borrador`.
- `test_factura_devuelta_eliminada_libera_y_se_convierte_otra_vez`.
- `test_con_borrador_no_se_edita_rechaza_ni_anula_y_descartar_la_libera`.
- `test_descartar_desde_la_venta`.
- `test_transferencia_bancaria_en_la_proforma_y_20_para_el_sri`.
- `test_ocultar_vendedor_con_una_cuenta_de_dos_empresas`: la ficha, el PDF y el adjunto del correo muestran la emisora,
  y el registro interno se conserva.
- Más los casos de estado, permiso y cupo.

En PostgreSQL, `tests/test_zz_proformas_borrador_concurrencia_pg.py` prueba dos cosas, con hilos:

- cuatro conversiones simultáneas dejan un solo borrador;
- descartar mientras otra pestaña emite nunca deja las dos cosas.

Se ajustaron dos pruebas existentes: la etiqueta del botón deshabilitado («Convertir en factura: …») y el conteo de la
vuelta de migraciones.

Resultados, sin la suite completa. La lista de archivos es la nueva más las pruebas de proformas, emisión, líneas e IVA,
alta de producto, auditoría, contratos B0, clientes, configuración de facturación, escapes, factura base, multiempresa,
puntos, recorridos, revisión, suscripciones, orden de líneas, auditoría de ventas, estáticos, RLS genérica y las dos de
concurrencia de proformas:

- `herramientas/pytest_sqlite.sh wt-pe-proforma <26 archivos>`: 472 aprobadas y 13 omitidas (las que solo corren en
  PostgreSQL).
- `herramientas/pytest_pg.sh wt-pe-proforma <los mismos 26>`: 485 aprobadas.
- `test_migracion_vuelta_fase.py` y `test_migracion_proformas.py` (SQLite): 4 aprobadas. `test_migracion_proformas.py`
  también pasa en PostgreSQL, dentro de la corrida anterior, y `test_migracion_vuelta_fase.py` con `pytest_pg.sh`: 2
  aprobadas.
- `manage.py makemigrations --check --dry-run` y `manage.py check` (con `config.settings_test`): sin cambios ni avisos.
- `node --check` de los tres JavaScript tocados: correcto.

## Pendiente

- Probar en un navegador real el selector «IVA» por línea, «Guardar borrador» y «Descartar borrador». El JavaScript solo
  pasó `node --check`.
- Decisiones de la propietaria:
  - si el Vendedor también puede revisar el IVA (hoy exige `change_product`);
  - si quiere, además, un predeterminado por empresa para «Ocultar el vendedor en el PDF».
- El RIDE de la factura sigue mostrando la forma de pago del SRI. Mostrar «Transferencia bancaria» ahí toca las
  plantillas del RIDE, que pertenecen a la entrega del diseño de factura.
- El borrador no guarda la referencia, la nota ni el archivo del cobro: se completan al emitir.
- Una proforma enviada que vence con un borrador pendiente: primero hay que descartar el borrador para cambiar la fecha
  de validez.
- La lista de proformas no muestra el borrador (el JSON de la fila no cambia, por compatibilidad); la ficha sí.
- Actualizar `CONTRATO-PANTALLAS-PROFORMAS.md` con detalle (por ahora solo lleva una nota en el §8).
