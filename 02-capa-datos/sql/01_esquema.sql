-- =====================================================================
-- 01. Esquema: base de conocimiento (5 tablas) + sistema transaccional (5) + auditoría técnica.
-- =====================================================================
SET client_encoding = 'UTF8';
SET search_path = se;

-- ---------------------------------------------------------------------
-- 0. DOMINIOS
-- ---------------------------------------------------------------------
CREATE TYPE t_nivel    AS ENUM ('Principiante','Intermedio','Avanzado');
CREATE TYPE t_equipo   AS ENUM ('Básico o en casa','Gimnasio completo');
CREATE TYPE t_objetivo AS ENUM ('Fuerza','Hipertrofia','Resistencia',
                                'Pérdida de grasa','Rendimiento deportivo');
CREATE TYPE t_fase     AS ENUM ('Volumen','Intensidad');
CREATE TYPE t_dias_semana AS ENUM ('2 días','3 o más días');
CREATE TYPE t_actividad   AS ENUM ('Sedentario','Algo activo');
CREATE TYPE t_rol_sistema     AS ENUM ('usuario_final','experto','ingeniero_conocimiento',
                                       'administrador');
CREATE TYPE t_estado_consulta AS ENUM ('en_curso','terminada','abandonada');
CREATE TYPE t_origen_respuesta AS ENUM ('boton','texto_libre');
CREATE TYPE t_tipo_traza      AS ENUM ('respuesta','seleccion_pregunta','conclusion',
                                       'verificacion_formal','validacion_experto');

-- =====================================================================
-- 1. BASE DE CONOCIMIENTO
-- =====================================================================

-- Preguntas del cuestionario. Cada una indaga un atributo del perfil.
-- peso_base: certeza por defecto con la que un hecho de esta pregunta
-- respalda una hipótesis (definida por el experto).
CREATE TABLE preguntas (
    id_pregunta  INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo       VARCHAR(5)   NOT NULL UNIQUE,                 -- P1..P5
    atributo     VARCHAR(40)  NOT NULL UNIQUE
                 CHECK (atributo ~ '^[a-z_]+$'),
    texto        VARCHAR(300) NOT NULL,
    ayuda        VARCHAR(300) NULL,                            -- aclaración no técnica
    orden        INT          NOT NULL UNIQUE CHECK (orden > 0),
    peso_base    NUMERIC(4,3) NOT NULL CHECK (peso_base > 0 AND peso_base < 1)
);

-- Hechos: afirmaciones atómicas "atributo = valor" sobre el usuario.
CREATE TABLE hechos (
    id_hecho     INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo       VARCHAR(6)   NOT NULL UNIQUE,                 -- HC01..
    id_pregunta  INT          NOT NULL REFERENCES preguntas(id_pregunta),
    valor        VARCHAR(60)  NOT NULL,
    descripcion  VARCHAR(200) NULL,
    CONSTRAINT uq_hecho_pregunta_valor UNIQUE (id_pregunta, valor)
);

-- Opciones de respuesta de cada pregunta. Cada opción establece un hecho.
-- sinonimos: expresiones en lenguaje natural que Amazon Lex usa para
-- reconocer la opción cuando el usuario escribe texto libre.
CREATE TABLE respuesta_pregunta (
    id_respuesta INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_hecho     INT          NOT NULL UNIQUE,                 -- la pregunta se obtiene por el hecho
    texto_opcion VARCHAR(120) NOT NULL,
    sinonimos    TEXT[]       NOT NULL DEFAULT '{}',
    orden        INT          NOT NULL CHECK (orden > 0),
    CONSTRAINT fk_respuesta_hecho FOREIGN KEY (id_hecho) REFERENCES hechos(id_hecho) ON DELETE CASCADE
);

-- Hipótesis: las rutinas que el sistema puede concluir.
CREATE TABLE hipotesis (
    id_hipotesis        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo              VARCHAR(5)   NOT NULL UNIQUE,          -- H01..H26
    nivel               t_nivel      NOT NULL,
    equipo              t_equipo     NOT NULL,
    objetivo            t_objetivo   NULL,
    fase                t_fase       NULL,
    dias_semana         t_dias_semana NULL,                    -- solo Principiante
    actividad           t_actividad  NULL,                     -- solo Principiante
    descripcion_rutina  TEXT         NOT NULL,
    probabilidad_previa NUMERIC(5,4) NOT NULL DEFAULT 1 CHECK (probabilidad_previa > 0)
);

-- Gránulos: hecho -> hipótesis con peso (certeza con que el hecho la respalda).
CREATE TABLE hechos_hipotesis (
    id_hecho     INT          NOT NULL REFERENCES hechos(id_hecho),
    id_hipotesis INT          NOT NULL REFERENCES hipotesis(id_hipotesis),
    peso         NUMERIC(4,3) NOT NULL CHECK (peso > 0 AND peso < 1),
    PRIMARY KEY (id_hecho, id_hipotesis)
);
CREATE INDEX ix_hechos_hipotesis_hipotesis ON hechos_hipotesis (id_hipotesis);

-- =====================================================================
-- 2. SISTEMA TRANSACCIONAL
-- =====================================================================

-- Perfil del usuario, vinculado a su cuenta de Amazon Cognito.
CREATE TABLE usuario (
    id_usuario     INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cognito_sub    VARCHAR(64)   NOT NULL UNIQUE,
    nombre         VARCHAR(120)  NOT NULL,
    alias          VARCHAR(30)   NOT NULL UNIQUE,              -- lo que ven experto e ingeniero
    correo         VARCHAR(150)  NOT NULL UNIQUE,
    rol            t_rol_sistema NOT NULL DEFAULT 'usuario_final',
    activo         BOOLEAN       NOT NULL DEFAULT TRUE,
    fecha_registro TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cada sesión del cuestionario.
CREATE TABLE consulta (
    id_consulta         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_usuario          INT               NOT NULL REFERENCES usuario(id_usuario),
    estado              t_estado_consulta NOT NULL DEFAULT 'en_curso',
    fecha_inicio        TIMESTAMPTZ       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_fin           TIMESTAMPTZ       NULL,
    verificacion_formal VARCHAR(30)       NULL,               -- VALID, INVALID... (Automated Reasoning)
    fecha_verificacion  TIMESTAMPTZ       NULL,
    CONSTRAINT ck_consulta_fin CHECK ((estado = 'en_curso') = (fecha_fin IS NULL))
);
CREATE INDEX ix_consulta_usuario ON consulta (id_usuario, fecha_inicio DESC);

-- Memoria de trabajo: hechos establecidos por el usuario, en orden.
CREATE TABLE consulta_hecho (
    id_consulta   INT                NOT NULL REFERENCES consulta(id_consulta) ON DELETE CASCADE,
    paso          SMALLINT           NOT NULL CHECK (paso > 0),
    id_hecho      INT                NOT NULL,                 -- la pregunta sale del hecho
    origen        t_origen_respuesta NOT NULL DEFAULT 'boton',
    texto_usuario VARCHAR(300)       NULL,                     -- frase interpretada por Lex
    fecha         TIMESTAMPTZ        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_consulta, paso),
    CONSTRAINT uq_consulta_hecho UNIQUE (id_consulta, id_hecho),  -- una por pregunta: tr_una_respuesta_por_pregunta
    CONSTRAINT fk_consulta_hecho FOREIGN KEY (id_hecho) REFERENCES hechos(id_hecho)
);

-- Resultado: las 5 hipótesis más probables de una consulta terminada.
CREATE TABLE diagnostico_hipotesis (
    id_consulta  INT          NOT NULL REFERENCES consulta(id_consulta) ON DELETE CASCADE,
    posicion     SMALLINT     NOT NULL CHECK (posicion BETWEEN 1 AND 5),
    id_hipotesis INT          NOT NULL REFERENCES hipotesis(id_hipotesis),
    probabilidad NUMERIC(6,5) NOT NULL CHECK (probabilidad >= 0 AND probabilidad <= 1),
    PRIMARY KEY (id_consulta, posicion),
    CONSTRAINT uq_diagnostico_hipotesis UNIQUE (id_consulta, id_hipotesis)
);

-- Traza del razonamiento: qué consultó el motor y qué concluyó en cada paso.
CREATE TABLE traza_inferencia (
    id_traza    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_consulta INT          NOT NULL REFERENCES consulta(id_consulta) ON DELETE CASCADE,
    paso        SMALLINT     NOT NULL,
    tipo        t_tipo_traza NOT NULL,
    detalle     JSONB        NOT NULL,
    fecha       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_traza_consulta ON traza_inferencia (id_consulta, paso);
-- Opinión del experto: un registro por experto y consulta (varios expertos, sin tabla extra)
CREATE UNIQUE INDEX ux_traza_validacion ON traza_inferencia (id_consulta, ((detalle->>'id_experto')::INT))
    WHERE tipo = 'validacion_experto';

-- Registro técnico de cambios (lo llenan triggers). Fuera del modelo conceptual.
CREATE TABLE auditoria (
    id_auditoria BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usuario_app  VARCHAR(150) NULL,      -- correo del usuario de la aplicación
    rol_bd       VARCHAR(63)  NOT NULL,  -- rol de base de datos activo
    tabla        VARCHAR(40)  NOT NULL,
    accion       VARCHAR(10)  NOT NULL,
    antes        JSONB        NULL,
    despues      JSONB        NULL
);
CREATE INDEX ix_auditoria_fecha ON auditoria (fecha DESC);
