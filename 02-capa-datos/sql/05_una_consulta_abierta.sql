-- =====================================================================
-- 05. Una sola consulta abierta por perfil; una consulta cerrada no se reabre. Idempotente.
-- =====================================================================
SET search_path = se;

-- Si ya hubiera perfiles con varias consultas abiertas, se conserva la más reciente
UPDATE consulta SET estado = 'abandonada', fecha_fin = CURRENT_TIMESTAMP
 WHERE estado = 'en_curso'
   AND id_consulta NOT IN (SELECT max(id_consulta) FROM consulta
                            WHERE estado = 'en_curso' GROUP BY id_usuario);

CREATE UNIQUE INDEX IF NOT EXISTS ux_consulta_abierta
    ON consulta (id_usuario) WHERE estado = 'en_curso';

CREATE OR REPLACE FUNCTION fn_estado_consulta() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = se, pg_temp
AS $$
BEGIN
    IF OLD.estado <> 'en_curso' AND NEW.estado IS DISTINCT FROM OLD.estado THEN
        RAISE EXCEPTION 'La consulta ya está cerrada (%); no puede cambiar de estado', OLD.estado;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE EXECUTE ON FUNCTION fn_estado_consulta() FROM PUBLIC;

DROP TRIGGER IF EXISTS tr_estado_consulta ON consulta;
CREATE TRIGGER tr_estado_consulta BEFORE UPDATE OF estado ON consulta
    FOR EACH ROW EXECUTE FUNCTION fn_estado_consulta();
