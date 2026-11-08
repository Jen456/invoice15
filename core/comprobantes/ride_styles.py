"""Allowed PDF styles and colors. Use validated context values in the RIDE."""
import re

STYLES = {
    "clasico": ("Clásico", "Diseño actual con dos bloques de encabezado.", "#CA462C", "#E5F1F6"),
    "corporativo": ("Corporativo", "Cabecera enmarcada y un bloque fiscal destacado.", "#174886", "#C8DDF4"),
    "minimalista": ("Minimalista", "Fondo blanco y líneas finas.", "#284A45", "#D6ECE4"),
    "banda": ("Banda de marca", "La identidad del comercio encabeza el documento.", "#603D80", "#ECDCF8"),
    "compacto": ("Compacto", "Encabezado corto y tabla de mayor densidad.", "#21635D", "#D6EAE7"),
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
