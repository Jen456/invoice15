"""Disparadores de PostgreSQL que hacen el libro de solo inserción aunque se escriba por SQL (tercera capa de la decisión
común 2; la primera es diario.py y la segunda, las guardas de core/contabilidad/modelos_libro.py). En SQLite no hace nada.

- `fpa_linea_solo_insercion`: una línea de asiento no se cambia ni se borra.
- `fpa_linea_en_asiento_abierto`: una línea nueva va en un asiento que existe, es de su misma empresa y no está sellado,
  y su cuenta existe y es de la misma empresa (`bulk_create` no pasa por `check_tenant_references`, y la restricción de
  clave foránea no mira la empresa).
- `fpa_asiento_solo_sello_o_reverso`: un asiento no se borra; solo se actualiza, sin cambiar ninguna otra columna, para
  (a) sellarlo, una vez, si sus líneas suman exactamente sus totales y son tantas como `lineas_n`, o (b) fijar, una vez y
  juntos, `reversado_por_id` y `reversado_en` de uno sellado, cuando `reversado_por` es su reverso. No hay un tercer caso:
  el autor no es una FK (decisión común 16) y nadie lo anula al borrar al usuario.
- `fpa_asiento_nace_abierto` (no está en la especificación): un asiento se inserta sin sellar y sin reverso. Sin él, un
  INSERT con `sellado = true` se saltaría la comprobación del sello y dejaría en el libro un asiento sin sus líneas.
- `fpa_asiento_sellado`: diferido al confirmar la transacción, relee la fila por id (en un disparador diferido `NEW` es la
  fila tal como se insertó, sin sellar) y rechaza la transacción si el asiento no quedó sellado. Para esa lectura pone
  `app.platform = 'on'` en la transacción (`set_config(…, true)`) y lo devuelve enseguida a lo que tenía: al confirmar, la
  empresa de la sesión puede ser ya otra (o ninguna, como al terminar una prueba) y la seguridad por filas escondería la
  fila. Solo lee la fila que se insertó. (Un `SET app.platform` en la definición de la función sería más limpio, pero
  PostgreSQL solo deja fijar así una variable propia al superusuario, y las funciones las crea el rol de la aplicación.)
- `fpa_evento_solo_insercion`: la historia de la apertura no se cambia ni se borra.

TRUNCATE y DROP TABLE no los disparan: el vaciado de las pruebas transaccionales y la vuelta de migraciones siguen
funcionando. La vuelta quita los disparadores y sus funciones. Los mensajes empiezan por el nombre del disparador."""
from django.db import migrations

FUNCIONES = {
    'fpa_linea_solo_insercion': """
        BEGIN
            RAISE EXCEPTION USING MESSAGE = 'fpa_linea_solo_insercion: las líneas de asiento son de solo inserción ('
                                            || TG_OP || ' rechazado)';
        END;""",
    'fpa_linea_en_asiento_abierto': """
        DECLARE
            padre record;
        BEGIN
            SELECT company_id, sellado INTO padre FROM contabilidad_asiento WHERE id = NEW.asiento_id FOR SHARE;
            IF NOT FOUND OR padre.company_id IS DISTINCT FROM NEW.company_id THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_linea_en_asiento_abierto: el asiento ' || NEW.asiento_id
                                                || ' no existe o es de otra empresa';
            END IF;
            IF padre.sellado THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_linea_en_asiento_abierto: el asiento ' || NEW.asiento_id
                                                || ' ya está sellado y no admite líneas';
            END IF;
            PERFORM 1 FROM contabilidad_cuenta WHERE id = NEW.cuenta_id AND company_id = NEW.company_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_linea_en_asiento_abierto: la cuenta ' || NEW.cuenta_id
                                                || ' no existe o es de otra empresa';
            END IF;
            RETURN NEW;
        END;""",
    'fpa_asiento_solo_sello_o_reverso': """
        DECLARE
            n bigint;
            suma_debe numeric;
            suma_haber numeric;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_solo_sello_o_reverso: el asiento ' || OLD.id
                                                || ' no se borra (se reversa)';
            END IF;
            IF (to_jsonb(NEW) - 'sellado' - 'reversado_por_id' - 'reversado_en')
               IS DISTINCT FROM (to_jsonb(OLD) - 'sellado' - 'reversado_por_id' - 'reversado_en') THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_solo_sello_o_reverso: el asiento ' || OLD.id
                                                || ' no se modifica (solo se sella o se marca su reverso)';
            END IF;
            -- (a) el sello, una vez, con las líneas que cuadran con los totales
            IF NOT OLD.sellado AND NEW.sellado AND OLD.reversado_por_id IS NULL AND NEW.reversado_por_id IS NULL
               AND OLD.reversado_en IS NULL AND NEW.reversado_en IS NULL THEN
                SELECT count(*), coalesce(sum(debe), 0), coalesce(sum(haber), 0) INTO n, suma_debe, suma_haber
                  FROM contabilidad_lineaasiento WHERE asiento_id = NEW.id;
                IF n <> NEW.lineas_n OR suma_debe <> NEW.total_debe OR suma_haber <> NEW.total_haber
                   OR suma_debe <> suma_haber THEN
                    RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_solo_sello_o_reverso: las líneas del asiento ' || NEW.id
                                                    || ' no cuadran con sus totales y no se sella';
                END IF;
                RETURN NEW;
            END IF;
            -- (b) el par del reverso, una vez y junto, en un asiento sellado, apuntando a su reverso
            IF OLD.sellado AND NEW.sellado AND OLD.reversado_por_id IS NULL AND NEW.reversado_por_id IS NOT NULL
               AND OLD.reversado_en IS NULL AND NEW.reversado_en IS NOT NULL THEN
                PERFORM 1 FROM contabilidad_asiento r
                 WHERE r.id = NEW.reversado_por_id AND r.reversa_de_id = NEW.id AND r.company_id = NEW.company_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_solo_sello_o_reverso: el asiento ' || NEW.reversado_por_id
                                                    || ' no es el reverso del asiento ' || NEW.id;
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_solo_sello_o_reverso: el asiento ' || OLD.id
                                            || ' no admite ese cambio (se sella una vez y su reverso se marca una vez)';
        END;""",
    'fpa_asiento_nace_abierto': """
        BEGIN
            IF NEW.sellado OR NEW.reversado_por_id IS NOT NULL OR NEW.reversado_en IS NOT NULL THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_nace_abierto: un asiento se inserta sin sellar y sin reverso'
                                                || ' (se sella después de insertar sus líneas)';
            END IF;
            RETURN NEW;
        END;""",
    'fpa_asiento_sellado': """
        DECLARE
            sello boolean;
            encontrado boolean;
            anterior text := current_setting('app.platform', true);
        BEGIN
            PERFORM set_config('app.platform', 'on', true);
            SELECT sellado INTO sello FROM contabilidad_asiento WHERE id = NEW.id;
            encontrado := FOUND;
            PERFORM set_config('app.platform', coalesce(anterior, ''), true);
            IF encontrado AND NOT sello THEN
                RAISE EXCEPTION USING MESSAGE = 'fpa_asiento_sellado: el asiento ' || NEW.id
                                                || ' llega sin sellar al confirmar la transacción';
            END IF;
            RETURN NULL;
        END;""",
    'fpa_evento_solo_insercion': """
        BEGIN
            RAISE EXCEPTION USING MESSAGE = 'fpa_evento_solo_insercion: la historia de la apertura es de solo inserción ('
                                            || TG_OP || ' rechazado)';
        END;""",
}
# (disparador = función, tabla, definición)
DISPARADORES = (
    ('fpa_linea_solo_insercion', 'contabilidad_lineaasiento', 'BEFORE UPDATE OR DELETE ON {tabla} FOR EACH ROW'),
    ('fpa_linea_en_asiento_abierto', 'contabilidad_lineaasiento', 'BEFORE INSERT ON {tabla} FOR EACH ROW'),
    ('fpa_asiento_solo_sello_o_reverso', 'contabilidad_asiento', 'BEFORE UPDATE OR DELETE ON {tabla} FOR EACH ROW'),
    ('fpa_asiento_nace_abierto', 'contabilidad_asiento', 'BEFORE INSERT ON {tabla} FOR EACH ROW'),
    ('fpa_asiento_sellado', 'contabilidad_asiento',
     'AFTER INSERT ON {tabla} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW'),
    ('fpa_evento_solo_insercion', 'contabilidad_eventoapertura', 'BEFORE UPDATE OR DELETE ON {tabla} FOR EACH ROW'),
)
DE_RESTRICCION = {'fpa_asiento_sellado'}   # CONSTRAINT TRIGGER: el único que puede diferirse


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for nombre, cuerpo in FUNCIONES.items():
        # params=None: el texto va tal cual (sin interpretar `%`).
        schema_editor.execute(f'CREATE OR REPLACE FUNCTION {nombre}() RETURNS trigger LANGUAGE plpgsql '
                              f'AS $fpa${cuerpo}\n$fpa$', None)
    for nombre, tabla, definicion in DISPARADORES:
        clase = 'CONSTRAINT TRIGGER' if nombre in DE_RESTRICCION else 'TRIGGER'
        schema_editor.execute(f'CREATE {clase} {nombre} {definicion.format(tabla=qn(tabla))} EXECUTE FUNCTION {nombre}()', None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for nombre, tabla, _ in DISPARADORES:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {nombre} ON {qn(tabla)}', None)
    for nombre in FUNCIONES:
        schema_editor.execute(f'DROP FUNCTION IF EXISTS {nombre}()', None)


class Migration(migrations.Migration):

    dependencies = [('contabilidad', '0012_rls_libro_apertura')]

    operations = [migrations.RunPython(forwards, backwards)]
