-- =====================================================================
-- 03. Procedimientos del ingeniero, validador y auditoría. Ejecutar como se_owner.
-- =====================================================================
SET search_path = se;

-- ---------------------------------------------------------------------
-- Coherencia de un gránulo (hecho -> hipótesis) con el perfil de la
-- hipótesis. Devuelve NULL si es coherente o el motivo si no lo es.
-- Reglas de dominio dadas por el experto (no son reglas de inferencia):
-- cada nivel corresponde a un tiempo de entrenamiento, y Intermedio y
-- Avanzado exigen dominar la técnica.
-- ---------------------------------------------------------------------
-- Coherencia de un gránulo con su hipótesis: NULL si es coherente, o el motivo.
CREATE FUNCTION fn_coherencia(p_id_hecho INT, p_id_hipotesis INT) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_atributo TEXT;
    v_valor    TEXT;
    v_tiempo   TEXT;
    h          hipotesis%ROWTYPE;
BEGIN
    SELECT p.atributo, he.valor INTO v_atributo, v_valor
      FROM hechos he JOIN preguntas p ON p.id_pregunta = he.id_pregunta
     WHERE he.id_hecho = p_id_hecho;
    SELECT * INTO h FROM hipotesis WHERE id_hipotesis = p_id_hipotesis;
    v_tiempo := CASE h.nivel WHEN 'Principiante' THEN 'Menos de 6 meses'
                             WHEN 'Intermedio'   THEN '6 meses a 2 años'
                             ELSE 'Más de 2 años' END;

    IF v_atributo = 'equipo_disponible' AND v_valor <> h.equipo::TEXT THEN
        RETURN format('el equipo "%s" no corresponde al de la hipótesis (%s)', v_valor, h.equipo);
    ELSIF v_atributo = 'objetivo_principal'
          AND (h.objetivo IS NULL OR v_valor <> h.objetivo::TEXT) THEN
        RETURN format('el objetivo "%s" no corresponde a la hipótesis (%s)',
                      v_valor, COALESCE(h.objetivo::TEXT, 'sin objetivo'));
    ELSIF v_atributo = 'fase_priorizada'
          AND (h.fase IS NULL OR v_valor <> h.fase::TEXT) THEN
        RETURN format('la fase "%s" no corresponde a la hipótesis (%s)',
                      v_valor, COALESCE(h.fase::TEXT, 'sin fase'));
    ELSIF v_atributo = 'tiempo_entrenando' AND v_valor <> v_tiempo THEN
        RETURN format('el tiempo "%s" no corresponde al nivel %s', v_valor, h.nivel);
    ELSIF v_atributo = 'tecnica_dominada' AND h.nivel <> 'Principiante' AND v_valor <> 'Sí' THEN
        RETURN format('el nivel %s exige dominar la técnica', h.nivel);
    ELSIF v_atributo = 'dias_semana'
          AND (h.dias_semana IS NULL OR v_valor <> h.dias_semana::TEXT) THEN
        RETURN format('los días "%s" no corresponden a la hipótesis (%s)',
                      v_valor, COALESCE(h.dias_semana::TEXT, 'no aplica a su nivel'));
    ELSIF v_atributo = 'actividad_actual'
          AND (h.actividad IS NULL OR v_valor <> h.actividad::TEXT) THEN
        RETURN format('la actividad "%s" no corresponde a la hipótesis (%s)',
                      v_valor, COALESCE(h.actividad::TEXT, 'no aplica a su nivel'));
    END IF;
    RETURN NULL;
END;
$$;

-- ---------------------------------------------------------------------
-- Hechos y opciones de respuesta (se registran juntos)
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_registrar_hecho(
    p_codigo VARCHAR, p_pregunta VARCHAR, p_valor VARCHAR, p_texto_opcion VARCHAR,
    p_sinonimos TEXT[], p_orden INT, p_descripcion VARCHAR DEFAULT NULL)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE
    v_id_pregunta INT;
    v_id_hecho    INT;
    v_sinonimos   TEXT[];
    v_choque      TEXT;
BEGIN
    SELECT id_pregunta INTO v_id_pregunta FROM preguntas WHERE codigo = p_pregunta;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Hecho %: la pregunta % no existe', p_codigo, p_pregunta;
    END IF;
    IF btrim(COALESCE(p_valor, '')) = '' OR btrim(COALESCE(p_texto_opcion, '')) = '' THEN
        RAISE EXCEPTION 'Hecho %: el valor y el texto de la opción son obligatorios', p_codigo;
    END IF;

    -- Sinónimos normalizados (minúsculas, sin espacios sobrantes ni repetidos)
    SELECT COALESCE(array_agg(DISTINCT lower(btrim(s))), '{}') INTO v_sinonimos
      FROM unnest(COALESCE(p_sinonimos, '{}')) s WHERE btrim(s) <> '';

    SELECT id_hecho INTO v_id_hecho FROM hechos WHERE codigo = p_codigo;
    IF FOUND THEN
        IF (SELECT id_pregunta FROM hechos WHERE id_hecho = v_id_hecho) <> v_id_pregunta THEN
            RAISE EXCEPTION 'Hecho %: no se puede mover a otra pregunta', p_codigo;
        END IF;
        UPDATE hechos SET valor = btrim(p_valor), descripcion = p_descripcion
         WHERE id_hecho = v_id_hecho;
    ELSE
        INSERT INTO hechos (codigo, id_pregunta, valor, descripcion)
        VALUES (p_codigo, v_id_pregunta, btrim(p_valor), p_descripcion)
        RETURNING id_hecho INTO v_id_hecho;
    END IF;

    -- Un sinónimo no puede servir para dos opciones de la misma pregunta
    SELECT s INTO v_choque
      FROM respuesta_pregunta r, unnest(r.sinonimos) s
     WHERE r.id_pregunta = v_id_pregunta AND r.id_hecho <> v_id_hecho
       AND s = ANY (v_sinonimos)
     LIMIT 1;
    IF v_choque IS NOT NULL THEN
        RAISE EXCEPTION 'Hecho %: el sinónimo "%" ya pertenece a otra opción de %',
                        p_codigo, v_choque, p_pregunta;
    END IF;

    INSERT INTO respuesta_pregunta (id_pregunta, id_hecho, texto_opcion, sinonimos, orden)
    VALUES (v_id_pregunta, v_id_hecho, btrim(p_texto_opcion), v_sinonimos, p_orden)
    ON CONFLICT (id_hecho) DO UPDATE
       SET texto_opcion = EXCLUDED.texto_opcion, sinonimos = EXCLUDED.sinonimos,
           orden = EXCLUDED.orden;
END;
$$;

CREATE PROCEDURE sp_eliminar_hecho(p_codigo VARCHAR)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE v_id INT;
BEGIN
    SELECT id_hecho INTO v_id FROM hechos WHERE codigo = p_codigo;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Hecho %: no existe', p_codigo;
    END IF;
    IF EXISTS (SELECT 1 FROM hechos_hipotesis WHERE id_hecho = v_id) THEN
        RAISE EXCEPTION 'Hecho %: está asociado a hipótesis; desasócielo primero', p_codigo;
    END IF;
    IF EXISTS (SELECT 1 FROM consulta_hecho WHERE id_hecho = v_id) THEN
        RAISE EXCEPTION 'Hecho %: forma parte del historial de consultas; no se puede eliminar',
                        p_codigo;
    END IF;
    DELETE FROM hechos WHERE id_hecho = v_id;   -- la opción de respuesta se borra en cascada
END;
$$;

-- ---------------------------------------------------------------------
-- Preguntas: el ingeniero ajusta textos y peso base (no crea ni borra)
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_actualizar_pregunta(
    p_codigo VARCHAR, p_texto VARCHAR, p_ayuda VARCHAR, p_peso_base NUMERIC,
    p_aplicar_peso_a_granulos BOOLEAN DEFAULT FALSE)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE v_id INT;
BEGIN
    SELECT id_pregunta INTO v_id FROM preguntas WHERE codigo = p_codigo;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Pregunta %: no existe', p_codigo;
    END IF;
    IF p_peso_base IS NULL OR p_peso_base <= 0 OR p_peso_base >= 1 THEN
        RAISE EXCEPTION 'Pregunta %: el peso base debe estar entre 0 y 1 (exclusivos)', p_codigo;
    END IF;
    UPDATE preguntas SET texto = btrim(p_texto), ayuda = NULLIF(btrim(p_ayuda), ''),
                         peso_base = p_peso_base
     WHERE id_pregunta = v_id;
    IF p_aplicar_peso_a_granulos THEN
        UPDATE hechos_hipotesis hh SET peso = p_peso_base
          FROM hechos he WHERE he.id_hecho = hh.id_hecho AND he.id_pregunta = v_id;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------
-- Hipótesis
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_registrar_hipotesis(
    p_codigo VARCHAR, p_nivel t_nivel, p_equipo t_equipo, p_objetivo t_objetivo,
    p_fase t_fase, p_dias_semana t_dias_semana, p_actividad t_actividad,
    p_descripcion TEXT, p_probabilidad_previa NUMERIC DEFAULT 1)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE
    v_id     INT;
    v_motivo TEXT;
BEGIN
    IF p_equipo IS NULL THEN
        RAISE EXCEPTION 'Hipótesis %: el equipo es obligatorio', p_codigo;
    END IF;
    IF p_nivel = 'Principiante' AND (p_objetivo IS NOT NULL OR p_fase IS NOT NULL) THEN
        RAISE EXCEPTION 'Hipótesis %: Principiante no se diferencia por objetivo ni fase', p_codigo;
    END IF;
    IF p_nivel <> 'Principiante' AND p_objetivo IS NULL THEN
        RAISE EXCEPTION 'Hipótesis %: Intermedio y Avanzado requieren objetivo', p_codigo;
    END IF;
    IF (p_fase IS NOT NULL) <> (p_nivel = 'Avanzado' AND p_objetivo IN ('Fuerza','Hipertrofia')) THEN
        RAISE EXCEPTION 'Hipótesis %: la fase solo aplica a Avanzado con Fuerza o Hipertrofia',
                        p_codigo;
    END IF;
    IF (p_nivel = 'Principiante') <> (p_dias_semana IS NOT NULL AND p_actividad IS NOT NULL)
       OR (p_nivel <> 'Principiante' AND (p_dias_semana IS NOT NULL OR p_actividad IS NOT NULL)) THEN
        RAISE EXCEPTION 'Hipótesis %: días por semana y actividad actual solo aplican, y son obligatorios, en Principiante',
                        p_codigo;
    END IF;
    IF btrim(COALESCE(p_descripcion, '')) = '' THEN
        RAISE EXCEPTION 'Hipótesis %: la descripción de la rutina es obligatoria', p_codigo;
    END IF;
    IF p_probabilidad_previa IS NULL OR p_probabilidad_previa <= 0 THEN
        RAISE EXCEPTION 'Hipótesis %: la probabilidad previa debe ser mayor que 0', p_codigo;
    END IF;

    INSERT INTO hipotesis (codigo, nivel, equipo, objetivo, fase, dias_semana, actividad,
                           descripcion_rutina, probabilidad_previa)
    VALUES (p_codigo, p_nivel, p_equipo, p_objetivo, p_fase, p_dias_semana, p_actividad,
            btrim(p_descripcion), p_probabilidad_previa)
    ON CONFLICT (codigo) DO UPDATE
       SET nivel = EXCLUDED.nivel, equipo = EXCLUDED.equipo, objetivo = EXCLUDED.objetivo,
           fase = EXCLUDED.fase, dias_semana = EXCLUDED.dias_semana,
           actividad = EXCLUDED.actividad, descripcion_rutina = EXCLUDED.descripcion_rutina,
           probabilidad_previa = EXCLUDED.probabilidad_previa
    RETURNING id_hipotesis INTO v_id;

    -- Si se modificó una hipótesis existente, sus gránulos deben seguir siendo coherentes
    SELECT fn_coherencia(id_hecho, v_id) INTO v_motivo
      FROM hechos_hipotesis WHERE id_hipotesis = v_id AND fn_coherencia(id_hecho, v_id) IS NOT NULL
     LIMIT 1;
    IF v_motivo IS NOT NULL THEN
        RAISE EXCEPTION 'Hipótesis %: el cambio deja gránulos incoherentes: %', p_codigo, v_motivo;
    END IF;
END;
$$;

CREATE PROCEDURE sp_eliminar_hipotesis(p_codigo VARCHAR)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE v_id INT;
BEGIN
    SELECT id_hipotesis INTO v_id FROM hipotesis WHERE codigo = p_codigo;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Hipótesis %: no existe', p_codigo;
    END IF;
    IF EXISTS (SELECT 1 FROM diagnostico_hipotesis WHERE id_hipotesis = v_id) THEN
        RAISE EXCEPTION 'Hipótesis %: aparece en diagnósticos del historial; no se puede eliminar',
                        p_codigo;
    END IF;
    DELETE FROM hechos_hipotesis WHERE id_hipotesis = v_id;
    DELETE FROM hipotesis WHERE id_hipotesis = v_id;
END;
$$;

-- ---------------------------------------------------------------------
-- Gránulos (hechos_hipotesis)
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_asociar_hecho_hipotesis(
    p_hecho VARCHAR, p_hipotesis VARCHAR, p_peso NUMERIC DEFAULT NULL)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE
    v_id_hecho INT;
    v_id_hip   INT;
    v_peso     NUMERIC;
    v_motivo   TEXT;
BEGIN
    SELECT he.id_hecho, COALESCE(p_peso, p.peso_base) INTO v_id_hecho, v_peso
      FROM hechos he JOIN preguntas p ON p.id_pregunta = he.id_pregunta
     WHERE he.codigo = p_hecho;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Gránulo %-%: el hecho % no existe', p_hecho, p_hipotesis, p_hecho;
    END IF;
    SELECT id_hipotesis INTO v_id_hip FROM hipotesis WHERE codigo = p_hipotesis;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Gránulo %-%: la hipótesis % no existe', p_hecho, p_hipotesis, p_hipotesis;
    END IF;
    IF v_peso <= 0 OR v_peso >= 1 THEN
        RAISE EXCEPTION 'Gránulo %-%: el peso debe estar entre 0 y 1 (exclusivos)',
                        p_hecho, p_hipotesis;
    END IF;
    v_motivo := fn_coherencia(v_id_hecho, v_id_hip);
    IF v_motivo IS NOT NULL THEN
        RAISE EXCEPTION 'Gránulo %-%: %', p_hecho, p_hipotesis, v_motivo;
    END IF;

    INSERT INTO hechos_hipotesis (id_hecho, id_hipotesis, peso)
    VALUES (v_id_hecho, v_id_hip, v_peso)
    ON CONFLICT (id_hecho, id_hipotesis) DO UPDATE SET peso = EXCLUDED.peso;
END;
$$;

CREATE PROCEDURE sp_desasociar_hecho_hipotesis(p_hecho VARCHAR, p_hipotesis VARCHAR)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE
    v_id_hecho INT;
    v_id_hip   INT;
BEGIN
    SELECT id_hecho INTO v_id_hecho FROM hechos WHERE codigo = p_hecho;
    SELECT id_hipotesis INTO v_id_hip FROM hipotesis WHERE codigo = p_hipotesis;
    DELETE FROM hechos_hipotesis WHERE id_hecho = v_id_hecho AND id_hipotesis = v_id_hip;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Gránulo %-%: no existe', p_hecho, p_hipotesis;
    END IF;
    -- Toda hipótesis debe conservar el hecho que define su equipo
    IF NOT EXISTS (SELECT 1 FROM hechos_hipotesis hh
                     JOIN hechos he ON he.id_hecho = hh.id_hecho
                     JOIN preguntas p ON p.id_pregunta = he.id_pregunta
                    WHERE hh.id_hipotesis = v_id_hip AND p.atributo = 'equipo_disponible') THEN
        RAISE EXCEPTION 'Gránulo %-%: la hipótesis quedaría sin hecho de equipo', p_hecho, p_hipotesis;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------
-- Validador estructural de la base de conocimiento.
-- (La alcanzabilidad de cada hipótesis la comprueba el motor, Fase 2.)
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_validar_base()
RETURNS TABLE (prueba TEXT, resultado TEXT, detalle TEXT)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = se, pg_temp
AS $$
DECLARE v TEXT;
BEGIN
    SELECT string_agg(p.codigo, ', ') INTO v FROM preguntas p
     WHERE (SELECT count(*) FROM respuesta_pregunta r WHERE r.id_pregunta = p.id_pregunta) < 2;
    RETURN QUERY SELECT 'Cada pregunta tiene al menos 2 opciones',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Sin opciones: ' || v, '');

    SELECT string_agg(he.codigo, ', ') INTO v FROM hechos he
     WHERE NOT EXISTS (SELECT 1 FROM respuesta_pregunta r WHERE r.id_hecho = he.id_hecho);
    RETURN QUERY SELECT 'Cada hecho tiene su opción de respuesta',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Huérfanos: ' || v, '');

    SELECT string_agg(h.codigo, ', ') INTO v FROM hipotesis h
     WHERE NOT EXISTS (SELECT 1 FROM hechos_hipotesis hh
                         JOIN hechos he ON he.id_hecho = hh.id_hecho
                         JOIN preguntas p ON p.id_pregunta = he.id_pregunta
                        WHERE hh.id_hipotesis = h.id_hipotesis
                          AND p.atributo = 'equipo_disponible');
    RETURN QUERY SELECT 'Cada hipótesis tiene gránulos y hecho de equipo',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Incompletas: ' || v, '');

    SELECT string_agg(DISTINCT h.codigo || '/' || he.codigo, ', ') INTO v
      FROM hechos_hipotesis hh JOIN hipotesis h ON h.id_hipotesis = hh.id_hipotesis
      JOIN hechos he ON he.id_hecho = hh.id_hecho
     WHERE fn_coherencia(hh.id_hecho, hh.id_hipotesis) IS NOT NULL;
    RETURN QUERY SELECT 'Todos los gránulos son coherentes con su hipótesis',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Incoherentes: ' || v, '');

    WITH perfiles AS (
        SELECT h.codigo, string_agg(hh.id_hecho::TEXT, ',' ORDER BY hh.id_hecho) AS perfil
          FROM hipotesis h JOIN hechos_hipotesis hh ON hh.id_hipotesis = h.id_hipotesis
         GROUP BY h.codigo)
    SELECT string_agg(grupo, '; ') INTO v FROM (
        SELECT string_agg(codigo, '=' ORDER BY codigo) AS grupo
          FROM perfiles GROUP BY perfil HAVING count(*) > 1) d;
    RETURN QUERY SELECT 'No hay hipótesis indistinguibles (mismos hechos)',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Iguales: ' || v, '');

    SELECT string_agg(DISTINCT s, ', ') INTO v FROM (
        SELECT r.id_pregunta, s FROM respuesta_pregunta r, unnest(r.sinonimos) s
         GROUP BY r.id_pregunta, s HAVING count(DISTINCT r.id_hecho) > 1) d;
    RETURN QUERY SELECT 'Ningún sinónimo apunta a dos opciones de una pregunta',
        CASE WHEN v IS NULL THEN 'OK' ELSE 'FALLO' END, COALESCE('Ambiguos: ' || v, '');

    RETURN QUERY SELECT 'Totales', 'INFO',
        format('%s preguntas, %s hechos, %s opciones, %s hipótesis, %s gránulos',
               (SELECT count(*) FROM preguntas), (SELECT count(*) FROM hechos),
               (SELECT count(*) FROM respuesta_pregunta), (SELECT count(*) FROM hipotesis),
               (SELECT count(*) FROM hechos_hipotesis));
END;
$$;

-- ---------------------------------------------------------------------
-- Auditoría automática de la base de conocimiento y de los roles
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_auditar() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
BEGIN
    INSERT INTO auditoria (usuario_app, rol_bd, tabla, accion, antes, despues)
    VALUES (NULLIF(current_setting('app.correo', true), ''),
            COALESCE(NULLIF(current_setting('role', true), 'none'), session_user::TEXT),
            TG_TABLE_NAME, TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
    RETURN NULL;
END;
$$;

CREATE TRIGGER tr_auditar_preguntas AFTER INSERT OR UPDATE OR DELETE ON preguntas
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_hechos AFTER INSERT OR UPDATE OR DELETE ON hechos
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_respuestas AFTER INSERT OR UPDATE OR DELETE ON respuesta_pregunta
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_hipotesis AFTER INSERT OR UPDATE OR DELETE ON hipotesis
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_granulos AFTER INSERT OR UPDATE OR DELETE ON hechos_hipotesis
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_usuario_alta AFTER INSERT ON usuario
    FOR EACH ROW EXECUTE FUNCTION fn_auditar();
CREATE TRIGGER tr_auditar_usuario_rol AFTER UPDATE OF rol, activo ON usuario
    FOR EACH ROW WHEN (OLD.rol IS DISTINCT FROM NEW.rol OR OLD.activo IS DISTINCT FROM NEW.activo)
    EXECUTE FUNCTION fn_auditar();

-- ---------------------------------------------------------------------
-- Protección de la administración: nadie cambia su propio rol ni se
-- desactiva, y siempre queda al menos un administrador activo
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_proteger_administracion() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = se, pg_temp
AS $$
BEGIN
    IF NEW.id_usuario = fn_usuario_actual()
       AND (NEW.rol IS DISTINCT FROM OLD.rol OR NEW.activo IS DISTINCT FROM OLD.activo) THEN
        RAISE EXCEPTION 'No puede cambiar su propio rol ni desactivar su propia cuenta';
    END IF;
    IF OLD.rol = 'administrador' AND OLD.activo
       AND (NEW.rol <> 'administrador' OR NOT NEW.activo)
       AND NOT EXISTS (SELECT 1 FROM usuario
                        WHERE rol = 'administrador' AND activo
                          AND id_usuario <> OLD.id_usuario) THEN
        RAISE EXCEPTION 'Debe quedar al menos un administrador activo';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_proteger_administracion BEFORE UPDATE OF rol, activo ON usuario
    FOR EACH ROW EXECUTE FUNCTION fn_proteger_administracion();

-- ---------------------------------------------------------------------
-- Permisos de ejecución (PostgreSQL concede EXECUTE a PUBLIC por defecto)
-- ---------------------------------------------------------------------
REVOKE EXECUTE ON ALL FUNCTIONS  IN SCHEMA se FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA se FROM PUBLIC;

GRANT EXECUTE ON FUNCTION fn_usuario_actual() TO rol_usuario, rol_experto,
      rol_ingeniero_conocimiento, rol_administrador;
GRANT EXECUTE ON PROCEDURE
      sp_registrar_hecho(VARCHAR, VARCHAR, VARCHAR, VARCHAR, TEXT[], INT, VARCHAR),
      sp_eliminar_hecho(VARCHAR),
      sp_actualizar_pregunta(VARCHAR, VARCHAR, VARCHAR, NUMERIC, BOOLEAN),
      sp_registrar_hipotesis(VARCHAR, t_nivel, t_equipo, t_objetivo, t_fase, t_dias_semana,
                             t_actividad, TEXT, NUMERIC),
      sp_eliminar_hipotesis(VARCHAR),
      sp_asociar_hecho_hipotesis(VARCHAR, VARCHAR, NUMERIC),
      sp_desasociar_hecho_hipotesis(VARCHAR, VARCHAR)
   TO rol_ingeniero_conocimiento;
GRANT EXECUTE ON FUNCTION fn_validar_base() TO rol_ingeniero_conocimiento;
GRANT EXECUTE ON FUNCTION fn_coherencia(INT, INT) TO rol_ingeniero_conocimiento;
