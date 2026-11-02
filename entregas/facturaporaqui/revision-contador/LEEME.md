# Paquete ficticio para la revisión del contador

Generado el 02/11/2026 con el código de `fase/libros-mensuales`. Empresa **ficticia** «EMISORA S.A.», RUC 0900000001001,
mes **10/2026**, con los datos de prueba de `tests/test_libros.py`. No contiene datos reales y no se envió nada al SRI.

Lo pide `CIERRE-Y-SIGUIENTE-ENTREGA.md`: el ATS y los borradores del 104 y del 103 solo se dan por terminados cuando un
contador revise este ejemplo y confirme los criterios marcados «por confirmar». Validar el XML contra el esquema no
equivale a la aceptación del SRI.

## Archivos

| Archivo | Qué es |
|---|---|
| `AT102026.zip`, `AT102026.xml` | ATS del mes, validado contra el `ats.xsd` oficial (huella en `core/tributario/ats.py`) |
| `informe-ats.json` | compras incluidas y excluidas (con sus motivos), advertencias y fuente del esquema |
| `borrador-104.xlsx`, `borrador-104.json` | casilleros calculados, «por confirmar» y documentos de cada uno |
| `borrador-103.xlsx`, `borrador-103.json` | ídem para el 103 |
| `libros.xlsx` | libros del mes: ventas, compras, retenciones efectuadas y recibidas |

## El mes ficticio

- **Ventas:** factura al 15 % (2 × 10.00), factura al 0 % (3 × 4.00), una anulada en el SRI, una en ambiente de pruebas,
  una devuelta por el SRI y una del mes anterior. Nota de crédito por toda la primera factura. Nota de débito de 10.00 más
  IVA sobre la segunda.
- **Compras:** una completa de 100.00 más IVA (sustento 06), con retención de renta código 312 (2 %). Una antigua de 50.00
  sin tarifa registrada, que queda fuera del ATS con sus motivos.

## Preguntas (cada respuesta desbloquea una parte)

**ATS**
1. ¿Las ventas electrónicas van en `ventasEstablecimiento` y `totalVentas`? Hoy no se incluyen.
2. ¿Cómo se reportan los comprobantes electrónicos anulados? Hoy no se incluyen.
3. ¿Confirmas que las retenciones electrónicas no se reportan en compras (valores retenidos en 0.00 y sin `air`)?
4. Pagos al exterior: la aplicación no registra sus datos y esas compras quedan fuera. ¿Hace falta para tus clientes?

**104**
5. Ventas con tarifa 0 %: ¿403/413, 405/415 o 406/416? Depende del derecho a crédito tributario.
6. Notas de crédito del mes: ya restan en el valor neto. ¿Se registran además en 423/424?
7. 480/481: ¿importe bruto o neto, y cómo se reparten las notas de crédito?
8. Compras gravadas: ¿qué códigos de sustento van con crédito (500/510/520), sin crédito (502) o en 540/550/560?
9. Activos fijos: ¿hay que distinguirlos (402/412/422 y 501/511/521)? Hoy no se registran aparte.

**103**
10. Códigos con letra distintos de 303A (por ejemplo 343A y 343B): ¿a qué casillero va cada uno? El Catálogo ATS
    solo trae código, concepto y porcentaje.
11. Pagos al exterior (códigos 5xx y subtotal 498).

**General**
12. ¿El ATS y los borradores de este mes ficticio coinciden con lo que declararías? Si algo no cuadra, indica el casillero
    o el campo.
