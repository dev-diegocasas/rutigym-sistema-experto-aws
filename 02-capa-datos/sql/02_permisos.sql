-- =====================================================================
-- 02. Permisos por rol y seguridad por fila (RLS). Ejecutar como se_owner.
-- =====================================================================
SET search_path = se;

REVOKE ALL ON ALL TABLES IN SCHEMA se FROM PUBLIC;
GRANT USAGE ON SCHEMA se TO rol_usuario, rol_experto, rol_ingeniero_conocimiento,
                             rol_administrador;

-- Usuario actual de la aplicación (NULL si no está fijado)
CREATE FUNCTION fn_usuario_actual() RETURNS INT
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.id_usuario', true), '')::INT
$$;

-- ---------------------------------------------------------------------
-- Base de conocimiento: todos consultan; el ingeniero la cambia solo con procedimientos.
-- ---------------------------------------------------------------------
GRANT SELECT ON preguntas, hechos, respuesta_pregunta, hipotesis, hechos_hipotesis
   TO rol_usuario, rol_experto, rol_ingeniero_conocimiento, rol_administrador;

-- ---------------------------------------------------------------------
-- usuario
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT ON usuario TO rol_usuario;
GRANT UPDATE (nombre) ON usuario TO rol_usuario;
-- Experto e ingeniero ven solo alias y rol (nunca nombre ni correo)
GRANT SELECT (id_usuario, alias, rol) ON usuario TO rol_experto, rol_ingeniero_conocimiento;
GRANT SELECT ON usuario TO rol_administrador;
GRANT UPDATE (rol, activo) ON usuario TO rol_administrador;
-- El administrador registra en la base los perfiles que crea en Cognito
GRANT INSERT ON usuario TO rol_administrador;

ALTER TABLE usuario ENABLE ROW LEVEL SECURITY;
CREATE POLICY usuario_propio ON usuario FOR ALL TO rol_usuario
    USING (id_usuario = fn_usuario_actual()
           OR cognito_sub = current_setting('app.cognito_sub', true))
    WITH CHECK (rol = 'usuario_final'
                AND cognito_sub = current_setting('app.cognito_sub', true));
CREATE POLICY usuario_lectura ON usuario FOR SELECT
    TO rol_experto, rol_ingeniero_conocimiento, rol_administrador USING (true);
CREATE POLICY usuario_admin_modifica ON usuario FOR UPDATE TO rol_administrador
    USING (true)
    WITH CHECK (true);
CREATE POLICY usuario_admin_crea ON usuario FOR INSERT TO rol_administrador
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- consulta y sus tablas hijas
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT ON consulta TO rol_usuario;
GRANT UPDATE (estado, fecha_fin) ON consulta TO rol_usuario;
GRANT SELECT ON consulta TO rol_experto, rol_ingeniero_conocimiento, rol_administrador;
-- Verificación formal (Automated Reasoning): la lanzan experto e ingeniero
GRANT UPDATE (verificacion_formal, fecha_verificacion) ON consulta
   TO rol_experto, rol_ingeniero_conocimiento;

GRANT SELECT, INSERT ON consulta_hecho, diagnostico_hipotesis TO rol_usuario;
GRANT SELECT ON consulta_hecho, diagnostico_hipotesis
   TO rol_experto, rol_ingeniero_conocimiento, rol_administrador;
GRANT SELECT, INSERT ON traza_inferencia TO rol_usuario;
GRANT SELECT ON traza_inferencia TO rol_experto, rol_ingeniero_conocimiento, rol_administrador;
GRANT INSERT ON traza_inferencia TO rol_experto, rol_ingeniero_conocimiento;

ALTER TABLE consulta ENABLE ROW LEVEL SECURITY;
CREATE POLICY consulta_propia ON consulta FOR ALL TO rol_usuario
    USING (id_usuario = fn_usuario_actual())
    WITH CHECK (id_usuario = fn_usuario_actual());
CREATE POLICY consulta_lectura ON consulta FOR SELECT
    TO rol_experto, rol_ingeniero_conocimiento, rol_administrador USING (true);
CREATE POLICY consulta_verificacion ON consulta FOR UPDATE
    TO rol_experto, rol_ingeniero_conocimiento USING (true) WITH CHECK (true);

-- Las tablas hijas heredan la restricción: la subconsulta sobre consulta
-- ya está filtrada por la política anterior
ALTER TABLE consulta_hecho ENABLE ROW LEVEL SECURITY;
CREATE POLICY consulta_hecho_acceso ON consulta_hecho FOR ALL
    USING (EXISTS (SELECT 1 FROM consulta c WHERE c.id_consulta = consulta_hecho.id_consulta))
    WITH CHECK (EXISTS (SELECT 1 FROM consulta c
                        WHERE c.id_consulta = consulta_hecho.id_consulta
                          AND c.estado = 'en_curso'));

ALTER TABLE diagnostico_hipotesis ENABLE ROW LEVEL SECURITY;
CREATE POLICY diagnostico_acceso ON diagnostico_hipotesis FOR ALL
    USING (EXISTS (SELECT 1 FROM consulta c
                   WHERE c.id_consulta = diagnostico_hipotesis.id_consulta))
    WITH CHECK (EXISTS (SELECT 1 FROM consulta c
                        WHERE c.id_consulta = diagnostico_hipotesis.id_consulta));

ALTER TABLE traza_inferencia ENABLE ROW LEVEL SECURITY;
CREATE POLICY traza_acceso ON traza_inferencia FOR ALL
    USING (EXISTS (SELECT 1 FROM consulta c WHERE c.id_consulta = traza_inferencia.id_consulta))
    WITH CHECK (EXISTS (SELECT 1 FROM consulta c
                        WHERE c.id_consulta = traza_inferencia.id_consulta));

-- ---------------------------------------------------------------------
-- Opinión del experto: fila de la traza (tipo validacion_experto), una por experto
-- ---------------------------------------------------------------------
GRANT UPDATE (detalle, fecha) ON traza_inferencia TO rol_experto;
-- El usuario final no ve las opiniones del experto sobre su consulta
CREATE POLICY traza_sin_opiniones ON traza_inferencia AS RESTRICTIVE FOR SELECT TO rol_usuario
    USING (tipo <> 'validacion_experto');
-- Solo el experto registra opiniones, y solo a su nombre
CREATE POLICY traza_opinion_alta ON traza_inferencia AS RESTRICTIVE FOR INSERT
    TO rol_usuario, rol_experto, rol_ingeniero_conocimiento
    WITH CHECK (tipo <> 'validacion_experto'
                OR (current_user = 'rol_experto'
                    AND (detalle->>'id_experto')::INT = fn_usuario_actual()));
CREATE POLICY traza_opinion_cambio ON traza_inferencia AS RESTRICTIVE FOR UPDATE TO rol_experto
    USING (tipo = 'validacion_experto' AND (detalle->>'id_experto')::INT = fn_usuario_actual())
    WITH CHECK (tipo = 'validacion_experto' AND (detalle->>'id_experto')::INT = fn_usuario_actual());

-- ---------------------------------------------------------------------
-- auditoria: solo lectura para el administrador; la escriben triggers
-- ---------------------------------------------------------------------
GRANT SELECT ON auditoria TO rol_administrador;
