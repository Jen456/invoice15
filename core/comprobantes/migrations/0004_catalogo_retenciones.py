"""Catálogo inicial de códigos de retención (renta residentes e IVA) vigente a octubre de 2026.

Fuentes: Catálogo ATS del SRI actualizado el 06/08/2026 (tabla 3.10) con los porcentajes de la
Res. NAC-DGERCGC26-00000009, y tablas 20 y 23 de la ficha técnica offline v2.34 con la Res. NAC-DGERCGC20-00000061.
No se cargan los códigos de pagos al exterior (5xx). Quedan inactivos los que piden nodos que el sistema aún no genera
(dividendos, banano, autorretenciones) y los de IVA sin caso general vigente. La plataforma los edita en su administración.
"""
from django.db import migrations

# (impuesto, código, concepto, porcentaje, porcentaje editable, común, activo, fuente, orden)
CATALOGO = (
    ('1', '303', 'Honorarios profesionales y demás pagos por servicios relacionados con el título profesional', '10.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 0),
    ('1', '303A', 'Servicios profesionales prestados por sociedades residentes', '5.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 1),
    ('1', '304', 'Servicios predomina el intelecto no relacionados con el título profesional', '10.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 2),
    ('1', '304A', 'Comisiones y demás pagos por servicios predomina intelecto no relacionados con el título profesional', '10.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 3),
    ('1', '304B', 'Pagos a notarios y registradores de la propiedad y mercantil por sus actividades ejercidas como tales', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 4),
    ('1', '304C', 'Pagos a deportistas, entrenadores, árbitros, miembros del cuerpo técnico por sus actividades ejercidas como tales', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 5),
    ('1', '304D', 'Pagos a artistas por sus actividades ejercidas como tales', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 6),
    ('1', '304E', 'Honorarios y demás pagos por servicios de docencia', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 7),
    ('1', '307', 'Servicios predomina la mano de obra', '3.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 8),
    ('1', '308', 'Utilización o aprovechamiento de la imagen o renombre (personas naturales, sociedades," influencers")', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 9),
    ('1', '309', 'Servicios prestados por medios de comunicación y agencias de publicidad', '3.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 10),
    ('1', '310', 'Servicio de transporte privado de pasajeros o transporte público o privado de carga', '1.00', True, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 11),
    ('1', '311', 'Pagos a través de liquidación de compra (nivel cultural o rusticidad)', '3.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 12),
    ('1', '312', 'Transferencia de bienes muebles de naturaleza corporal', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 13),
    ('1', '312A', 'COMPRAS AL PRODUCTOR: de bienes de origen bioacuático, forestal y los descritos el art.27.1 de LRTI', '1.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 14),
    ('1', '312C', 'COMPRAS AL COMERCIALIZADOR: de bienes de origen bioacuático, forestal y los descritos el art.27.1 de LRTI', '1.75', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 15),
    ('1', '314A', 'Regalías por concepto de franquicias de acuerdo al Código INGENIOS (COESCCI) - pago a personas naturales', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 16),
    ('1', '314B', 'Cánones, derechos de autor, marcas, patentes y similares de acuerdo al Código INGENIOS (COESCCI) – pago a personas naturales', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 17),
    ('1', '314C', 'Regalías por concepto de franquicias de acuerdo al Código INGENIOS (COESCCI) - pago a sociades', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 18),
    ('1', '314D', 'Cánones, derechos de autor, marcas, patentes y similares de acuerdo al Código INGENIOS (COESCCI)', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 19),
    ('1', '319', 'Cuotas de arrendamiento mercantil (prestado por sociedades), inclusive la de opción de compra', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 20),
    ('1', '320', 'Arrendamiento bienes inmuebles', '10.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 21),
    ('1', '322', 'Seguros y reaseguros (primas y cesiones)', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 22),
    ('1', '323', 'Rendimientos financieros pagados a naturales y sociedades (No a IFIs)', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 23),
    ('1', '323A', 'Rendimientos financieros depósitos Cta. Corriente', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 24),
    ('1', '323B1', 'Rendimientos financieros depósitos Cta. Ahorros Sociedades', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 25),
    ('1', '323E', 'Rendimientos financieros depósito a plazo fijo gravados', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 26),
    ('1', '323E2', 'Rendimientos financieros depósito a plazo fijo exentos', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 27),
    ('1', '323F', 'Rendimientos financieros operaciones de reporto - repos', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 28),
    ('1', '323G', 'Inversiones (captaciones) rendimientos distintos de aquellos pagados a IFIs', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 29),
    ('1', '323H', 'Rendimientos financieros obligaciones', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 30),
    ('1', '323I', 'Rendimientos financieros bonos convertible en acciones', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 31),
    ('1', '323M', 'Rendimientos financieros : Inversiones en títulos valores en renta fija gravados', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 32),
    ('1', '323N', 'Rendimientos financieros Inversiones en títulos valores en renta fija exentos', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 33),
    ('1', '323O', 'Intereses y demás rendimientos financieros pagados a bancos y otras entidades sometidas al control de la Superintendencia de Bancos y de la Economía Popular y Solidaria', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 34),
    ('1', '323P', 'Intereses pagados por entidades del sector público a favor de sujetos pasivos', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 35),
    ('1', '323Q', 'Otros intereses y rendimientos financieros gravados', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 36),
    ('1', '323R', 'Otros intereses y rendimientos financieros exentos', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 37),
    ('1', '323S', 'Pagos y créditos en cuenta efectuados por el BCE y los depósitos centralizados de valores, en calidad de intermediarios, a instituciones del sistema financiero por cuenta de otras personas naturales y sociedades', '3.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 38),
    ('1', '323T', 'Rendimientos financieros originados en la deuda pública ecuatoriana', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 39),
    ('1', '323U', 'Rendimientos financieros originados en títulos valores de obligaciones de 360 días o más para el financiamiento de proyectos públicos en asociación público-privada', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 40),
    ('1', '324A', 'Intereses en operaciones de crédito entre instituciones del sistema financiero y entidades economía popular y solidaria.', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 41),
    ('1', '324B', 'Inversiones entre instituciones del sistema financiero y entidades economía popular y solidaria', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 42),
    ('1', '324C', 'Pagos y créditos en cuenta efectuados por el BCE y los depósitos centralizados de valores, en calidad de intermediarios, a instituciones del sistema financiero por cuenta de otras instituciones del sistema financiero', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 43),
    ('1', '325', 'Anticipo dividendos', '25.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 44),
    ('1', '325A', 'Préstamos accionistas, beneficiarios o partícipes residentes o establecidos en el Ecuador', '25.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 45),
    ('1', '3250', 'Dividendos exentos (por no llegar a franja exenta o beneficio de otras leyes)', '0.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 46),
    ('1', '326', 'Dividendos distribuidos que correspondan al impuesto a la renta único establecido en el art. 27 de la LRTI', '12.00', True, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 47),
    ('1', '327', 'Dividendos distribuidos a personas naturales residentes', '12.00', True, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 48),
    ('1', '328', 'Dividendos distribuidos a sociedades residentes', '0.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 49),
    ('1', '329', 'Dividendos distribuidos a fideicomisos residentes', '0.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 50),
    ('1', '331', 'Dividendos en acciones (capitalización de utilidades)', '0.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 51),
    ('1', '332', 'Otras compras de bienes y servicios no sujetas a retención (incluye régimen RIMPE - Negocios Populares, para este caso aplica con cualquier forma de pago inclusive los pagos que deban realizar las tarjetas de crédito/débito)', '0.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 52),
    ('1', '332B', 'Compra de bienes inmuebles', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 53),
    ('1', '332C', 'Transporte público de pasajeros', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 54),
    ('1', '332D', 'Pagos en el país por transporte de pasajeros o transporte internacional de carga, a compañías nacionales o extranjeras de aviación o marítimas', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 55),
    ('1', '332E', 'Valores entregados por las cooperativas de transporte a sus socios', '0.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 56),
    ('1', '332F', 'Compraventa de divisas distintas al dólar de los Estados Unidos de América', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 57),
    ('1', '332G', 'Pagos con tarjeta de crédito', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 58),
    ('1', '332H', 'Pago al exterior tarjeta de crédito reportada por la Emisora de tarjeta de crédito, solo recap', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 59),
    ('1', '332I', 'Pago a través de convenio de debito (Clientes IFI`s)', '0.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 60),
    ('1', '333', 'Ganancia en la enajenación de derechos representativos de capital u otros derechos que permitan la exploración, explotación, concesión o similares de sociedades, que se coticen en bolsa de valores del Ecuador', '10.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 61),
    ('1', '334', 'Contraprestación producida por la enajenación de derechos representativos de capital u otros derechos que permitan la exploración, explotación, concesión o similares de sociedades, no cotizados en bolsa de valores del Ecuador', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 62),
    ('1', '335', 'Loterías, rifas, pronósticos deportivos, apuestas y similares', '15.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 63),
    ('1', '336', 'Venta de combustibles a comercializadoras', '0.20', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 64),
    ('1', '337', 'Venta de combustibles a distribuidores', '0.30', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 65),
    ('1', '338', 'Producción y venta local de banano producido o no por el mismo sujeto pasivo', '1.00', True, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 66),
    ('1', '340', 'Impuesto único a la exportación de banano', '3.00', False, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 67),
    ('1', '343', 'Otras retenciones aplicables el 1% (incluye régimen RIMPE - Emprendedores, para este caso aplica con cualquier forma de pago inclusive los pagos que deban realizar las tarjetas de crédito/débito)', '1.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 68),
    ('1', '343A', 'Energía eléctrica', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 69),
    ('1', '343B', 'Actividades de construcción de obra material inmueble, urbanización, lotización o actividades similares', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 70),
    ('1', '343C', 'Recepción de botellas plásticas no retornables de PET', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 71),
    ('1', '3440', 'Otras retenciones aplicables el 3% (incluye pago utilidades a extrabajadores)', '3.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 72),
    ('1', '344A', 'Pago local tarjeta de crédito /débito reportada por la Emisora de tarjeta de crédito / entidades del sistema financiero/sistemas auxiliares de pago', '2.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 73),
    ('1', '344B', 'Adquisición de sustancias minerales dentro del territorio nacional', '2.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 74),
    ('1', '346', 'Otras retenciones aplicables a otros porcentajes', '0.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 75),
    ('1', '346A', 'Otras ganancias de capital distintas de enajenación de derechos representativos de capital', '0.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 76),
    ('1', '346B', 'Donaciones en dinero -Impuesto a las donaciones', '36.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 77),
    ('1', '346C', 'Retención a cargo del propio sujeto pasivo por la producción y/o comercialización de minerales y otros bienes', '0.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 78),
    ('1', '346D', 'Retención a cargo del propio sujeto pasivo por la comercialización de productos forestales', '0.00', True, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 79),
    ('1', '350', 'Otras autorretenciones (inciso 1 y 2 Art.92.1 RLRTI)', '1.50', True, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 80),
    ('1', '3480', 'Impuesto a la renta único sobre los ingresos percibidos por los operadores de pronósticos deportivos', '15.00', False, False, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 81),
    ('1', '3481', 'Autorretenciones Sociedades Grandes Contribuyentes', '24.00', True, False, False, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 82),
    ('1', '3482', 'Comisiones a sociedades, nacionales o extranjeras residentes y establecimientos permanentes domiciliados en el país', '5.00', False, True, True, 'Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)', 83),
    ('2', '9', 'Contribuyente especial que compra BIENES a otro contribuyente especial; emisoras de tarjetas a afiliados CE por bienes', '10.00', False, False, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 0),
    ('2', '10', 'Contribuyente especial que compra SERVICIOS/derechos/comisiones/consultoría a otro contribuyente especial; tarjetas a afiliados CE por servicios', '20.00', False, False, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 1),
    ('2', '1', 'Transferencia de BIENES gravados; contratos de construcción (siempre 30%)', '30.00', False, True, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 2),
    ('2', '11', 'Código vigente en la ficha (Tabla 20) y catálogo ATS desde 2016; la Res. NAC-DGERCGC20-00000061 no fija hoy ningún caso general al 50%', '50.00', False, False, False, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 3),
    ('2', '2', 'SERVICIOS y derechos, comisiones por intermediación, contratos de consultoría', '70.00', False, True, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 4),
    ('2', '3', 'Servicios profesionales de personas naturales con título (salvo consultoría), arriendo de inmuebles a PN no obligadas a contabilidad, LIQUIDACIONES DE COMPRA, dietas a directorios, cuerpos colegiados de elección popular, importación de servicios, exportadores habituales AR/CE', '100.00', False, True, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 5),
    ('2', '7', "Retención en cero (ficha: 'Aplica de conformidad con la Disposición Transitoria Única de la Resolución NAC-DGERCGC15-00000284', resolución derogada por la 20-00000061)", '0.00', False, False, False, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 6),
    ('2', '8', 'No procede retención de IVA (p. ej. proveedor contribuyente especial comprado por agente no CE, Estado, RIMPE emprendedor pagado por medio electrónico, etc.)', '0.00', False, True, True, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 7),
    ('2', '4', 'Caso específico', '12.00', False, False, False, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 8),
    ('2', '5', 'Caso específico', '100.00', False, False, False, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 9),
    ('2', '6', 'Caso específico', '100.00', False, False, False, 'Ficha técnica offline v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061', 10),
)


def cargar(apps, schema_editor):
    CodigoRetencion = apps.get_model('comprobantes', 'CodigoRetencion')
    for impuesto, codigo, concepto, porcentaje, editable, comun, activo, fuente, orden in CATALOGO:
        CodigoRetencion.objects.update_or_create(impuesto=impuesto, codigo=codigo, defaults=dict(
            concepto=concepto, porcentaje=porcentaje, porcentaje_editable=editable, comun=comun, activo=activo,
            fuente=fuente, orden=orden))


class Migration(migrations.Migration):
    dependencies = [('comprobantes', '0003_modulo_retenciones')]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]

