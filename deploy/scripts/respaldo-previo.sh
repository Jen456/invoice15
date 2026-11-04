#!/bin/bash
# FacturaPorAquí — respaldo previo a un despliegue con migraciones: volcado de la base (el mismo pg_dump que
# desplegar.sh) y archivos privados (archivos/ y firmas/, con dueños y permisos) con sus huellas.
#   bash respaldo-previo.sh [entorno]        (por defecto pruebas = app.facturaporaqui.com)
# Imprime la carpeta creada (respaldos/previo-<fecha>). No muestra credenciales. Comprobarlo con probar-restauracion.sh.
set -euo pipefail
umask 077
ENTORNO=${1:-pruebas}
ENVF=/etc/facturaporaqui/$ENTORNO.env
DATOS=/home/facturaporaqui/datos/$ENTORNO
D=$DATOS/respaldos/previo-$(date -u +%Y%m%d-%H%M%S)
install -d -m 700 "$D"
( set -a; . "$ENVF"; set +a
  PGOPTIONS="-c app.platform=on" pg_dump --enable-row-security --format=custom --no-owner --file="$D/base.dump" "$DATABASE_URL" )
tar -C "$DATOS" --numeric-owner -cpzf "$D/archivos-privados.tar.gz" archivos firmas
( cd "$DATOS" && find archivos firmas -type f -print0 | sort -z | xargs -0 -r sha256sum ) > "$D/archivos.sha256"
readlink -f /opt/facturaporaqui/$ENTORNO/current > "$D/version-publicada.txt"
chmod 600 "$D"/*
echo "$D"
ls -la "$D" | tail -n +4
echo "tablas con datos en el volcado: $(pg_restore --list "$D/base.dump" | grep -c 'TABLE DATA')"
