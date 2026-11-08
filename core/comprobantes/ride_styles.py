"""Allowed PDF styles and colors. Use validated context values in the RIDE."""
import re

STYLES = {
    "clasico": ("Clásico", "Diseño actual con dos bloques de encabezado.", "#CA462C", "#E5F1F6"),
    "corporativo": ("Corporativo", "Cabecera enmarcada y un bloque fiscal destacado.", "#174886", "#C8DDF4"),
    "minimalista": ("Minimalista", "Fondo blanco y líneas finas.", "#284A45", "#D6ECE4"),
    "banda": ("Banda de marca", "La identidad del comercio encabeza el documento.", "#603D80", "#ECDCF8"),
    "compacto": ("Compacto", "Encabezado corto y tabla de mayor densidad.", "#21635D", "#D6EAE7"),
}
VERSION_PERSONALIZADA = 2
FUENTES = {
    "original": ("Original del sistema", "Arial, Helvetica, sans-serif"),
    "liberation-serif": ("Liberation Serif", '"Liberation Serif", "Times New Roman", serif'),
    "dejavu-sans": ("DejaVu Sans", '"DejaVu Sans", Arial, sans-serif'),
    "dejavu-serif": ("DejaVu Serif", '"DejaVu Serif", Georgia, serif'),
}
MAX_ENCABEZADO = 100
MAX_PIE_COMERCIAL = 180
PROVEEDOR_FIJO = {
    "nombre": "FACTURAPORAQUI",
    "ruc": "0941609729001",
    "email": "soporte@facturaporaqui.com",
    "direccion": "Milagro, Manta y Rumiñahui",
}
DESCRIPCIONES = {
    "clasico": "Plantilla original de FacturaPorAquí. Seleccionada por defecto.",
    "corporativo": "Cabecera enmarcada, franja oscura y tabla de productos con cuadrícula.",
    "minimalista": "Diseño editorial, espacio en blanco y acentos de color discretos.",
    "banda": "Cabecera de marca con cortes diagonales y una tabla de alto contraste.",
    "compacto": "Bloques compactos, filas alternadas y total destacado.",
}
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")


def clean_color(value, fallback):
    if isinstance(value, str) and HEX_COLOR.fullmatch(value):
        return value.upper()
    return fallback


def normalize(style, primary=None, secondary=None):
    if not isinstance(style, str) or style not in STYLES:
        style = "clasico"
    _, _, default_primary, default_secondary = STYLES[style]
    return {
        "id": style,
        "version": 1,
        "primary": clean_color(primary, default_primary),
        "secondary": clean_color(secondary, default_secondary),
    }


def template_context(style, primary=None, secondary=None):
    """Whiten the secondary color so dark print text stays legible."""
    data = normalize(style, primary, secondary)
    color = data["secondary"]
    components = [int(color[offset:offset + 2], 16) for offset in (1, 3, 5)]
    data["wash"] = "#" + "".join(f"{round(255 * .64 + channel * .36):02X}" for channel in components)
    return data


# --- Integración en FacturaPorAquí (no cambian la semántica de lo anterior) ---------------------------------------

def choices():
    """(id, nombre) de los cinco estilos, para el campo `estilo` de DisenoFactura."""
    return [(key, value[0]) for key, value in STYLES.items()]


def catalog():
    """Objetos {id, name, description, primary, secondary} para la pantalla «Diseño de factura»."""
    return [{"id": key, "name": name, "description": DESCRIPCIONES[key], "primary": primary, "secondary": secondary}
            for key, (name, _, primary, secondary) in STYLES.items()]


def is_valid_color(value):
    """El color llega exactamente como #RRGGBB (lo que acepta clean_color sin usar el respaldo)."""
    return isinstance(value, str) and HEX_COLOR.fullmatch(value) is not None


def opciones_personalizacion(fuente=None, encabezado=None, pie_comercial=None):
    """Valores seguros para una muestra o una copia persistida."""
    return {
        "fuente": fuente if isinstance(fuente, str) and fuente in FUENTES else "original",
        "encabezado": encabezado.strip()[:MAX_ENCABEZADO] if isinstance(encabezado, str) else "",
        "pie_comercial": pie_comercial.strip()[:MAX_PIE_COMERCIAL] if isinstance(pie_comercial, str) else "",
    }


def _tono_oscuro(color):
    """Mezcla el color con negro hasta que el texto blanco sea legible."""
    rgb = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]

    def luminancia(canales):
        lineales = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in canales]
        return sum(c * peso for c, peso in zip(lineales, (.2126, .7152, .0722)))

    while luminancia(rgb) > .174:
        rgb = [canal * .9 for canal in rgb]
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb)


def context_from_copy(copy):
    """`ride_style` de la plantilla a partir de la copia guardada en la factura ({id, version, primary, secondary}).

    Equivale a template_context(id, primary, secondary): la copia también lleva `version`, que template_context no
    recibe; se conserva en el resultado para saber con qué versión del estilo se emitió. Valores dañados o desconocidos
    caen en los de respaldo de normalize(), nunca en CSS arbitrario."""
    if not isinstance(copy, dict):
        return None
    data = template_context(copy.get("id"), copy.get("primary"), copy.get("secondary"))
    if isinstance(copy.get("version"), int):
        data["version"] = copy["version"]
    if data["version"] == VERSION_PERSONALIZADA:
        data.update(opciones_personalizacion(copy.get("fuente"), copy.get("encabezado"), copy.get("pie_comercial")))
        data["familia"] = FUENTES[data["fuente"]][1]
        data["tono_oscuro"] = _tono_oscuro(data["primary"])
        data["proveedor_fijo"] = PROVEEDOR_FIJO
        data["colores_originales"] = (data["id"] == "clasico" and
                                       (data["primary"], data["secondary"]) == STYLES["clasico"][2:])
        data["personalizado"] = True
    return data
