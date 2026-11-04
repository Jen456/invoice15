#!/bin/bash
# FacturaPorAquí — vuelta a la versión anterior ante una regresión grave de un despliegue con migraciones: base, código
# y estáticos (desplegar.sh --revertir solo vuelve el código).
#
#   bash restaurar.sh <volcado previo .dump> <carpeta de la versión anterior en releases/>             prepara y comprueba
#   bash restaurar.sh <volcado previo .dump> <carpeta de la versión anterior en releases/> --ejecutar  además, la aplica
#   (entorno: FPA_ENTORNO_DESPLIEGUE, por defecto pruebas = app.facturaporaqui.com)
#
# Preparar (sin parar nada): restaura el volcado en <base>_restaurada (createdb -O <usuario de la app> + pg_restore
# --role, como el ensayo) y lista lo que se escribió en la base publicada después del volcado, que se perdería
# (las ventas, notas y retenciones ya autorizadas en el SRI hay que volver a registrarlas a mano o corregir hacia
# adelante: con datos nuevos importantes, no restaurar sin decidirlo).
# Ejecutar: detiene servicio y tareas, renombra la base actual a <base>_fallida_<fecha> (se conserva para revisar),
# pone la restaurada en su lugar, vuelve `current` a la versión anterior, regenera sus estáticos, arranca y comprueba
# /login/. Los archivos privados no se tocan: el código anterior ignora las carpetas nuevas; si se dañaran, están en
# archivos-privados.tar.gz de respaldo-previo.sh (tar -xpzf en /home/facturaporaqui/datos/<entorno>, con huellas).
set -euo pipefail
DUMP=${1:?volcado previo}; ANTERIOR=${2:?carpeta de la versión anterior}; MODO=${3:-}
E=${FPA_ENTORNO_DESPLIEGUE:-pruebas}
ENVF=/etc/facturaporaqui/$E.env
RAIZ=/opt/facturaporaqui/$E
SERVICIO=facturaporaqui@$E.service
TAREAS="facturaporaqui-sri@$E.timer facturaporaqui-importacion@$E.timer"
[ -r "$DUMP" ] || { echo "no se puede leer $DUMP"; exit 1; }
[ -f "$ANTERIOR/REVISION" ] && [ -x "$ANTERIOR/.venv/bin/python" ] || { echo "versión anterior no válida: $ANTERIOR"; exit 1; }
read -r APPUSER DB < <(set -a; . "$ENVF"; set +a; python3 -c 'import os; from urllib.parse import urlsplit; u = urlsplit(os.environ["DATABASE_URL"]); print(u.username, u.path.lstrip("/"))')
NUEVA="${DB}_restaurada"
psqlp() { runuser -u postgres -- psql -X -At -v ON_ERROR_STOP=1 "$@"; }
conteos() {
  psqlp -d "$1" <<'SQL'
select format('select %L, count(*) from public.%I', tablename, tablename) from pg_tables where schemaname = 'public' order by tablename \gexec
SQL
}

echo "== 1. Volcado $(basename "$DUMP") en $NUEVA (versión anterior: $(cut -c1-8 "$ANTERIOR/REVISION"))"
runuser -u postgres -- dropdb --if-exists "$NUEVA"
runuser -u postgres -- createdb -O "$APPUSER" "$NUEVA"
runuser -u postgres -- pg_restore --no-owner --no-privileges --role="$APPUSER" --exit-on-error -d "$NUEVA" < "$DUMP"
echo "  restaurado: $(psqlp -d "$NUEVA" -c "select count(*) from pg_tables where schemaname = 'public'") tablas"

echo "== 2. Escrito en la base publicada después del volcado (se perdería al restaurar)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
conteos "$NUEVA" | LC_ALL=C sort -t'|' -k1,1 > "$T/volcado.txt"; conteos "$DB" | LC_ALL=C sort -t'|' -k1,1 > "$T/publicada.txt"
LC_ALL=C join -t'|' -a2 -e0 -o '0,1.2,2.2' "$T/volcado.txt" "$T/publicada.txt" | awk -F'|' '$3 != $2 {printf "  %s: %s → %s\n", $1, $2, $3}' | grep -v "django_session" || echo "  nada fuera de las sesiones"
MAXV=$(psqlp -d "$NUEVA" -c "select coalesce(max(id), 0) from pos_sale")
psqlp -d "$DB" -F' · ' -c "select 'venta ' || id, voucher_number_full, status, date_joined from pos_sale where id > $MAXV order by id" | sed 's/^/  /'

[ "$MODO" = "--ejecutar" ] || { echo "PREPARADO (sin cambios en lo publicado). Para aplicar: $0 $DUMP $ANTERIOR --ejecutar"; exit 0; }

TS=$(date -u +%Y%m%d-%H%M%S)
echo "== 3. Aplicación ($TS)"
systemctl stop $TAREAS
systemctl stop "$SERVICIO"
psqlp -d postgres -c "select count(pg_terminate_backend(pid)) from pg_stat_activity where datname in ('$DB', '$NUEVA') and pid <> pg_backend_pid()" > /dev/null
psqlp -d postgres -c "alter database \"$DB\" rename to \"${DB}_fallida_$TS\"" -c "alter database \"$NUEVA\" rename to \"$DB\""
echo "  base publicada = volcado; la anterior quedó como ${DB}_fallida_$TS"
ln -sfn "$ANTERIOR" "$RAIZ/current.nuevo" && mv -Tf "$RAIZ/current.nuevo" "$RAIZ/current"
runuser -u facturaporaqui -- env -C "$ANTERIOR" bash -c 'set -a; . "$0"; set +a; exec .venv/bin/python manage.py collectstatic --noinput --clear -v 0' "$ENVF"
chmod -R a+rX "$(sed -n 's/^STATIC_ROOT=//p' "$ENVF")"
systemctl start "$SERVICIO"
DOMINIO=$(sed -n 's/^ALLOWED_HOSTS=\([^,]*\).*/\1/p' "$ENVF"); PUERTO=$(sed -n 's/^FPA_PUERTO=//p' "$ENVF")
for _ in $(seq 1 30); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMINIO" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:$PUERTO/login/" || true)
  [ "$c" = 200 ] && break; sleep 1
done
echo "  salud: /login/ → $c"
systemctl start $TAREAS
echo "RESTAURADO: código $(cut -c1-8 "$RAIZ/current/REVISION"), base del volcado $(basename "$DUMP")"
