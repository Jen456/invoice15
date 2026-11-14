"""Idempotencia de una acción repetible o por lote sobre un recurso que ya existe (decisión común 5c de
contable/bloque-2-especificacion.md): agregar auxiliares a una línea, asignaciones… La clave no puede ir en la fila creada
(son varias) ni en el recurso (la acción se repite): va en `RegistroClave`, con la huella del contenido y lo necesario
para rehacer la respuesta.

Uso, siempre dentro de la transacción que tiene el recurso bloqueado:

    hecho = registro_clave.previo(clave, 'apertura_auxiliares', 'apertura', apertura.pk, contenido)
    if hecho is not None:
        return hecho, True                      # el mismo envío ya se aplicó: el mismo resultado, `repetido`
    … aplicar la acción …
    registro_clave.guardar(clave, 'apertura_auxiliares', 'apertura', apertura.pk, contenido, resultado, autor)

Con el recurso bloqueado, dos envíos con la misma clave sobre el mismo recurso se ponen en fila: el segundo encuentra el
registro del primero. Si la misma clave se usó para otra acción u otro recurso (o con otro contenido), 409 `clave_usada`.
Si otra transacción la guardó a la vez para otro recurso, la restricción única decide: `guardar` lanza el 409 y la
transacción de quien llama se deshace entera (con su acción)."""
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from core.contabilidad import api
from core.contabilidad.models import RegistroClave

TEXTO_CLAVE_USADA = 'Esta clave ya se usó para otro envío: vuelve a cargar la página e inténtalo de nuevo.'


def huella(contenido):
    """SHA-256 del contenido normalizado (JSON con claves ordenadas, sin espacios; Decimal y fechas como texto). Quien
    llama pasa el contenido ya limpio y sin la clave."""
    texto = json.dumps(contenido, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(texto.encode('ascii')).hexdigest()


def _usada(registro):
    return api.ErrorApi('clave_usada', TEXTO_CLAVE_USADA, 409, recurso={'tipo': registro.recurso_tipo, 'id': registro.recurso_id},
                        accion=registro.accion)


def previo(clave, accion, recurso_tipo, recurso_id, contenido):
    """El `resultado` guardado si este mismo envío (clave, acción, recurso y contenido) ya se aplicó; None si la clave es
    nueva. Lanza 409 `clave_usada` si se usó para otra cosa."""
    registro = RegistroClave.objects.filter(clave=clave).first()
    if registro is None:
        return None
    if (registro.accion, registro.recurso_tipo, registro.recurso_id, registro.huella) != (
            accion, recurso_tipo, recurso_id, huella(contenido)):
        raise _usada(registro)
    return registro.resultado


def guardar(clave, accion, recurso_tipo, recurso_id, contenido, resultado, autor):
    """Inserta el registro (en su punto de guardado). `autor` = `(id, nombre)`. Devuelve la fila."""
    registro = RegistroClave(clave=clave, accion=accion, recurso_tipo=recurso_tipo, recurso_id=recurso_id,
                             huella=huella(contenido), resultado=resultado, creado_por_id=autor[0], creado_por_nombre=autor[1])
    try:
        with transaction.atomic():
            registro.save()
    except IntegrityError:
        otro = RegistroClave.objects.filter(clave=clave).first()
        if otro is None:
            raise
        raise _usada(otro) from None
    return registro
