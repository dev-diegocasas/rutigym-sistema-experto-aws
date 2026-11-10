-- =====================================================================
-- Rutigym · Sistema experto de rutinas de entrenamiento
-- Modelo relacional para MySQL Workbench (MySQL 8.0)
--
-- Uso: File > Import > Reverse Engineer MySQL Create Script...
--      (marcar "Place imported objects on a diagram")
--
-- Bloque 1 · Base de conocimiento (las 5 tablas núcleo):
--   preguntas  1 ── N  hechos
--   hechos     1 ── 1  respuesta_pregunta   (la pregunta se obtiene por el hecho)
--   hechos     N ── M  hipotesis            (resuelta con hechos_hipotesis = gránulos)
--
-- Bloque 2 · Sistema transaccional:
--   usuario    1 ── N  consulta
--   consulta   1 ── N  consulta_hecho          (memoria de trabajo)
--   hechos     1 ── N  consulta_hecho          (hecho afirmado; la pregunta sale del hecho)
--   consulta   1 ── N  diagnostico_hipotesis   (top 5)
--   hipotesis  1 ── N  diagnostico_hipotesis
--   consulta   1 ── N  traza_inferencia        (razonamiento, verificación y opiniones)
--
-- Sin relaciones redundantes ni ciclos de tres tablas: ninguna tabla guarda una
-- llave que ya se obtiene siguiendo otra relación.
-- Varios expertos opinan sobre una consulta: cada opinión es una fila de la traza
-- (tipo validacion_experto), única por experto, sin una tabla más.
-- La tabla técnica de auditoría del sistema no forma parte del modelo conceptual.
-- Equivale al esquema PostgreSQL desplegado en Aurora (02-capa-datos/sql).
-- =====================================================================

DROP SCHEMA IF EXISTS rutigym_se;
CREATE SCHEMA rutigym_se DEFAULT CHARACTER SET utf8mb4;
USE rutigym_se;

-- =====================================================================
-- 1. BASE DE CONOCIMIENTO
-- =====================================================================

-- Preguntas del cuestionario. Cada una indaga un atributo del perfil.
CREATE TABLE preguntas (
    id_pregunta  INT           NOT NULL AUTO_INCREMENT,
    codigo       VARCHAR(5)    NOT NULL COMMENT 'P1..P7',
    atributo     VARCHAR(40)   NOT NULL COMMENT 'tecnica_dominada, tiempo_entrenando, ...',
    texto        VARCHAR(300)  NOT NULL,
    ayuda        VARCHAR(300)  NULL,
    orden        INT           NOT NULL,
    peso_base    DECIMAL(4,3)  NOT NULL COMMENT 'Certeza por defecto de sus hechos',
    PRIMARY KEY (id_pregunta),
    UNIQUE KEY uq_preguntas_codigo   (codigo),
    UNIQUE KEY uq_preguntas_atributo (atributo),
    UNIQUE KEY uq_preguntas_orden    (orden),
    CONSTRAINT ck_preguntas_peso  CHECK (peso_base > 0 AND peso_base < 1),
    CONSTRAINT ck_preguntas_orden CHECK (orden > 0)
) ENGINE=InnoDB COMMENT='Base de conocimiento: preguntas del cuestionario';

-- Hechos: afirmaciones atómicas "atributo = valor".
CREATE TABLE hechos (
    id_hecho     INT           NOT NULL AUTO_INCREMENT,
    codigo       VARCHAR(6)    NOT NULL COMMENT 'HC01..HC19',
    id_pregunta  INT           NOT NULL,
    valor        VARCHAR(60)   NOT NULL,
    descripcion  VARCHAR(200)  NULL,
    PRIMARY KEY (id_hecho),
    UNIQUE KEY uq_hechos_codigo (codigo),
    UNIQUE KEY uq_hecho_pregunta_valor (id_pregunta, valor),
    CONSTRAINT fk_hechos_preguntas
        FOREIGN KEY (id_pregunta) REFERENCES preguntas (id_pregunta)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB COMMENT='Base de conocimiento: hechos (atributo = valor)';

-- Opciones de respuesta: cada opción establece exactamente un hecho.
-- No lleva id_pregunta: la pregunta se obtiene por hechos.id_pregunta.
CREATE TABLE respuesta_pregunta (
    id_respuesta INT           NOT NULL AUTO_INCREMENT,
    id_hecho     INT           NOT NULL,
    texto_opcion VARCHAR(120)  NOT NULL,
    sinonimos    JSON          NOT NULL COMMENT 'Frases que reconocen la opción en texto libre',
    orden        INT           NOT NULL COMMENT 'Orden de la opción dentro de su pregunta',
    PRIMARY KEY (id_respuesta),
    UNIQUE KEY uq_respuesta_hecho (id_hecho),
    CONSTRAINT fk_respuesta_hechos
        FOREIGN KEY (id_hecho) REFERENCES hechos (id_hecho)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='Base de conocimiento: opciones y sinónimos';

-- Hipótesis: rutinas que el sistema puede concluir (H01..H32).
CREATE TABLE hipotesis (
    id_hipotesis        INT           NOT NULL AUTO_INCREMENT,
    codigo              VARCHAR(5)    NOT NULL COMMENT 'H01..H32',
    nivel               ENUM('Principiante','Intermedio','Avanzado') NOT NULL,
    equipo              ENUM('Básico o en casa','Gimnasio completo') NOT NULL,
    objetivo            ENUM('Fuerza','Hipertrofia','Resistencia','Pérdida de grasa','Rendimiento deportivo') NULL,
    fase                ENUM('Volumen','Intensidad') NULL,
    dias_semana         ENUM('2 días','3 o más días') NULL COMMENT 'Solo Principiante',
    actividad           ENUM('Sedentario','Algo activo') NULL COMMENT 'Solo Principiante',
    descripcion_rutina  TEXT          NOT NULL,
    probabilidad_previa DECIMAL(5,4)  NOT NULL DEFAULT 1.0000,
    PRIMARY KEY (id_hipotesis),
    UNIQUE KEY uq_hipotesis_codigo (codigo),
    CONSTRAINT ck_hipotesis_previa CHECK (probabilidad_previa > 0)
) ENGINE=InnoDB COMMENT='Base de conocimiento: hipótesis (rutinas)';

-- Gránulos de conocimiento: relación N:M entre hechos e hipótesis.
CREATE TABLE hechos_hipotesis (
    id_hecho     INT           NOT NULL,
    id_hipotesis INT           NOT NULL,
    peso         DECIMAL(4,3)  NOT NULL COMMENT 'Certeza con que el hecho respalda la hipótesis',
    PRIMARY KEY (id_hecho, id_hipotesis),
    KEY ix_hechos_hipotesis_hipotesis (id_hipotesis),
    CONSTRAINT fk_granulo_hechos
        FOREIGN KEY (id_hecho) REFERENCES hechos (id_hecho)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_granulo_hipotesis
        FOREIGN KEY (id_hipotesis) REFERENCES hipotesis (id_hipotesis)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_granulo_peso CHECK (peso > 0 AND peso < 1)
) ENGINE=InnoDB COMMENT='Base de conocimiento: gránulos (hecho respalda hipótesis)';

-- =====================================================================
-- 2. SISTEMA TRANSACCIONAL
-- =====================================================================

-- Perfil del usuario, vinculado a su cuenta de Amazon Cognito.
CREATE TABLE usuario (
    id_usuario     INT           NOT NULL AUTO_INCREMENT,
    cognito_sub    VARCHAR(64)   NOT NULL,
    nombre         VARCHAR(120)  NOT NULL,
    alias          VARCHAR(30)   NOT NULL COMMENT 'Ej.: juan.p',
    correo         VARCHAR(150)  NOT NULL,
    rol            ENUM('usuario_final','experto','ingeniero_conocimiento','administrador')
                                 NOT NULL DEFAULT 'usuario_final',
    activo         TINYINT(1)    NOT NULL DEFAULT 1,
    fecha_registro DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_usuario),
    UNIQUE KEY uq_usuario_cognito (cognito_sub),
    UNIQUE KEY uq_usuario_alias   (alias),
    UNIQUE KEY uq_usuario_correo  (correo)
) ENGINE=InnoDB COMMENT='Transaccional: perfiles y roles';

-- Cada sesión del cuestionario.
CREATE TABLE consulta (
    id_consulta         INT           NOT NULL AUTO_INCREMENT,
    id_usuario          INT           NOT NULL,
    estado              ENUM('en_curso','terminada','abandonada') NOT NULL DEFAULT 'en_curso',
    fecha_inicio        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_fin           DATETIME      NULL,
    verificacion_formal VARCHAR(30)   NULL COMMENT 'VALID, INVALID, SATISFIABLE, IMPOSSIBLE...',
    fecha_verificacion  DATETIME      NULL,
    PRIMARY KEY (id_consulta),
    KEY ix_consulta_usuario (id_usuario, fecha_inicio),
    -- Una sola consulta abierta por perfil
    UNIQUE KEY ux_consulta_abierta ((CASE WHEN estado = 'en_curso' THEN id_usuario END)),
    CONSTRAINT fk_consulta_usuario
        FOREIGN KEY (id_usuario) REFERENCES usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_consulta_fin CHECK ((estado = 'en_curso') = (fecha_fin IS NULL))
) ENGINE=InnoDB COMMENT='Transaccional: consultas de cada perfil';

-- Memoria de trabajo: hechos que el usuario afirmó, en orden.
-- No lleva id_pregunta: la pregunta respondida se obtiene por el hecho.
CREATE TABLE consulta_hecho (
    id_consulta   INT           NOT NULL,
    paso          SMALLINT      NOT NULL,
    id_hecho      INT           NOT NULL,
    origen        ENUM('boton','texto_libre') NOT NULL DEFAULT 'boton',
    texto_usuario VARCHAR(300)  NULL COMMENT 'Frase escrita, si la hubo',
    fecha         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_consulta, paso),
    UNIQUE KEY uq_consulta_hecho (id_consulta, id_hecho),
    KEY ix_consulta_hecho_hecho (id_hecho),
    CONSTRAINT fk_ch_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta (id_consulta)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_ch_hechos
        FOREIGN KEY (id_hecho) REFERENCES hechos (id_hecho)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_ch_paso CHECK (paso > 0)
) ENGINE=InnoDB COMMENT='Transaccional: memoria de trabajo';

-- Resultado: las 5 hipótesis más probables de una consulta terminada.
CREATE TABLE diagnostico_hipotesis (
    id_consulta  INT           NOT NULL,
    posicion     SMALLINT      NOT NULL COMMENT '1..5',
    id_hipotesis INT           NOT NULL,
    probabilidad DECIMAL(6,5)  NOT NULL,
    PRIMARY KEY (id_consulta, posicion),
    UNIQUE KEY uq_diagnostico_hipotesis (id_consulta, id_hipotesis),
    KEY ix_diagnostico_hipotesis (id_hipotesis),
    CONSTRAINT fk_diag_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta (id_consulta)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_diag_hipotesis
        FOREIGN KEY (id_hipotesis) REFERENCES hipotesis (id_hipotesis)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_diag_posicion CHECK (posicion BETWEEN 1 AND 5),
    CONSTRAINT ck_diag_probabilidad CHECK (probabilidad >= 0 AND probabilidad <= 1)
) ENGINE=InnoDB COMMENT='Transaccional: top 5 de hipótesis';

-- Traza del razonamiento paso a paso.
CREATE TABLE traza_inferencia (
    id_traza    BIGINT        NOT NULL AUTO_INCREMENT,
    id_consulta INT           NOT NULL,
    paso        SMALLINT      NOT NULL,
    tipo        ENUM('respuesta','seleccion_pregunta','conclusion','verificacion_formal',
                     'validacion_experto') NOT NULL,
    detalle     JSON          NOT NULL COMMENT 'Opinión: {id_experto, de_acuerdo, comentario}',
    fecha       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_traza),
    KEY ix_traza_consulta (id_consulta, paso),
    -- Una opinión por experto y consulta
    UNIQUE KEY ux_traza_validacion (id_consulta,
        (CASE WHEN tipo = 'validacion_experto'
              THEN CAST(detalle->>'$.id_experto' AS UNSIGNED) END)),
    CONSTRAINT fk_traza_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta (id_consulta)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='Transaccional: razonamiento, verificación y opiniones de expertos';

-- =====================================================================
-- 3. MÉTODOS CLAVE (procedimientos, funciones y disparadores)
-- =====================================================================
DELIMITER $$

-- Ingeniero del conocimiento: registra un hecho y su opción de respuesta.
CREATE PROCEDURE sp_registrar_hecho(
    IN p_codigo VARCHAR(6), IN p_pregunta VARCHAR(5), IN p_valor VARCHAR(60),
    IN p_texto_opcion VARCHAR(120), IN p_sinonimos JSON, IN p_orden INT)
BEGIN
    DECLARE v_id_pregunta INT;
    DECLARE v_id_hecho INT;
    SELECT id_pregunta INTO v_id_pregunta FROM preguntas WHERE codigo = p_pregunta;
    IF v_id_pregunta IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La pregunta no existe';
    END IF;
    IF EXISTS (SELECT 1 FROM respuesta_pregunta r JOIN hechos h ON h.id_hecho = r.id_hecho
               WHERE h.id_pregunta = v_id_pregunta AND r.orden = p_orden) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Otra opción de la pregunta ya usa ese orden';
    END IF;
    INSERT INTO hechos (codigo, id_pregunta, valor) VALUES (p_codigo, v_id_pregunta, p_valor);
    SET v_id_hecho = LAST_INSERT_ID();
    INSERT INTO respuesta_pregunta (id_hecho, texto_opcion, sinonimos, orden)
    VALUES (v_id_hecho, p_texto_opcion, p_sinonimos, p_orden);
END$$

-- Ingeniero del conocimiento: registra una hipótesis (rutina).
CREATE PROCEDURE sp_registrar_hipotesis(
    IN p_codigo VARCHAR(5), IN p_nivel VARCHAR(20), IN p_equipo VARCHAR(30),
    IN p_objetivo VARCHAR(30), IN p_fase VARCHAR(20),
    IN p_dias VARCHAR(20), IN p_actividad VARCHAR(20), IN p_rutina TEXT)
BEGIN
    IF p_nivel = 'Principiante' AND (p_objetivo IS NOT NULL OR p_fase IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Principiante no se diferencia por objetivo ni fase';
    END IF;
    IF p_fase IS NOT NULL AND (p_nivel <> 'Avanzado' OR p_objetivo NOT IN ('Fuerza','Hipertrofia')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La fase solo aplica a Avanzado con Fuerza o Hipertrofia';
    END IF;
    INSERT INTO hipotesis (codigo, nivel, equipo, objetivo, fase, dias_semana, actividad, descripcion_rutina)
    VALUES (p_codigo, p_nivel, p_equipo, p_objetivo, p_fase, p_dias, p_actividad, p_rutina);
END$$

-- Ingeniero del conocimiento: crea o ajusta un gránulo (hecho -> hipótesis, peso).
CREATE PROCEDURE sp_asociar_hecho_hipotesis(
    IN p_hecho VARCHAR(6), IN p_hipotesis VARCHAR(5), IN p_peso DECIMAL(4,3))
BEGIN
    DECLARE v_id_hecho INT;
    DECLARE v_id_hipotesis INT;
    IF p_peso IS NULL OR p_peso <= 0 OR p_peso >= 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El peso debe estar entre 0 y 1';
    END IF;
    SELECT id_hecho INTO v_id_hecho FROM hechos WHERE codigo = p_hecho;
    SELECT id_hipotesis INTO v_id_hipotesis FROM hipotesis WHERE codigo = p_hipotesis;
    IF v_id_hecho IS NULL OR v_id_hipotesis IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El hecho o la hipótesis no existe';
    END IF;
    INSERT INTO hechos_hipotesis (id_hecho, id_hipotesis, peso)
    VALUES (v_id_hecho, v_id_hipotesis, p_peso)
    ON DUPLICATE KEY UPDATE peso = VALUES(peso);
END$$

-- Motor de inferencia: consulta granular, solo los gránulos de una pregunta.
CREATE PROCEDURE sp_granulos_por_pregunta(IN p_pregunta VARCHAR(5))
BEGIN
    SELECT p.codigo AS pregunta, h.codigo AS hecho, h.valor,
           hi.codigo AS hipotesis, hh.peso
    FROM hechos_hipotesis hh
    JOIN hechos h     ON h.id_hecho = hh.id_hecho
    JOIN preguntas p  ON p.id_pregunta = h.id_pregunta
    JOIN hipotesis hi ON hi.id_hipotesis = hh.id_hipotesis
    WHERE p.codigo = p_pregunta
    ORDER BY hi.codigo, h.codigo;
END$$

-- Motor de inferencia: gránulos que sustentan una hipótesis.
CREATE PROCEDURE sp_granulos_por_hipotesis(IN p_hipotesis VARCHAR(5))
BEGIN
    SELECT hi.codigo AS hipotesis, p.codigo AS pregunta, p.atributo,
           h.codigo AS hecho, h.valor, hh.peso
    FROM hipotesis hi
    JOIN hechos_hipotesis hh ON hh.id_hipotesis = hi.id_hipotesis
    JOIN hechos h            ON h.id_hecho = hh.id_hecho
    JOIN preguntas p         ON p.id_pregunta = h.id_pregunta
    WHERE hi.codigo = p_hipotesis
    ORDER BY p.orden, h.codigo;
END$$

-- Validador de la base: cuenta hipótesis sin gránulos o sin hecho de equipo.
CREATE FUNCTION fn_validar_base() RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_errores INT DEFAULT 0;
    SELECT COUNT(*) INTO v_errores
    FROM hipotesis hi
    WHERE NOT EXISTS (
        SELECT 1 FROM hechos_hipotesis hh
        JOIN hechos h    ON h.id_hecho = hh.id_hecho
        JOIN preguntas p ON p.id_pregunta = h.id_pregunta
        WHERE hh.id_hipotesis = hi.id_hipotesis AND p.atributo = 'equipo_disponible');
    RETURN v_errores;
END$$

-- Una consulta cerrada no se puede reabrir.
CREATE TRIGGER tr_estado_consulta BEFORE UPDATE ON consulta
FOR EACH ROW
BEGIN
    IF OLD.estado <> 'en_curso' AND NEW.estado <> OLD.estado THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Una consulta cerrada no se puede reabrir';
    END IF;
END$$

-- Una sola respuesta por pregunta en cada consulta (la pregunta sale del hecho).
CREATE TRIGGER tr_una_respuesta_por_pregunta BEFORE INSERT ON consulta_hecho
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1
               FROM consulta_hecho ch
               JOIN hechos h_prev ON h_prev.id_hecho = ch.id_hecho
               JOIN hechos h_new  ON h_new.id_hecho  = NEW.id_hecho
               WHERE ch.id_consulta = NEW.id_consulta
                 AND h_prev.id_pregunta = h_new.id_pregunta) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Esa pregunta ya se respondió en esta consulta';
    END IF;
END$$

-- La verificación formal con resultado lógico es definitiva.
CREATE TRIGGER tr_verificacion_definitiva BEFORE UPDATE ON consulta
FOR EACH ROW FOLLOWS tr_estado_consulta
BEGIN
    IF OLD.verificacion_formal IN ('VALID','INVALID','SATISFIABLE','IMPOSSIBLE')
       AND NOT (NEW.verificacion_formal <=> OLD.verificacion_formal) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La verificación formal ya es definitiva';
    END IF;
END$$

-- La opinión del experto: solo sobre consultas terminadas y de un usuario con rol experto.
CREATE TRIGGER tr_opinion_experto BEFORE INSERT ON traza_inferencia
FOR EACH ROW
BEGIN
    IF NEW.tipo = 'validacion_experto' THEN
        IF NOT EXISTS (SELECT 1 FROM consulta WHERE id_consulta = NEW.id_consulta AND estado = 'terminada') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se pueden validar consultas terminadas';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM usuario
                       WHERE id_usuario = CAST(NEW.detalle->>'$.id_experto' AS UNSIGNED) AND rol = 'experto') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo un experto puede validar la consulta';
        END IF;
    END IF;
END$$

DELIMITER ;
