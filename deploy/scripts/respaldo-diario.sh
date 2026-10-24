#!/bin/bash
# =============================================================================
# FacturaPorAquí — volcado diario de la base PostgreSQL (VM101, root).
#
#   bash respaldo-diario.sh <entorno>
#
# Lo lanza facturaporaqui-respaldo@<entorno>.timer a las 18:15 de Ecuador, antes del respaldo nocturno del
# hipervisor (19:00), que copia /home/ de VM101 —con estos volcados, los archivos y las firmas— a la instantánea
# cifrada restic que descarga el NAS (historial: 14 diarios, 8 semanales, 12 mensuales, 3 anuales).
# Aquí se conservan los últimos 14 volcados. Con RLS forzada, pg_dump necesita --enable-row-security y
# app.platform=on para ver las filas de todas las empresas (igual que desplegar.sh).
# Las credenciales viajan por variables de entorno, nunca en la línea de órdenes (visible para todo el sistema).
# =============================================================================
set -euo pipefail
umask 077
ENTORNO="${1:?Falta el entorno (p. ej. pruebas)}"
USUARIO=facturaporaqui
ENVF=/etc/facturaporaqui/$ENTORNO.env
DESTINO=/home/$USUARIO/datos/$ENTORNO/respaldos/diario
CONSERVAR=14
MINIMO_TABLAS=20

exec 9> "/run/facturaporaqui-respaldo-$ENTORNO.lock"
flock -n 9 || { echo "Ya hay un respaldo de $ENTORNO en curso."; exit 0; }
mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

FPA_URL=$(grep -E '^DATABASE_URL=' "$ENVF" | head -1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]$//")
export FPA_URL
eval "$(python3 -c '
import os, shlex
from urllib.parse import urlsplit, unquote
u = urlsplit(os.environ["FPA_URL"])
for clave, valor in (("PGHOST", u.hostname or "localhost"), ("PGPORT", str(u.port or 5432)), ("PGUSER", unquote(u.username or "")),
                     ("PGPASSWORD", unquote(u.password or "")), ("PGDATABASE", u.path.lstrip("/"))):
    print(f"export {clave}={shlex.quote(valor)}")
')"
unset FPA_URL

FECHA=$(date -u +%Y%m%d-%H%M%S)
TEMPORAL="$DESTINO/.diario-$FECHA.dump.tmp"
FINAL="$DESTINO/diario-$FECHA.dump"
trap 'rm -f "$TEMPORAL"' EXIT
PGOPTIONS="-c app.platform=on" nice -n 10 pg_dump --enable-row-security --format=custom --no-owner --file="$TEMPORAL"
TABLAS=$(pg_restore --list "$TEMPORAL" | grep -c " TABLE DATA " || true)
if [ "$TABLAS" -lt "$MINIMO_TABLAS" ]; then
  echo "ERROR: el volcado solo tiene $TABLAS tablas con datos (mínimo $MINIMO_TABLAS); no se guarda." >&2
  exit 1
fi
mv "$TEMPORAL" "$FINAL"
trap - EXIT
ls -1t "$DESTINO"/diario-*.dump | tail -n +$((CONSERVAR + 1)) | xargs -r rm -f
echo "Respaldo $ENTORNO: $(basename "$FINAL") · $(du -h "$FINAL" | cut -f1) · $TABLAS tablas · $(ls "$DESTINO"/diario-*.dump | wc -l) conservados"
