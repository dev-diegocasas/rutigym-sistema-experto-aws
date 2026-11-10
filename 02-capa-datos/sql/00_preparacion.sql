-- =====================================================================
-- 00. Roles de la base y esquema "se" (usuario postgres; idempotente).
-- =====================================================================
SET client_min_messages = warning;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['se_owner','rol_usuario','rol_experto',
                             'rol_ingeniero_conocimiento','rol_administrador'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_lambda') THEN
        CREATE ROLE app_lambda LOGIN;
    END IF;
END $$;

-- El usuario maestro puede actuar como propietario para crear los objetos
GRANT se_owner TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;

-- Autenticación del motor por IAM (sin contraseña)
GRANT rds_iam TO app_lambda;

-- app_lambda NO hereda permisos: debe hacer SET ROLE al rol de quien llama
GRANT rol_usuario, rol_experto, rol_ingeniero_conocimiento, rol_administrador
   TO app_lambda WITH INHERIT FALSE, SET TRUE;

CREATE SCHEMA IF NOT EXISTS se AUTHORIZATION se_owner;
ALTER ROLE app_lambda SET search_path = se;
ALTER ROLE se_owner   SET search_path = se;
