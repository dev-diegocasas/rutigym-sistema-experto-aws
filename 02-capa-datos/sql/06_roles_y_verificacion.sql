-- =====================================================================
-- 06. Validador solo del ingeniero, verificación formal definitiva y alias legibles. Idempotente.
-- =====================================================================
SET search_path = se;

REVOKE EXECUTE ON FUNCTION fn_validar_base() FROM rol_experto;

CREATE OR REPLACE FUNCTION fn_verificacion_definitiva() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = se, pg_temp
AS $$
BEGIN
    IF OLD.verificacion_formal IN ('VALID', 'INVALID', 'SATISFIABLE', 'IMPOSSIBLE')
       AND (NEW.verificacion_formal IS DISTINCT FROM OLD.verificacion_formal
            OR NEW.fecha_verificacion IS DISTINCT FROM OLD.fecha_verificacion) THEN
        RAISE EXCEPTION 'La verificación formal de esta consulta ya es definitiva (%)', OLD.verificacion_formal;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE EXECUTE ON FUNCTION fn_verificacion_definitiva() FROM PUBLIC;

DROP TRIGGER IF EXISTS tr_verificacion_definitiva ON consulta;
CREATE TRIGGER tr_verificacion_definitiva BEFORE UPDATE OF verificacion_formal, fecha_verificacion ON consulta
    FOR EACH ROW EXECUTE FUNCTION fn_verificacion_definitiva();

-- ---------------------------------------------------------------------
-- Alias legibles: los perfiles creados al registrarse tenían un alias al azar
-- («usuario-c47814»). Ahora el alias sale del nombre de registro: primer nombre
-- e inicial del apellido («Juan Pérez» -> juan.p), con un número si se repite.
-- El alias no es la llave (la llave es id_usuario), así que cambiarlo no afecta
-- consultas ni validaciones.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    r RECORD; v_palabras TEXT[]; v_base TEXT; v_alias TEXT; n INT;
-- Alias legibles desde el nombre («Juan Pérez» -> juan.p); corrige los alias al azar.
BEGIN
    FOR r IN SELECT id_usuario, nombre, correo FROM usuario
              WHERE alias ~ '^usuario-[0-9a-f]{6}$' ORDER BY id_usuario LOOP
        v_palabras := regexp_split_to_array(
            btrim(regexp_replace(translate(lower(r.nombre), 'áéíóúüñàèìòù', 'aeiouunaeiou'),
                                 '[^a-z0-9]+', ' ', 'g')), ' ');
        IF v_palabras IS NULL OR v_palabras[1] IS NULL OR v_palabras[1] = '' THEN
            v_palabras := regexp_split_to_array(
                btrim(regexp_replace(lower(split_part(r.correo, '@', 1)), '[^a-z0-9]+', ' ', 'g')), ' ');
        END IF;
        v_base := left(v_palabras[1] || CASE WHEN array_length(v_palabras, 1) > 1
                                             THEN '.' || left(v_palabras[2], 1) ELSE '' END, 26);
        v_alias := v_base; n := 1;
        WHILE EXISTS (SELECT 1 FROM usuario WHERE alias = v_alias AND id_usuario <> r.id_usuario) LOOP
            n := n + 1; v_alias := left(v_base, 27) || n;
        END LOOP;
        UPDATE usuario SET alias = v_alias WHERE id_usuario = r.id_usuario;
    END LOOP;
END;
$$;
