"""Paginación de las listas de /contabilidad/api/ (decisión común 7 de contable/bloque-2-especificacion.md):
`?pagina=1&por_pagina=100` (máximo 500) → `"paginacion": {"pagina", "por_pagina", "total", "paginas"}`.

Una página más allá de la última no es un error: llega vacía, con la paginación que dice cuántas hay."""
POR_PAGINA, POR_PAGINA_MAX = 100, 500
PAGINA_MAX = 10 ** 6
TEXTOS = {
    'pagina': 'La página es un número entero desde 1.',
    'por_pagina': f'Se muestran de 1 a {POR_PAGINA_MAX} por página.',
}


def _entero(texto):
    texto = (texto or '').strip()
    return int(texto) if texto.isascii() and texto.isdigit() and len(texto) <= 7 else None


def pedida(consulta, errores):
    """`(pagina, por_pagina)` de la consulta de la URL; un valor que no vale deja su error en `errores` (api.Errores)."""
    pagina, por_pagina = 1, POR_PAGINA
    if consulta.get('pagina') not in (None, ''):
        pagina = _entero(consulta.get('pagina'))
        if pagina is None or not 1 <= pagina <= PAGINA_MAX:
            errores.agregar('pagina', TEXTOS['pagina'])
            pagina = 1
    if consulta.get('por_pagina') not in (None, ''):
        por_pagina = _entero(consulta.get('por_pagina'))
        if por_pagina is None or not 1 <= por_pagina <= POR_PAGINA_MAX:
            errores.agregar('por_pagina', TEXTOS['por_pagina'])
            por_pagina = POR_PAGINA
    return pagina, por_pagina


def tramo(pagina, por_pagina):
    """`slice` de la página dentro de la consulta ordenada."""
    inicio = (pagina - 1) * por_pagina
    return slice(inicio, inicio + por_pagina)


def datos(pagina, por_pagina, total):
    return {'pagina': pagina, 'por_pagina': por_pagina, 'total': total, 'paginas': max(1, -(-total // por_pagina))}
