-- =====================================================================
-- 07. Modelo sin relaciones redundantes y opiniones de varios expertos en la traza.
-- Idempotente. Ejecutar SIN -1 y luego volver a ejecutar 03_procedimientos.sql.
-- =====================================================================
SET search_path = se;

ALTER TYPE t_tipo_traza ADD VALUE IF NOT EXISTS 'validacion_experto';

BEGIN;

-- Opciones de respuesta: llave foránea simple al hecho
ALTER TABLE respuesta_pregunta DROP CONSTRAINT IF EXISTS fk_respuesta_hecho;
ALTER TABLE respuesta_pregunta DROP CONSTRAINT IF EXISTS uq_respuesta_orden;
ALTER TABLE respuesta_pregunta DROP COLUMN IF EXISTS id_pregunta;
ALTER TABLE respuesta_pregunta ADD CONSTRAINT fk_respuesta_hecho
    FOREIGN KEY (id_hecho) REFERENCES hechos(id_hecho) ON DELETE CASCADE;

-- Memoria de trabajo: llave foránea simple al hecho
ALTER TABLE consulta_hecho DROP CONSTRAINT IF EXISTS fk_consulta_hecho;
ALTER TABLE consulta_hecho DROP CONSTRAINT IF EXISTS uq_consulta_pregunta;
ALTER TABLE consulta_hecho DROP COLUMN IF EXISTS id_pregunta;
ALTER TABLE consulta_hecho DROP CONSTRAINT IF EXISTS uq_consulta_hecho;
ALTER TABLE consulta_hecho ADD CONSTRAINT uq_consulta_hecho UNIQUE (id_consulta, id_hecho);
ALTER TABLE consulta_hecho ADD CONSTRAINT fk_consulta_hecho
    FOREIGN KEY (id_hecho) REFERENCES hechos(id_hecho);

ALTER TABLE hechos DROP CONSTRAINT IF EXISTS uq_hecho_pregunta_id;

-- Opiniones del experto: de validacion_experto a la traza
CREATE UNIQUE INDEX IF NOT EXISTS ux_traza_validacion
    ON traza_inferencia (id_consulta, ((detalle->>'id_experto')::INT))
    WHERE tipo = 'validacion_experto';

DO $$
BEGIN
    IF to_regclass('se.validacion_experto') IS NOT NULL THEN
        INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle, fecha)
        SELECT v.id_consulta,
               (SELECT COALESCE(max(paso), 0) FROM consulta_hecho ch WHERE ch.id_consulta = v.id_consulta),
               'validacion_experto',
               jsonb_build_object('id_experto', v.id_experto, 'de_acuerdo', v.de_acuerdo,
                                  'comentario', v.comentario),
               v.fecha
          FROM validacion_experto v
        ON CONFLICT DO NOTHING;
        DROP TABLE validacion_experto;
    END IF;
END;
$$;

-- Permisos y seguridad por fila de las opiniones
GRANT UPDATE (detalle, fecha) ON traza_inferencia TO rol_experto;
DROP POLICY IF EXISTS traza_sin_opiniones ON traza_inferencia;
CREATE POLICY traza_sin_opiniones ON traza_inferencia AS RESTRICTIVE FOR SELECT TO rol_usuario
    USING (tipo <> 'validacion_experto');
DROP POLICY IF EXISTS traza_opinion_alta ON traza_inferencia;
CREATE POLICY traza_opinion_alta ON traza_inferencia AS RESTRICTIVE FOR INSERT
    TO rol_usuario, rol_experto, rol_ingeniero_conocimiento
    WITH CHECK (tipo <> 'validacion_experto'
                OR (current_user = 'rol_experto'
                    AND (detalle->>'id_experto')::INT = fn_usuario_actual()));
DROP POLICY IF EXISTS traza_opinion_cambio ON traza_inferencia;
CREATE POLICY traza_opinion_cambio ON traza_inferencia AS RESTRICTIVE FOR UPDATE TO rol_experto
    USING (tipo = 'validacion_experto' AND (detalle->>'id_experto')::INT = fn_usuario_actual())
    WITH CHECK (tipo = 'validacion_experto' AND (detalle->>'id_experto')::INT = fn_usuario_actual());

COMMIT;
