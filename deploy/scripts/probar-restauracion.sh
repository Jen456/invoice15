#!/bin/bash
# FacturaPorAquí — prueba de restauración de un respaldo de respaldo-previo.sh: la base en una base temporal (los mismos
# pasos que restaurar.sh: createdb -O <usuario de la app> + pg_restore --role) y los archivos privados en una carpeta
# temporal. Compara las filas por tabla con la base publicada y las huellas de los archivos; borra lo temporal al salir.
#   bash probar-restauracion.sh <carpeta del respaldo> [entorno]
set -euo pipefail
D=${1:?carpeta del respaldo}
ENVF=/etc/facturaporaqui/${2:-pruebas}.env
read -r APPUSER PRODDB < <(set -a; . "$ENVF"; set +a; python3 -c 'import os; from urllib.parse import urlsplit; u = urlsplit(os.environ["DATABASE_URL"]); print(u.username, u.path.lstrip("/"))')
TMPDB=fpa_restauracion_prueba
T=$(mktemp -d /tmp/fpa-restauracion.XXXXXX)
limpiar() { runuser -u postgres -- dropdb --if-exists "$TMPDB"; rm -rf "$T"; }
trap limpiar EXIT
runuser -u postgres -- dropdb --if-exists "$TMPDB"
runuser -u postgres -- createdb -O "$APPUSER" "$TMPDB"
inicio=$(date +%s)
runuser -u postgres -- pg_restore --no-owner --no-privileges --role="$APPUSER" --exit-on-error -d "$TMPDB" < "$D/base.dump"
echo "base restaurada en $(( $(date +%s) - inicio )) s"
conteos() {  # filas por tabla de public; postgres es superusuario y no lo filtra la RLS
  runuser -u postgres -- psql -X -At -v ON_ERROR_STOP=1 -d "$1" <<'SQL'
select format('select %L, count(*) from public.%I', tablename, tablename) from pg_tables where schemaname = 'public' order by tablename \gexec
SQL
}
conteos "$TMPDB" > "$T/restaurada.txt"
conteos "$PRODDB" > "$T/publicada.txt"
echo "tablas: $(wc -l < "$T/restaurada.txt") restauradas, $(wc -l < "$T/publicada.txt") publicadas; filas restauradas: $(awk -F'|' '{s += $2} END {print s}' "$T/restaurada.txt")"
if diff -q "$T/restaurada.txt" "$T/publicada.txt" > /dev/null; then echo "conteos por tabla: IDÉNTICOS a la base publicada"
else echo "conteos distintos (lo escrito en la base publicada después del volcado):"; diff "$T/restaurada.txt" "$T/publicada.txt" | grep -E '^[<>]' | head -20; fi
runuser -u postgres -- psql -X -At -d "$TMPDB" -c "select 'ventas', count(*), max(id) from pos_sale union all select 'empresas', count(*), max(id) from pos_company union all select 'comprobantes recibidos', count(*), max(id) from pos_purchase"
mkdir "$T/archivos"
tar -C "$T/archivos" --numeric-owner -xpzf "$D/archivos-privados.tar.gz"
( cd "$T/archivos" && sha256sum --quiet --strict -c "$D/archivos.sha256" ) && echo "archivos privados: $(wc -l < "$D/archivos.sha256") restaurados con la misma huella"
echo "prueba de restauración: OK"
