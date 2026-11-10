/* Sistema experto de rutinas · aplicación web (sin dependencias externas)
   Partes: utilidades · sesión (Cognito) · API · enrutador · vistas por rol. */
"use strict";
(() => {
  const CFG = window.SE_CONFIG || {};
  const vista = document.getElementById("vista");

  /* ============================================================ utilidades */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (p) => (Number(p) * 100).toFixed(1).replace(".", ",") + " %";
  const num = (n) => Number(n).toLocaleString("es-CO");
  const fecha = (s) => s ? new Date(String(s).replace(" ", "T")).toLocaleString("es-CO",
    { dateStyle: "medium", timeStyle: "short" }) : "";
  const decimal = (v) => String(v).replace(".", ",");

  function aviso(texto, tipo = "ok", ms = 4500) {
    const el = document.createElement("div");
    el.className = `aviso ${tipo}`;
    el.textContent = texto;
    $("#avisos").append(el);
    if (ms) setTimeout(() => el.remove(), ms);
    return el;
  }

  function anchoBarras(raiz = document) {
    // Los anchos se fijan desde JavaScript para cumplir la política de seguridad (sin estilos en línea)
    $$("[data-ancho]", raiz).forEach((i) => {
      const v = Math.max(0, Math.min(100, Number(i.dataset.ancho) * 100));
      requestAnimationFrame(() => i.style.setProperty("width", v + "%"));
    });
  }

  const EQUIPO = { "Gimnasio completo": "en gimnasio", "Básico o en casa": "en casa" };
  function nombreHipotesis(h) {
    return `${h.nivel} ${EQUIPO[h.equipo] || ""}`.trim();
  }
  function detalleHipotesis(h) {
    const partes = [h.objetivo, h.fase && `fase de ${h.fase.toLowerCase()}`,
      h.dias_semana && `${h.dias_semana} por semana`, h.actividad && h.actividad.toLowerCase()];
    return partes.filter(Boolean).join(", ");
  }

  /* ============================================================ sesión (Amazon Cognito) */
  const CLAVE = "se.sesion";
  const Sesion = {
    get() { try { return JSON.parse(sessionStorage.getItem(CLAVE)); } catch { return null; } },
    set(v) { sessionStorage.setItem(CLAVE, JSON.stringify(v)); },
    limpiar() { sessionStorage.removeItem(CLAVE); },
  };

  const MENSAJES_COGNITO = {
    NotAuthorizedException: "Correo o contraseña incorrectos.",
    UserNotFoundException: "Correo o contraseña incorrectos.",
    UsernameExistsException: "Ya existe una cuenta con ese correo.",
    InvalidPasswordException: "La contraseña debe tener al menos 10 caracteres, con mayúscula, minúscula, número y símbolo.",
    CodeMismatchException: "El código no es correcto.",
    ExpiredCodeException: "El código venció. Pide uno nuevo.",
    LimitExceededException: "Demasiados intentos. Espera unos minutos y vuelve a intentarlo.",
    TooManyRequestsException: "Demasiados intentos. Espera unos minutos y vuelve a intentarlo.",
    InvalidParameterException: "Revisa los datos ingresados.",
    CodeDeliveryFailureException: "No fue posible enviar el código a ese correo.",
  };

  async function cognito(accion, cuerpo) {
    const r = await fetch(CFG.cognitoUrl || `https://cognito-idp.${CFG.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": `AWSCognitoIdentityProviderService.${accion}` },
      body: JSON.stringify(cuerpo),
    });
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) {
      const codigo = String(datos.__type || "").split("#").pop();
      const e = new Error(MENSAJES_COGNITO[codigo] || datos.message || "No fue posible completar la operación.");
      e.codigo = codigo;
      throw e;
    }
    return datos;
  }

  function guardarTokens(r, correo) {
    const previa = Sesion.get() || {};
    Sesion.set({ id: r.IdToken, refresh: r.RefreshToken || previa.refresh,
                 exp: Date.now() + r.ExpiresIn * 1000, correo: correo || previa.correo });
  }

  async function iniciarSesion(correo, clave) {
    const r = await cognito("InitiateAuth", { ClientId: CFG.cliente, AuthFlow: "USER_PASSWORD_AUTH",
      AuthParameters: { USERNAME: correo, PASSWORD: clave } });
    if (r.ChallengeName) return r;
    guardarTokens(r.AuthenticationResult, correo);
    return null;
  }

  async function refrescar() {
    const s = Sesion.get();
    if (!s || !s.refresh) throw new Error("sin sesión");
    const r = await cognito("InitiateAuth", { ClientId: CFG.cliente, AuthFlow: "REFRESH_TOKEN_AUTH",
      AuthParameters: { REFRESH_TOKEN: s.refresh } });
    guardarTokens(r.AuthenticationResult);
  }

  function cerrarSesion(mensaje) {
    const s = Sesion.get();
    if (s && s.refresh) {
      cognito("RevokeToken", { ClientId: CFG.cliente, Token: s.refresh }).catch(() => {});
    }
    Sesion.limpiar();
    estado.perfil = null;
    estado.base = null;
    if (mensaje) aviso(mensaje, "pendiente", 6000);
    if (location.hash !== "#/acceso") location.hash = "#/acceso";
    else iniciar();
  }

  /* ============================================================ API del sistema experto */
  const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));

  async function api(metodo, ruta, cuerpo, reintento = true) {
    let s = Sesion.get();
    if (s && Date.now() > s.exp - 60000) { await refrescar().catch(() => {}); s = Sesion.get(); }
    const lento = setTimeout(() => {
      estado.avisoLento = aviso("Preparando el sistema… la primera respuesta del día puede tardar hasta un minuto.",
        "pendiente", 0);
    }, 2500);
    let r;
    try {
      // Reintentos: 503 significa que la base se está reanudando (respuesta propia del
      // motor, segura de repetir). Un fallo de red solo se repite en lecturas (GET),
      // para no duplicar una consulta o una respuesta.
      for (let intento = 0; ; intento++) {
        try {
          r = await fetch(CFG.api + ruta, {
            method: metodo,
            headers: { "Content-Type": "application/json", ...(s ? { Authorization: `Bearer ${s.id}` } : {}) },
            body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
          });
        } catch {
          if (metodo === "GET" && intento < 3) { await esperar(4000); continue; }
          throw new Error("No hay conexión con el servicio. Revisa tu conexión a internet e intenta de nuevo.");
        }
        if ((r.status === 503 || r.status === 504) && intento < 4) { await esperar(3000); continue; }
        break;
      }
    } finally {
      clearTimeout(lento);
      if (estado.avisoLento) { estado.avisoLento.remove(); estado.avisoLento = null; }
    }
    if (r.status === 401 && reintento) {
      try { await refrescar(); return api(metodo, ruta, cuerpo, false); }
      catch { cerrarSesion("Tu sesión terminó. Inicia sesión de nuevo."); throw new Error("Sesión terminada"); }
    }
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) {
      const e = new Error(datos.error || datos.message || `El servicio respondió con un error (${r.status}).`);
      e.estado = r.status;
      e.datos = datos;
      throw e;
    }
    return datos;
  }

  function despertar() {
    fetch(CFG.api + "/despertar", { method: "POST" }).catch(() => {});
  }

  /* ============================================================ enrutador */
  const estado = { perfil: null, base: null, avisoLento: null, ocupado: false };

  const MENU = {
    usuario_final: [["#/consulta", "Nueva consulta"], ["#/mis-consultas", "Mis consultas"]],
    experto: [["#/consultas", "Consultas"], ["#/metricas", "Métricas"], ["#/conocimiento", "Base de conocimiento"]],
    ingeniero_conocimiento: [["#/conocimiento", "Base de conocimiento"], ["#/consultas", "Consultas"],
      ["#/metricas", "Métricas"]],
    administrador: [["#/usuarios", "Usuarios"], ["#/auditoria", "Auditoría"], ["#/consultas", "Consultas"],
      ["#/metricas", "Métricas"]],
  };
  const NOMBRE_ROL = { usuario_final: "Usuario", experto: "Experto", ingeniero_conocimiento: "Ingeniero del conocimiento",
    administrador: "Administrador" };

  function pintarBarra() {
    const p = estado.perfil;
    $("#barra").hidden = !p;
    if (!p) { document.body.classList.remove("con-barra"); return; }
    $("#quien").innerHTML = `${esc(p.nombre)}<small>${esc(NOMBRE_ROL[p.rol])}</small>`;
    document.body.classList.add("con-barra");
    const actual = location.hash.split("/").slice(0, 2).join("/");
    $("#menu").innerHTML = MENU[p.rol].map(([h, t]) =>
      `<a href="${h}"${h === actual ? ' aria-current="page"' : ""}>${esc(t)}</a>`).join("");
  }

  // Lo más frecuente de cada rol, siempre a un clic
  const ACCION = {
    usuario_final: { texto: "Nueva consulta", ruta: "#/consulta", oculta: (r) => r[0] === "consulta" },
    experto: { texto: "Revisar pendientes", ruta: "#/consultas", filtro: "sin-verificar" },
    ingeniero_conocimiento: { texto: "Validar la base", ruta: "#/conocimiento/validacion",
      oculta: (r) => r[0] === "conocimiento" && r[1] === "validacion" },
    administrador: { texto: "Crear cuenta", ruta: "#/usuarios", crear: true },
  };
  function ponerAccionPrincipal(partes) {
    const a = ACCION[estado.perfil.rol];
    const cab = $(".encabezado", vista);
    if (!a || !cab || $(".accion-principal", vista) || (a.oculta && a.oculta(partes))) return;
    const enlace = document.createElement("a");
    enlace.className = "boton accion-principal";
    enlace.href = a.ruta;
    enlace.textContent = a.texto;
    enlace.addEventListener("click", (ev) => {
      if (a.filtro) sessionStorage.setItem("se.filtro", a.filtro);
      if (a.crear) sessionStorage.setItem("se.crear", "1");
      if (location.hash === a.ruta) { ev.preventDefault(); enrutar(); }
    });
    const acciones = $(":scope > .acciones", cab);
    (acciones || cab).append(enlace);
  }

  async function enrutar() {
    const partes = location.hash.replace(/^#\/?/, "").split("/");
    if (!estado.perfil) return iniciar();
    const rol = estado.perfil.rol;
    const inicio = MENU[rol][0][0];
    const permitido = (r) => MENU[rol].some(([h]) => h === "#/" + r) ||
      (r === "consultas" && partes[1]) || (r === "consulta" && rol === "usuario_final");
    if (!partes[0] || partes[0] === "acceso" || !permitido(partes[0])) { location.hash = inicio; return; }
    pintarBarra();
    vista.innerHTML = '<p class="cargando">Cargando…</p>';
    try {
      switch (partes[0]) {
        case "consulta": await vistaConsulta(partes[1]); break;
        case "mis-consultas": await vistaListaConsultas(true); break;
        case "consultas": partes[1] ? await vistaDetalle(partes[1]) : await vistaListaConsultas(false); break;
        case "metricas": await vistaMetricas(); break;
        case "conocimiento": await vistaConocimiento(partes[1] || "preguntas", partes[2]); break;
        case "usuarios": await vistaUsuarios(); break;
        case "auditoria": await vistaAuditoria(); break;
      }
      ponerAccionPrincipal(partes);
    } catch (e) {
      if (e.message !== "Sesión terminada") {
        vista.innerHTML = `<div class="superficie vacio"><p>${esc(e.message)}</p>
          <p class="acciones"><a class="boton claro" href="${inicio}">Volver al inicio</a></p></div>`;
      }
    }
    vista.focus({ preventScroll: true });
  }

  async function iniciar() {
    despertar();
    if (!Sesion.get()) { pintarBarra(); return vistaAcceso("ingresar"); }
    try {
      estado.perfil = await api("GET", "/perfil");
    } catch (e) {
      Sesion.limpiar();
      estado.perfil = null;
      pintarBarra();
      vistaAcceso("ingresar");
      aviso(e.message, "error", 7000);
      return;
    }
    if (!location.hash || location.hash === "#/acceso") location.hash = MENU[estado.perfil.rol][0][0];
    else enrutar();
  }

  /* ============================================================ acceso */
  function vistaAcceso(modo, datos = {}) {
    estado.perfil = null;
    pintarBarra();
    const pestanas = modo === "ingresar" || modo === "registrar";
    const formularios = {
      ingresar: `
        <form class="formulario" data-form="ingresar" novalidate>
          <label class="campo"><span>Correo</span>
            <input type="email" name="correo" autocomplete="username" required value="${esc(datos.correo)}"></label>
          <label class="campo"><span>Contraseña</span>
            <input type="password" name="clave" autocomplete="current-password" required></label>
          <div class="acciones"><button class="boton" type="submit">Iniciar sesión</button>
            <button class="boton sutil" type="button" data-ir="olvido">¿Olvidaste tu contraseña?</button></div>
        </form>`,
      registrar: `
        <form class="formulario" data-form="registrar" novalidate>
          <label class="campo"><span>Nombre</span>
            <input type="text" name="nombre" autocomplete="name" required maxlength="120"></label>
          <label class="campo"><span>Correo</span>
            <input type="email" name="correo" autocomplete="email" required></label>
          <label class="campo"><span>Contraseña</span>
            <input type="password" name="clave" autocomplete="new-password" required minlength="10" aria-describedby="politica">
            <small id="politica">Mínimo 10 caracteres, con mayúscula, minúscula, número y símbolo.</small></label>
          <button class="boton" type="submit">Crear cuenta</button>
        </form>`,
      confirmar: `
        <h2>Confirma tu correo</h2>
        <p class="secundario">Enviamos un código a <b>${esc(datos.correo)}</b>. Escríbelo para activar tu cuenta.</p>
        <form class="formulario" data-form="confirmar" novalidate>
          <label class="campo"><span>Código de verificación</span>
            <input type="text" name="codigo" inputmode="numeric" autocomplete="one-time-code" required></label>
          <div class="acciones"><button class="boton" type="submit">Confirmar correo</button>
            <button class="boton sutil" type="button" data-accion="reenviar">Reenviar código</button></div>
        </form>`,
      reto: `
        <h2>Define tu contraseña</h2>
        <p class="secundario">Es tu primer ingreso. Cambia la contraseña temporal por una propia.</p>
        <form class="formulario" data-form="reto" novalidate>
          <label class="campo"><span>Nueva contraseña</span>
            <input type="password" name="clave" autocomplete="new-password" required minlength="10">
            <small>Mínimo 10 caracteres, con mayúscula, minúscula, número y símbolo.</small></label>
          <button class="boton" type="submit">Guardar contraseña</button>
        </form>`,
      olvido: `
        <h2>Recupera tu contraseña</h2>
        <p class="secundario">Te enviaremos un código al correo de tu cuenta.</p>
        <form class="formulario" data-form="olvido" novalidate>
          <label class="campo"><span>Correo</span>
            <input type="email" name="correo" autocomplete="email" required value="${esc(datos.correo)}"></label>
          <div class="acciones"><button class="boton" type="submit">Enviar código</button>
            <button class="boton sutil" type="button" data-ir="ingresar">Volver</button></div>
        </form>`,
      restablecer: `
        <h2>Nueva contraseña</h2>
        <p class="secundario">Escribe el código que llegó a <b>${esc(datos.correo)}</b> y tu nueva contraseña.</p>
        <form class="formulario" data-form="restablecer" novalidate>
          <label class="campo"><span>Código</span>
            <input type="text" name="codigo" inputmode="numeric" autocomplete="one-time-code" required></label>
          <label class="campo"><span>Nueva contraseña</span>
            <input type="password" name="clave" autocomplete="new-password" required minlength="10"></label>
          <button class="boton" type="submit">Cambiar contraseña</button>
        </form>`,
    };
    vista.innerHTML = `
      <section class="acceso">
        <div class="acceso-texto">
          <p class="marca">Rutigym</p>
          <h1>Tu rutina de entrenamiento, con el criterio de un entrenador.</h1>
          <p>Respondes entre dos y cinco preguntas sobre tu técnica, tu tiempo entrenando, tu equipo y tu objetivo.
             Con cada respuesta el sistema consulta el conocimiento del experto y reordena las rutinas posibles
             hasta quedarse con la tuya.</p>
          <figure class="muestra" aria-hidden="true">
            <ol class="marcador pequeno">
              <li class="lider"><span class="puesto">1.º</span><span class="valor">33,3 %</span>
                <span class="nombre">Avanzado en gimnasio</span><span class="detalle">Fuerza, fase de intensidad</span>
                <span class="medidor"><i class="m33"></i></span></li>
              <li><span class="puesto">2.º</span><span class="valor">10,0 %</span>
                <span class="nombre">Avanzado en gimnasio</span><span class="detalle">Fuerza, fase de volumen</span>
                <span class="medidor"><i class="m10"></i></span></li>
              <li><span class="puesto">3.º</span><span class="valor">6,7 %</span>
                <span class="nombre">Avanzado en casa</span><span class="detalle">Fuerza, fase de intensidad</span>
                <span class="medidor"><i class="m7"></i></span></li>
            </ol>
            <figcaption>Así ves, mientras respondes, qué rutinas van ganando.</figcaption>
          </figure>
        </div>
        <div class="superficie acceso-caja">
          ${pestanas ? `<div class="pestanas" role="tablist">
            <button type="button" role="tab" aria-selected="${modo === "ingresar"}" data-ir="ingresar">Iniciar sesión</button>
            <button type="button" role="tab" aria-selected="${modo === "registrar"}" data-ir="registrar">Crear cuenta</button>
          </div>` : ""}
          ${formularios[modo]}
          <p class="aviso error" id="error-acceso" role="alert" hidden></p>
        </div>
      </section>`;

    const error = $("#error-acceso");
    const mostrarError = (m) => { error.textContent = m; error.hidden = false; };
    $$("[data-ir]", vista).forEach((b) => b.addEventListener("click", () =>
      vistaAcceso(b.dataset.ir, { correo: $("input[name=correo]", vista)?.value || datos.correo })));
    const reenviar = $("[data-accion=reenviar]", vista);
    if (reenviar) reenviar.addEventListener("click", async () => {
      try { await cognito("ResendConfirmationCode", { ClientId: CFG.cliente, Username: datos.correo });
        aviso("Enviamos un código nuevo."); } catch (e) { mostrarError(e.message); }
    });

    const form = $("form", vista);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      error.hidden = true;
      const f = Object.fromEntries(new FormData(form));
      const correo = (f.correo || datos.correo || "").trim().toLowerCase();
      const boton = $("button[type=submit]", form);
      boton.disabled = true;
      try {
        if (modo === "ingresar") {
          if (!correo || !f.clave) throw new Error("Escribe tu correo y tu contraseña.");
          const reto = await iniciarSesion(correo, f.clave);
          if (reto && reto.ChallengeName === "NEW_PASSWORD_REQUIRED") {
            return vistaAcceso("reto", { correo, sesion: reto.Session });
          }
          if (reto) throw new Error("Este tipo de verificación no está disponible en la aplicación.");
          return iniciar();
        }
        if (modo === "registrar") {
          if (!f.nombre.trim() || !correo || !f.clave) throw new Error("Completa todos los campos.");
          await cognito("SignUp", { ClientId: CFG.cliente, Username: correo, Password: f.clave,
            UserAttributes: [{ Name: "email", Value: correo }, { Name: "name", Value: f.nombre.trim() }] });
          return vistaAcceso("confirmar", { correo, clave: f.clave });
        }
        if (modo === "confirmar") {
          await cognito("ConfirmSignUp", { ClientId: CFG.cliente, Username: datos.correo,
            ConfirmationCode: f.codigo.trim() });
          if (datos.clave) { await iniciarSesion(datos.correo, datos.clave); return iniciar(); }
          aviso("Correo confirmado. Ya puedes iniciar sesión.");
          return vistaAcceso("ingresar", { correo: datos.correo });
        }
        if (modo === "reto") {
          const r = await cognito("RespondToAuthChallenge", { ClientId: CFG.cliente,
            ChallengeName: "NEW_PASSWORD_REQUIRED", Session: datos.sesion,
            ChallengeResponses: { USERNAME: datos.correo, NEW_PASSWORD: f.clave } });
          guardarTokens(r.AuthenticationResult, datos.correo);
          return iniciar();
        }
        if (modo === "olvido") {
          if (!correo) throw new Error("Escribe el correo de tu cuenta.");
          await cognito("ForgotPassword", { ClientId: CFG.cliente, Username: correo });
          return vistaAcceso("restablecer", { correo });
        }
        if (modo === "restablecer") {
          await cognito("ConfirmForgotPassword", { ClientId: CFG.cliente, Username: datos.correo,
            ConfirmationCode: f.codigo.trim(), Password: f.clave });
          aviso("Contraseña actualizada. Inicia sesión con la nueva.");
          return vistaAcceso("ingresar", { correo: datos.correo });
        }
      } catch (e) {
        if (e.codigo === "UserNotConfirmedException") return vistaAcceso("confirmar", { correo });
        mostrarError(e.message);
      } finally {
        boton.disabled = false;
      }
    });
    const primero = $("input", vista);
    if (primero) primero.focus();
  }

  /* ============================================================ piezas compartidas */
  const CORTO = { tecnica_dominada: "Técnica", tiempo_entrenando: "Tiempo entrenando", equipo_disponible: "Equipo",
    objetivo_principal: "Objetivo", fase_priorizada: "Fase", dias_semana: "Días por semana", actividad_actual: "Actividad" };

  // Marcador: las cinco rutinas más probables, la líder resaltada
  function htmlMarcador(ranking, conCodigo) {
    if (!ranking || !ranking.length) return '<p class="tenue">Sin datos todavía.</p>';
    return `<ol class="marcador">${ranking.map((h, i) => `
      <li class="${i === 0 ? "lider" : ""}" data-codigo="${esc(h.codigo)}">
        <span class="puesto">${i + 1}.º</span>
        <span class="valor">${pct(h.probabilidad)}</span>
        <span class="nombre">${esc(nombreHipotesis(h))}${conCodigo ? ` <small>${esc(h.codigo)}</small>` : ""}</span>
        <span class="detalle">${esc(detalleHipotesis(h))}</span>
        <span class="medidor" aria-hidden="true"><i data-ancho="${h.probabilidad}"></i></span>
      </li>`).join("")}</ol>`;
  }

  // Reemplaza el marcador y anima el cambio de puesto de cada rutina
  function actualizarMarcador(cont, ranking, conCodigo) {
    const antes = new Map($$("li[data-codigo]", cont).map((li) => [li.dataset.codigo, li.getBoundingClientRect()]));
    cont.innerHTML = htmlMarcador(ranking, conCodigo);
    anchoBarras(cont);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    $$("li[data-codigo]", cont).forEach((li) => {
      const a = antes.get(li.dataset.codigo);
      if (!a) return;
      const b = li.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) return;
      li.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration: 450, easing: "cubic-bezier(.2,.7,.2,1)" });
    });
  }

  function htmlRecorrido(hechos) {
    if (!hechos || !hechos.length) return '<li class="recorrido-vacio">Todavía no has respondido.</li>';
    return hechos.map((h) => `
      <li><span class="rec-preg">${esc(CORTO[h.atributo] || h.pregunta)}</span>
        <b>${esc(h.respuesta)}</b>${h.origen === "texto_libre" ? `<small>escribiste «${esc(h.texto_usuario)}»</small>` : ""}</li>`).join("");
  }

  function htmlResultado(d, acciones = true) {
    const r = d.rutina;
    return `
      <div class="resultado">
        <div>
          <p class="paso">Rutina recomendada, ${pct(r.probabilidad)}</p>
          <h2>${esc(nombreHipotesis(r))}${detalleHipotesis(r) ? `: ${esc(detalleHipotesis(r).toLowerCase())}` : ""}</h2>
          <p class="descripcion">${esc(r.descripcion_rutina)}</p>
          ${d.explicacion_ia ? `<p class="explicacion">${esc(d.explicacion_ia)}</p>` : ""}
          ${acciones ? `<div class="acciones resultado-acciones">
            <a class="boton" href="#/consulta" data-nueva>Hacer otra consulta</a>
            <a class="boton claro" href="#/mis-consultas">Ver mis consultas</a></div>` : ""}
        </div>
        <div>
          <h3>Por qué esta rutina</h3>
          <ul class="respaldo">${d.respaldo.map((h) => `
            <li><span>${esc(CORTO[h.atributo] || h.texto_pregunta)}: <b>${esc(h.respuesta)}</b></span>
                <span class="peso" title="Peso del hecho para esta rutina">${decimal(h.peso)}</span></li>`).join("")}</ul>
        </div>
      </div>`;
  }

  function htmlVerificacion(resultado, hipotesis, det, cuando) {
    det = det || {};
    const reglas = (det.reglas || []).join(", ");
    return `
      <p>${etiquetaVerificacion(resultado)} ${resultado === "VALID"
        ? `La rutina ${esc(hipotesis)} cumple ${reglas ? `la regla ${esc(reglas)}` : "las reglas"} de la política formal.`
        : resultado === "INVALID" ? `La rutina ${esc(hipotesis)} contradice ${reglas ? `la regla ${esc(reglas)}` : "las reglas del experto"}.`
        : esc(det.error || "El verificador no pudo concluir.")}</p>
      ${cuando ? `<p class="tenue">Verificada el ${esc(fecha(cuando))}</p>` : ""}
      ${(det.premisas || []).length ? `<details><summary>Ver la traducción a lógica formal</summary>
        <p class="tenue">Premisas</p>${det.premisas.map((x) => `<code>${esc(x)}</code>`).join(" ")}
        <p class="tenue">Afirmación</p>${(det.afirmaciones || []).map((x) => `<code>${esc(x)}</code>`).join(" ")}</details>` : ""}`;
  }

  const ETIQUETA_VERIF = { VALID: ["ok", "Válida"], INVALID: ["error", "Inválida"] };
  function etiquetaVerificacion(v) {
    if (!v) return '<span class="etiqueta">Sin verificar</span>';
    const [clase, texto] = ETIQUETA_VERIF[v] || ["pendiente", v];
    return `<span class="etiqueta ${clase}">${esc(texto)}</span>`;
  }
  const etiquetaEstado = (e) => e === "terminada" ? '<span class="etiqueta ok">Terminada</span>'
    : e === "abandonada" ? '<span class="etiqueta">Descartada</span>'
    : '<span class="etiqueta pendiente">En curso</span>';
  // Para el experto, el ingeniero y el administrador la numeración es de cada perfil
  const tituloConsulta = (e, propia) => `Consulta ${e.numero ?? e.id_consulta}${!propia && e.alias ? ` de ${e.alias}` : ""}`;

  /* ============================================================ usuario final: consulta */
  async function vistaConsulta(idConsulta) {
    let e;
    if (idConsulta) {
      e = await api("GET", `/consultas/${encodeURIComponent(idConsulta)}`);
      if (e.estado !== "en_curso") { location.hash = `#/consultas/${e.id_consulta}`; return; }
    } else {
      const { consultas } = await api("GET", "/consultas");
      // Solo puede haber una abierta: se continúa o se descarta antes de empezar otra
      const pendiente = consultas.find((c) => c.estado === "en_curso");
      vista.innerHTML = `
        <section class="inicio-consulta">
          <div>
            <h1>${pendiente ? "Tienes una consulta sin terminar." : "Encontremos la rutina que te corresponde."}</h1>
            ${pendiente ? `<p>La consulta ${esc(pendiente.numero)}, que empezaste el ${esc(fecha(pendiente.fecha_inicio))}, sigue abierta.
               Puedes seguirla donde la dejaste o descartarla y empezar otra. Si la descartas, sus respuestas
               quedan guardadas en Mis consultas, pero no genera rutina.</p>
            <div class="acciones">
              <a class="boton" href="#/consulta/${pendiente.id_consulta}">Continuar la consulta ${esc(pendiente.numero)}</a>
              <button class="boton claro" type="button" id="empezar" data-descartar>Descartarla y empezar otra</button>
            </div>`
            : `<p>Son entre dos y cinco preguntas. Puedes elegir una opción o escribir la respuesta con tus palabras;
               el sistema solo te pregunta lo que todavía puede cambiar el resultado.</p>
            <div class="acciones">
              <button class="boton" type="button" id="empezar">Empezar consulta</button>
            </div>`}
          </div>
          <ol class="que-pasa">
            <li><span>Responde la pregunta que aparece en el centro de la pantalla.</span></li>
            <li><span>Arriba verás cómo cambia la probabilidad de cada rutina.</span></li>
            <li><span>Al final recibes tu rutina, el porqué y las alternativas más cercanas.</span></li>
          </ol>
        </section>`;
      $("#empezar").addEventListener("click", async (ev) => {
        ev.target.disabled = true;
        try {
          const nueva = await api("POST", "/consultas",
            ev.target.hasAttribute("data-descartar") ? { descartar_pendiente: true } : {});
          history.replaceState(null, "", `#/consulta/${nueva.id_consulta}`);
          pintarConversacion(nueva);
        } catch (err) {
          // Otra pestaña dejó una consulta abierta: se muestra la elección
          if (err.estado === 409 && err.datos && err.datos.pendiente) { aviso(err.message, "error"); enrutar(); return; }
          aviso(err.message, "error"); ev.target.disabled = false;
        }
      });
      return;
    }
    pintarConversacion(e);
  }

  function pintarConversacion(e) {
    vista.innerHTML = `
      <div class="encabezado"><div><h1>Consulta ${esc(e.numero ?? e.id_consulta)}</h1>
        <p>Responde con calma: no hay respuestas buenas ni malas. Arriba ves qué rutinas te van quedando mejor.
           Si sales, la consulta queda guardada para seguirla después.</p></div>
        <div class="acciones" id="acciones-consulta"><button class="boton claro pequeno" type="button" id="descartar">Descartar consulta</button></div></div>
      <section aria-labelledby="t-marcador">
        <div class="titulo-marcador"><h2 id="t-marcador">Rutinas más probables</h2>
          <p>Cambian con cada respuesta</p></div>
        <div id="marcador"></div>
      </section>
      <section class="pregunta-zona" id="zona" aria-live="polite"></section>
      <section class="recorrido-zona" aria-labelledby="t-rec">
        <h2 id="t-rec">Tu recorrido</h2>
        <ol class="recorrido" id="recorrido"></ol>
      </section>`;
    const zona = $("#zona");
    // Datos que la persona adelantó al escribir: se proponen cuando llegue su pregunta
    const sugerencias = {};
    let ultimoTexto = "";
    actualizar(e);

    // Descartar pide una segunda confirmación en el mismo lugar (sin ventanas emergentes)
    $("#descartar").addEventListener("click", async (ev) => {
      const b = ev.currentTarget;
      if (!b.dataset.confirmar) {
        b.dataset.confirmar = "1";
        b.textContent = "Sí, descartarla";
        b.classList.remove("claro");
        const no = document.createElement("button");
        no.type = "button"; no.className = "boton claro pequeno"; no.textContent = "Cancelar"; no.id = "no-descartar";
        no.addEventListener("click", () => { delete b.dataset.confirmar; b.textContent = "Descartar consulta"; b.classList.add("claro"); no.remove(); });
        b.after(no);
        return;
      }
      b.disabled = true;
      try {
        await api("POST", `/consultas/${e.id_consulta}/descartar`, {});
        aviso(`Consulta ${e.numero ?? e.id_consulta} descartada. Sus respuestas quedan en Mis consultas.`);
        location.hash = "#/consulta";
      } catch (err) { aviso(err.message, "error"); b.disabled = false; }
    });

    function actualizar(est, aviso_) {
      actualizarMarcador($("#marcador"), est.ranking, false);
      $("#recorrido").innerHTML = htmlRecorrido(est.hechos);
      if (est.estado === "terminada") {
        const acc = $("#acciones-consulta");
        if (acc) acc.remove();
        zona.classList.remove("pensando");
        $("#t-marcador").textContent = "Resultado final";
        $(".titulo-marcador p").textContent = "Las cinco rutinas más probables";
        zona.innerHTML = htmlResultado(est.diagnostico);
        zona.scrollIntoView({ block: "start", behavior: "smooth" });
        return;
      }
      pintarPregunta(est, aviso_);
    }

    function pintarPregunta(est, aviso_ = {}) {
      const p = est.pregunta;
      const propuesta = aviso_.confirmar || (sugerencias[p.atributo] && { ...sugerencias[p.atributo], sugerida: true });
      zona.classList.remove("pensando");
      zona.innerHTML = `
        ${est.mensaje && !aviso_.noEntendido && !aviso_.confirmar ? `<p class="coach">${esc(est.mensaje)}</p>` : ""}
        <p class="paso">Pregunta ${est.hechos.length + 1}</p>
        <h2 class="pregunta-texto" id="t-pregunta">${esc(p.texto)}</h2>
        ${p.ayuda ? `<p class="ayuda">${esc(p.ayuda)}</p>` : ""}
        ${propuesta ? `<div class="propuesta" role="alert">
          <p>${propuesta.sugerida ? `Por lo que escribiste antes, parece que tu respuesta es <b>${esc(propuesta.opcion)}</b>.`
            : `Escribiste «${esc(propuesta.texto)}». ¿Te refieres a <b>${esc(propuesta.opcion)}</b>?`}</p>
          <div class="acciones">
            <button class="boton" type="button" id="aceptar-propuesta">${propuesta.sugerida ? "Sí, es correcto" : "Sí, a eso me refiero"}</button>
            <button class="boton claro" type="button" id="rechazar-propuesta">No, elijo otra</button>
          </div></div>` : ""}
        <div class="opciones" role="group" aria-labelledby="t-pregunta">${p.opciones.map((o) =>
          `<button type="button" class="opcion${propuesta && propuesta.id_respuesta === o.id_respuesta ? " propuesta-opcion" : ""}" data-id="${o.id_respuesta}">${esc(o.texto)}</button>`).join("")}</div>
        ${aviso_.noEntendido ? `<p class="no-entendido" role="alert">${esc(aviso_.noEntendido)}</p>` : ""}
        <form class="redactor" id="redactor" autocomplete="off">
          <label for="texto-libre">O respóndelo con tus palabras</label>
          <div class="redactor-fila">
            <input type="text" id="texto-libre" maxlength="300"
              placeholder="${p.ejemplos && p.ejemplos.length ? esc("Ej.: " + p.ejemplos.join(", ")) : ""}">
            <button class="boton claro" type="submit">Enviar respuesta</button>
          </div>
          <small class="tenue">Puedes contar varias cosas a la vez, por ejemplo «llevo tres años yendo al gym y quiero ganar fuerza».</small>
        </form>
        <p class="estado-motor" id="estado-motor" role="status"></p>`;
      $$(".opcion", zona).forEach((b) => b.addEventListener("click", () => {
        if (estado.ocupado) return;
        b.classList.add("elegida");
        delete sugerencias[p.atributo];
        enviar(`/consultas/${e.id_consulta}/respuestas`, { id_respuesta: Number(b.dataset.id) });
      }));
      const aceptar = $("#aceptar-propuesta");
      if (aceptar) {
        aceptar.addEventListener("click", () => {
          delete sugerencias[p.atributo];
          enviar(`/consultas/${e.id_consulta}/respuestas`, { id_respuesta: propuesta.id_respuesta,
            texto: propuesta.texto || propuesta.textoOrigen || ultimoTexto,
            interpretacion: propuesta.sugerida ? "sugerencia" : "confirmada" });
        });
        $("#rechazar-propuesta").addEventListener("click", () => {
          delete sugerencias[p.atributo];
          pintarPregunta(est);
        });
        aceptar.focus({ preventScroll: true });
      }
      $("#redactor").addEventListener("submit", (ev) => {
        ev.preventDefault();
        const texto = $("#texto-libre").value.trim();
        if (!texto || estado.ocupado) return;
        ultimoTexto = texto;
        enviar(`/consultas/${e.id_consulta}/mensajes`, { texto });
      });
      if (!propuesta) {
        const primera = $(".opcion", zona);
        if (aviso_.noEntendido) $("#texto-libre").focus();
        else if (primera) primera.focus({ preventScroll: true });
      }
    }

    async function enviar(ruta, cuerpo) {
      estado.ocupado = true;
      zona.classList.add("pensando");
      $$("button, input", zona).forEach((x) => { x.disabled = true; });
      $("#estado-motor").textContent = cuerpo.texto && !cuerpo.id_respuesta
        ? "Interpretando tu respuesta…" : "Consultando la base de conocimiento…";
      try {
        const nuevo = await api("POST", ruta, cuerpo);
        for (const [atributo, s] of Object.entries(nuevo.sugerencias || {})) {
          sugerencias[atributo] = { ...s, textoOrigen: cuerpo.texto };
        }
        if (nuevo.no_entendido) {
          pintarPregunta(nuevo, { noEntendido: nuevo.mensaje });
        } else if (nuevo.confirmar) {
          pintarPregunta(nuevo, { confirmar: nuevo.confirmar });
        } else {
          e = nuevo;
          actualizar(e);
        }
      } catch (err) {
        aviso(err.message, "error");
        pintarPregunta(e);
      } finally {
        estado.ocupado = false;
      }
    }
  }

  /* ============================================================ listas de consultas */
  async function vistaListaConsultas(propias) {
    const { consultas } = await api("GET", "/consultas");
    const filtro = sessionStorage.getItem("se.filtro") || "todas";
    vista.innerHTML = `
      <div class="encabezado"><div>
        <h1>${propias ? "Mis consultas" : "Consultas"}</h1>
        <p>${propias ? "Aquí están tus consultas. Abre una para ver tu rutina y por qué se eligió. Solo puedes tener una sin terminar a la vez."
          : { experto: "Aquí llegan las consultas de los usuarios. Empieza por las terminadas sin verificar: ábrelas, revisa cómo se eligió la rutina, verifícala y deja tu opinión.",
            ingeniero_conocimiento: "Sirven para ver cómo responde el sistema con la base actual. Si cambiaste pesos o reglas, verifica una consulta nueva para confirmar que todo sigue cumpliendo las reglas del experto.",
            administrador: "Seguimiento del uso del sistema, solo de lectura. La revisión de cada consulta la hace el experto." }[estado.perfil.rol]}</p></div>
        ${propias ? "" : `
        <label class="campo"><span>Mostrar</span><select id="filtro">
          <option value="todas">Todas</option><option value="terminadas">Terminadas</option>
          <option value="sin-verificar">Terminadas sin verificar</option></select></label>`}
      </div>
      <div class="superficie tabla-contenedor" id="tabla"></div>`;
    const pintar = (f) => {
      const filas = consultas.filter((c) => f === "todas" || (c.estado === "terminada" &&
        (f === "terminadas" || !c.verificacion_formal)));
      $("#tabla").innerHTML = filas.length ? `<table>
        <thead><tr>${propias ? "" : '<th scope="col">Usuario</th>'}<th scope="col">N.º</th><th scope="col">Fecha</th>
          <th scope="col">Rutina</th><th scope="col">Probabilidad</th>
          ${propias ? "" : '<th scope="col">Verificación</th>'}<th scope="col">Estado</th></tr></thead>
        <tbody>${filas.map((c) => `
          <tr class="clicable" data-ir="${c.estado === "en_curso" && propias ? `#/consulta/${c.id_consulta}` : `#/consultas/${c.id_consulta}`}">
            ${propias ? "" : `<td>${esc(c.alias)}</td>`}
            <td class="num"><a href="${c.estado === "en_curso" && propias ? `#/consulta/${c.id_consulta}` : `#/consultas/${c.id_consulta}`}">${c.numero ?? c.id_consulta}</a></td>
            <td>${esc(fecha(c.fecha_inicio))}</td>
            <td>${c.hipotesis ? esc(c.hipotesis) : `<span class="tenue">${c.estado === "abandonada" ? "Sin resultado" : "Pendiente"}</span>`}</td>
            <td class="num">${c.probabilidad != null ? pct(c.probabilidad) : ""}</td>
            ${propias ? "" : `<td>${c.estado === "terminada" ? etiquetaVerificacion(c.verificacion_formal) : ""}</td>`}
            <td>${etiquetaEstado(c.estado)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="vacio">${propias ? "Todavía no tienes consultas. Empieza una para recibir tu rutina."
          : "No hay consultas con ese filtro."}</p>`;
      $$("tr[data-ir]").forEach((tr) => tr.addEventListener("click", (ev) => {
        if (ev.target.tagName !== "A") location.hash = tr.dataset.ir; }));
    };
    const sel = $("#filtro");
    if (sel) {
      sel.value = filtro;
      sel.addEventListener("change", () => { sessionStorage.setItem("se.filtro", sel.value); pintar(sel.value); });
    }
    pintar(propias ? "todas" : filtro);
  }

  /* ============================================================ detalle de una consulta */
  const INTERPRETE = { sinonimos: "los sinónimos de la base", lex: "Amazon Lex", nova: "Bedrock Nova",
    confirmada: "Bedrock Nova y la persona lo confirmó", sugerencia: "un mensaje anterior y la persona lo confirmó" };
  function interpretadoPor(i) {
    if (!i || !i.metodo) return "";
    return ` (con ${INTERPRETE[i.metodo] || i.metodo}${i.motivo && !i.confirmada ? `: ${esc(i.motivo)}` : ""})`;
  }

  function htmlTraza(traza, tecnico) {
    const pasos = [];
    const lider = (par) => tecnico ? `<b>${esc(par[0])}</b> con ${pct(par[1])}` : `una rutina con ${pct(par[1])}`;
    for (const t of traza || []) {
      const d = t.detalle || {};
      if (t.tipo === "seleccion_pregunta") {
        const omitidas = (d.evaluadas || []).filter((x) => !x.puede_cambiar_lider).map((x) => x.pregunta);
        const decisivas = ((d.evaluadas || []).find((x) => x.pregunta === d.elegida) || {}).respuestas_decisivas || [];
        if (d.elegida) {
          pasos.push(`<li><h3>Pregunta ${esc(d.elegida)}</h3>
            <p>Es la siguiente pregunta que todavía podía cambiar el resultado${decisivas.length
              ? `: lo cambiarían las respuestas ${esc(decisivas.join(", "))}` : ""}.</p>
            ${omitidas.length ? `<p>Se salta ${esc(omitidas.join(", "))}, porque ninguna respuesta cambiaría el resultado.</p>` : ""}</li>`);
        } else {
          pasos.push(`<li><h3>Fin del cuestionario</h3>
            <p>Ya ninguna pregunta cambiaría la rutina al frente${omitidas.length ? `, así que ${esc(omitidas.join(", "))} no se preguntan` : ""}.</p></li>`);
        }
      } else if (t.tipo === "respuesta") {
        const h = d.hecho || {};
        const al = (d.top_despues || [])[0] || [];
        pasos.push(`<li><h3>Respuesta a ${esc(h.pregunta)}: ${esc(h.respuesta)}</h3>
          ${d.origen === "texto_libre" ? `<p>Se escribió «${esc(d.texto_usuario)}» y el sistema lo entendió como «${esc(h.respuesta)}»${tecnico ? interpretadoPor(d.interpretacion) : ""}.</p>` : ""}
          <p>De ${esc(d.hipotesis_que_dependen)} rutinas relacionadas con esta pregunta, ${(d.hipotesis_respaldadas || []).length}
             siguen en pie y ${(d.hipotesis_debilitadas || []).length} pierden fuerza.${tecnico ? ` Hecho ${esc(h.hecho)}.` : ""}</p>
          ${al.length ? `<p>Al frente queda ${lider(al)}.</p>` : ""}</li>`);
      } else if (t.tipo === "conclusion") {
        pasos.push(`<li class="conclusion"><h3>Resultado: ${tecnico ? esc(d.hipotesis) + " con " : ""}${pct(d.probabilidad)}</h3>
          <p>Se guardan las cinco rutinas más probables.</p></li>`);
      } else if (t.tipo === "verificacion_formal") {
        pasos.push(`<li><h3>Verificación con las reglas del experto: ${etiquetaVerificacion(d.resultado)}</h3>
          <p>${d.reglas && d.reglas.length ? `Regla aplicada: ${esc(d.reglas.join(", "))}. ` : ""}${esc(fecha(t.fecha))}</p></li>`);
      }
    }
    return pasos.length ? `<ol class="traza">${pasos.join("")}</ol>` : '<p class="tenue">Sin pasos registrados.</p>';
  }

  async function vistaDetalle(id) {
    const e = await api("GET", `/consultas/${encodeURIComponent(id)}`);
    const rol = estado.perfil.rol;
    // Con un resultado lógico la verificación es definitiva (la consulta ya no cambia);
    // solo se reintenta si falló por causas técnicas
    const definitiva = ["VALID", "INVALID", "SATISFIABLE", "IMPOSSIBLE"].includes(e.verificacion_formal);
    const puedeVerificar = (rol === "experto" || rol === "ingeniero_conocimiento") && !definitiva;
    const puedeValidar = rol === "experto";
    // La última verificación guardada (queda en la consulta y en su traza)
    const previa = [...(e.traza || [])].reverse().find((t) => t.tipo === "verificacion_formal");
    const terminada = e.estado === "terminada";
    const descartada = e.estado === "abandonada";
    const propia = rol === "usuario_final";
    vista.innerHTML = `
      <div class="encabezado"><div>
        <h1>${esc(tituloConsulta(e, propia))}</h1>
        <p>${esc(fecha(e.fecha_inicio))}</p></div>
        <div class="acciones">${etiquetaEstado(e.estado)} <span id="etiqueta-verif">${terminada ? etiquetaVerificacion(e.verificacion_formal) : ""}</span>
          <a class="boton claro pequeno" href="${propia ? "#/mis-consultas" : "#/consultas"}">Volver a la lista</a></div>
      </div>
      <section aria-labelledby="t-marc">
        <div class="titulo-marcador"><h2 id="t-marc">${terminada ? "Hipótesis finales" : descartada ? "Hipótesis al descartarla" : "Hipótesis actuales"}</h2>
          <p>${terminada ? "Las cinco rutinas que quedaron al terminar" : descartada ? "Cómo iba cuando se descartó; no es un resultado"
            : "Cambiarán mientras la persona siga respondiendo"}</p></div>
        ${htmlMarcador(e.ranking, !propia)}
      </section>
      <div class="detalle-consulta">
        <div class="principal">
          ${terminada ? `<section class="superficie relleno" aria-label="Resultado">${htmlResultado(e.diagnostico, false)}</section>`
            : descartada ? `<section class="superficie relleno"><h2>Consulta descartada</h2>
               <p class="secundario">${propia ? "La descartaste antes de terminar, así que no generó rutina. Se conservan las respuestas que alcanzaste a dar."
                 : "La persona la descartó, o se cerró por inactividad, antes de terminar. No generó rutina, así que no se verifica ni se valida."}
                 ${e.fecha_fin ? ` Se cerró el ${esc(fecha(e.fecha_fin))}.` : ""}</p></section>`
            : `<section class="superficie relleno"><h2>Consulta en curso</h2>
               <p class="secundario">${propia ? "Todavía te faltan preguntas por responder." : "La persona todavía no termina. Podrás verificarla y dar tu opinión cuando termine."}</p>
               ${propia ? `<p class="acciones resultado-acciones"><a class="boton" href="#/consulta/${e.id_consulta}">Continuar</a></p>` : ""}</section>`}
          <section class="superficie relleno" aria-labelledby="t-rec"><h2 id="t-rec">Respuestas</h2>
            <ol class="recorrido">${htmlRecorrido(e.hechos)}</ol></section>
          <section class="superficie relleno" aria-labelledby="t-traza"><h2 id="t-traza">${propia ? "Cómo se eligió tu rutina" : "Cómo llegó el sistema a esta rutina"}</h2>
            <p class="tenue">${propia ? "Paso a paso: qué se te preguntó y cómo cambió la rutina al frente."
              : "Paso a paso: qué se preguntó, qué respondió la persona y qué rutina quedaba al frente. Cada paso sale de la base de conocimiento, no de reglas fijas en el código."}</p>
            ${htmlTraza(e.traza, !propia)}</section>
        </div>
        ${terminada && !propia ? `<aside class="lateral" aria-label="Revisión del diagnóstico">
          <section class="superficie relleno" aria-labelledby="t-ver">
            <h2 id="t-ver">Verificación formal</h2>
            <p class="tenue">${definitiva ? "Resultado definitivo: las respuestas y la rutina de esta consulta no cambian, así que verificarla otra vez daría lo mismo."
              : { experto: "Comprueba que la rutina respete las reglas que definiste. Hazlo antes de dar tu opinión; basta con una vez.",
              ingeniero_conocimiento: "Comprueba que la rutina cumple las reglas del experto. Se hace una sola vez por consulta; para probar un cambio en la base, verifica una consulta nueva.",
              administrador: "Resultado de la comprobación con las reglas del experto. Solo el experto y el ingeniero pueden ejecutarla." }[rol]}</p>
            <div class="verificacion" id="verificacion">${previa
              ? htmlVerificacion(e.verificacion_formal, previa.detalle.hipotesis || e.diagnostico.rutina.codigo, previa.detalle, previa.fecha)
              : e.verificacion_formal ? htmlVerificacion(e.verificacion_formal, e.diagnostico.rutina.codigo)
              : '<p class="tenue">Todavía no se ha verificado.</p>'}</div>
            ${puedeVerificar ? `<button class="boton${e.verificacion_formal ? " claro" : ""}" type="button" id="verificar">${e.verificacion_formal
              ? "Reintentar la verificación" : "Verificar con Automated Reasoning"}</button>` : ""}
          </section>
          <section class="superficie relleno" aria-labelledby="t-val">
            <h2 id="t-val">Opinión del experto</h2>
            <p class="tenue">${puedeValidar ? "Según tu experiencia, ¿esta rutina es adecuada para lo que respondió la persona? Tu opinión alimenta la concordancia de Métricas."
              : "Lo que opinó el experto sobre esta rutina."}</p>
            <div id="validaciones"></div>
            ${puedeValidar ? `<form class="formulario" id="validar">
              <fieldset class="campo"><legend>¿Recomendarías esta rutina a esta persona?</legend>
                <label><input type="radio" name="acuerdo" value="si" required> De acuerdo</label>
                <label><input type="radio" name="acuerdo" value="no"> En desacuerdo</label></fieldset>
              <label class="campo"><span>Comentario para el ingeniero (opcional)</span><textarea name="comentario" maxlength="500"></textarea></label>
              <button class="boton" type="submit">Guardar opinión</button></form>` : ""}
          </section>
        </aside>` : ""}
      </div>`;
    anchoBarras();
    pintarValidaciones(e.validaciones);

    const verificar = $("#verificar");
    if (verificar) verificar.addEventListener("click", async () => {
      verificar.disabled = true;
      verificar.textContent = "Verificando…";
      try {
        const v = await api("POST", `/consultas/${e.id_consulta}/verificacion`);
        $("#etiqueta-verif").innerHTML = etiquetaVerificacion(v.resultado);
        $("#verificacion").innerHTML = htmlVerificacion(v.resultado, v.hipotesis, v.detalle, new Date().toISOString());
        if (["VALID", "INVALID", "SATISFIABLE", "IMPOSSIBLE"].includes(v.resultado)) {
          verificar.remove();                       // definitiva: no se repite
        } else {
          verificar.textContent = "Reintentar la verificación";
          verificar.classList.add("claro");
          verificar.disabled = false;
        }
      } catch (err) {
        aviso(err.message, "error");
        verificar.textContent = e.verificacion_formal ? "Reintentar la verificación" : "Verificar con Automated Reasoning";
        verificar.disabled = false;
        if (err.estado === 409) enrutar();          // otra persona ya la verificó: se muestra su resultado
      }
    });

    const form = $("#validar");
    if (form) form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = new FormData(form);
      if (!f.get("acuerdo")) { aviso("Elige si recomendarías o no esta rutina.", "error"); return; }
      try {
        const r = await api("POST", `/consultas/${e.id_consulta}/validacion`,
          { de_acuerdo: f.get("acuerdo") === "si", comentario: f.get("comentario") });
        pintarValidaciones(r.validaciones);
        form.reset();
        aviso("Opinión guardada.");
      } catch (err) { aviso(err.message, "error"); }
    });
  }

  function pintarValidaciones(lista) {
    const cont = $("#validaciones");
    if (!cont) return;
    cont.innerHTML = lista && lista.length ? `<ul class="hechos-lista">${lista.map((v) => `
      <li><span>${esc(v.experto)}, ${esc(fecha(v.fecha))}</span>
        ${v.de_acuerdo ? '<span class="etiqueta ok">De acuerdo</span>' : '<span class="etiqueta error">En desacuerdo</span>'}
        ${v.comentario ? `<p>${esc(v.comentario)}</p>` : ""}</li>`).join("")}</ul><hr class="separador">`
      : '<p class="tenue">Aún no hay validaciones.</p><hr class="separador">';
  }

  /* ============================================================ métricas */
  async function vistaMetricas() {
    const m = await api("GET", "/metricas");
    const total = m.por_hipotesis.reduce((s, h) => s + h.veces, 0) || 1;
    vista.innerHTML = `
      <div class="encabezado"><div><h1>Métricas</h1>
        <p>${{ experto: "Qué tanto coinciden los resultados del sistema con tu criterio. Si la concordancia baja, revisa con el ingeniero las rutinas en las que no estuviste de acuerdo.",
          ingeniero_conocimiento: "Te ayudan a decidir qué ajustar: una concordancia baja señala rutinas o pesos por revisar con el experto.",
          administrador: "Uso general del sistema y qué tanto coincide con el criterio del experto." }[estado.perfil.rol]}</p></div></div>
      <dl class="superficie indicadores">
        <div><dt>Consultas</dt><dd>${num(m.consultas)}
          <small>${num(m.terminadas)} terminadas, ${num(m.en_curso)} en curso y ${num(m.descartadas ?? 0)} descartadas</small></dd></div>
        <div><dt>Pendientes por verificar</dt><dd>${num(m.pendientes_verificar)}
          <small>Terminadas que aún no se comprueban con las reglas</small></dd></div>
        <div><dt>Verificadas con las reglas</dt><dd>${num(m.verificadas)}
          <small>${num(m.verificadas_valid)} válidas y ${num(m.verificadas_invalid)} inválidas</small></dd></div>
        <div><dt>Concordancia con el experto</dt><dd>${m.concordancia_experto == null ? "Sin datos" : pct(m.concordancia_experto)}
          <small>${m.validaciones ? `${num(m.de_acuerdo)} de ${num(m.validaciones)} opiniones de acuerdo, en ${num(m.consultas_con_opinion)} consultas`
            : "Aún no hay opiniones del experto"}</small></dd></div>
      </dl>
      <section class="superficie relleno">
        <h2>Rutinas más recomendadas</h2>
        <p class="tenue">Cuántas consultas terminadas concluyeron en cada rutina.</p>
        ${m.por_hipotesis.length ? `<ul class="frecuencias">${m.por_hipotesis.slice(0, 10).map((h) => `
          <li><span><b>${esc(nombreHipotesis(h))}</b> <span class="tenue">${esc(h.codigo)}</span>
              <small class="tenue frec-detalle">${esc(detalleHipotesis(h))}</small></span>
            <div class="barra-prob" aria-hidden="true"><i data-ancho="${h.veces / total}"></i></div>
            <span class="num" title="${num(h.veces)} de ${num(total)} consultas terminadas">${num(h.veces)}</span></li>`).join("")}</ul>`
          : '<p class="tenue">Aún no hay consultas terminadas.</p>'}
      </section>`;
    $("section", vista).classList.add("seccion-separada");
    anchoBarras();
  }

  /* ============================================================ base de conocimiento */
  const SECCIONES_KB = [["preguntas", "Preguntas"], ["hechos", "Opciones y hechos"], ["hipotesis", "Hipótesis"],
    ["granulos", "Gránulos y pesos"], ["frases", "Frases por revisar"], ["validacion", "Validación"]];
  const DOMINIOS = {
    nivel: ["Principiante", "Intermedio", "Avanzado"],
    equipo: ["Básico o en casa", "Gimnasio completo"],
    objetivo: ["Fuerza", "Hipertrofia", "Resistencia", "Pérdida de grasa", "Rendimiento deportivo"],
    fase: ["Volumen", "Intensidad"],
    dias_semana: ["2 días", "3 o más días"],
    actividad: ["Sedentario", "Algo activo"],
  };

  async function guardarKB(metodo, ruta, cuerpo, mensaje) {
    const r = await api(metodo, ruta, cuerpo);
    estado.base = null;
    if (r.validacion && r.validacion.length) {
      aviso("Guardado, pero el validador encontró problemas: " + r.validacion.map((v) => v.prueba).join("; "),
        "pendiente", 9000);
    } else aviso(mensaje);
    return r;
  }

  // El experto revisa la base en solo lectura; validar y enseñar frases es del ingeniero
  const SOLO_INGENIERO = new Set(["frases", "validacion"]);
  async function vistaConocimiento(seccion, seleccion) {
    const editable = estado.perfil.rol === "ingeniero_conocimiento";
    const secciones = SECCIONES_KB.filter(([s]) => editable || !SOLO_INGENIERO.has(s));
    if (!secciones.some(([s]) => s === seccion)) { location.hash = "#/conocimiento/preguntas"; return; }
    if (!estado.base) estado.base = await api("GET", "/base-conocimiento");
    const kb = estado.base;
    const dis = editable ? "" : " disabled";
    vista.innerHTML = `
      <div class="encabezado"><div><h1>Base de conocimiento</h1>
        <p>${editable ? "Lo que cambies aquí se aplica de inmediato a las consultas nuevas y queda registrado. Antes de guardar, confirma que el cambio respeta el criterio del experto; después de cambios grandes, ejecuta la validación."
          : "Aquí está tu conocimiento tal como lo usa el sistema: preguntas, opciones, rutinas y el peso de cada respuesta. Es de solo lectura; si encuentras algo que no refleja tu criterio, coméntalo con el ingeniero del conocimiento para que lo corrija y valide la base."}</p></div></div>
      <nav class="subnav" aria-label="Partes de la base de conocimiento">${secciones.map(([s, t]) =>
        `<a href="#/conocimiento/${s}"${s === seccion ? ' aria-current="page"' : ""}>${t}</a>`).join("")}</nav>
      <div id="kb"></div>`;
    const cont = $("#kb");
    const recargar = () => { estado.base = null; enrutar(); };

    if (seccion === "preguntas") {
      cont.innerHTML = `<div class="formulario">${kb.preguntas.map((p) => `
        <form class="superficie relleno formulario" data-codigo="${esc(p.codigo)}">
          <h2>${esc(p.codigo)} <span class="tenue">${esc(p.atributo)}</span></h2>
          <label class="campo"><span>Pregunta</span><input type="text" name="texto" value="${esc(p.texto)}" required${dis}></label>
          <label class="campo"><span>Ayuda para el usuario</span><input type="text" name="ayuda" value="${esc(p.ayuda)}"${dis}></label>
          <div class="fila-campos">
            <label class="campo"><span>Peso base</span>
              <input type="number" name="peso_base" min="0.01" max="0.99" step="0.01" value="${esc(p.peso_base)}" class="peso-input"${dis}>
              <small>Qué tanto separan sus respuestas unas rutinas de otras (de 0,01 a 0,99).</small></label>
            ${editable ? `<label class="campo"><span>Al guardar</span>
              <label><input type="checkbox" name="aplicar"> Aplicar este peso a todos sus gránulos</label></label>` : ""}
          </div>
          ${editable ? '<p class="acciones"><button class="boton" type="submit">Guardar pregunta</button></p>' : ""}
        </form>`).join("")}</div>`;
      $$("form", cont).forEach((f) => f.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const d = new FormData(f);
        try {
          await guardarKB("PUT", `/base-conocimiento/preguntas/${f.dataset.codigo}`, {
            texto: d.get("texto"), ayuda: d.get("ayuda"), peso_base: Number(d.get("peso_base")),
            aplicar_a_granulos: d.get("aplicar") === "on" }, `Pregunta ${f.dataset.codigo} guardada.`);
          recargar();
        } catch (err) { aviso(err.message, "error", 8000); }
      }));
    }

    if (seccion === "hechos") {
      const siguiente = "HC" + String(Math.max(...kb.preguntas.flatMap((p) => p.opciones.map((o) =>
        Number(o.codigo_hecho.slice(2))))) + 1).padStart(2, "0");
      cont.innerHTML = `<div class="formulario">${kb.preguntas.map((p) => `
        <section class="superficie">
          <div class="relleno"><h2>${esc(p.codigo)} ${esc(p.texto)}</h2></div>
          <div class="tabla-contenedor"><table>
            <thead><tr><th scope="col">Hecho</th><th scope="col">Valor</th><th scope="col">Texto de la opción</th>
              <th scope="col">Sinónimos (separados por coma)</th><th scope="col">Orden</th>${editable ? "<th></th>" : ""}</tr></thead>
            <tbody>${p.opciones.map((o) => `
              <tr data-codigo="${esc(o.codigo_hecho)}" data-pregunta="${esc(p.codigo)}">
                <td>${esc(o.codigo_hecho)}</td>
                <td><input type="text" name="valor" value="${esc(o.valor)}" aria-label="Valor"${dis}></td>
                <td><input type="text" name="texto_opcion" value="${esc(o.texto_opcion)}" aria-label="Texto de la opción"${dis}></td>
                <td><input type="text" name="sinonimos" value="${esc((o.sinonimos || []).join(", "))}" aria-label="Sinónimos"${dis}></td>
                <td><input type="number" name="orden" min="1" value="${esc(o.orden)}" class="peso-input" aria-label="Orden"${dis}></td>
                ${editable ? `<td><div class="acciones"><button class="boton pequeno" data-accion="guardar" type="button">Guardar</button>
                  <button class="boton peligro pequeno" data-accion="eliminar" type="button">Eliminar</button></div></td>` : ""}
              </tr>`).join("")}
              ${editable ? `<tr data-codigo="${siguiente}" data-pregunta="${esc(p.codigo)}" data-nuevo>
                <td class="tenue">${siguiente}</td>
                <td><input type="text" name="valor" placeholder="Nuevo valor" aria-label="Valor nuevo"></td>
                <td><input type="text" name="texto_opcion" placeholder="Texto que verá el usuario" aria-label="Texto de la opción nueva"></td>
                <td><input type="text" name="sinonimos" aria-label="Sinónimos de la opción nueva"></td>
                <td><input type="number" name="orden" min="1" value="${p.opciones.length + 1}" class="peso-input" aria-label="Orden"></td>
                <td><button class="boton claro pequeno" data-accion="guardar" type="button">Agregar opción</button></td></tr>` : ""}
            </tbody></table></div>
        </section>`).join("")}
        <p class="nota">Ten en cuenta: los botones muestran una opción nueva de inmediato, pero el sistema solo la reconoce
          cuando la persona escribe con sus palabras después de actualizar el asistente de lenguaje (Amazon Lex).</p></div>`;
      $$("button[data-accion]", cont).forEach((b) => b.addEventListener("click", async () => {
        const fila = b.closest("tr");
        const v = (n) => $(`[name=${n}]`, fila).value.trim();
        try {
          if (b.dataset.accion === "eliminar") {
            if (!confirm(`¿Eliminar el hecho ${fila.dataset.codigo}?`)) return;
            await guardarKB("DELETE", `/base-conocimiento/hechos/${fila.dataset.codigo}`, undefined,
              `Hecho ${fila.dataset.codigo} eliminado.`);
          } else {
            await guardarKB("PUT", `/base-conocimiento/hechos/${fila.dataset.codigo}`, {
              pregunta: fila.dataset.pregunta, valor: v("valor"), texto_opcion: v("texto_opcion"),
              sinonimos: v("sinonimos").split(",").map((s) => s.trim()).filter(Boolean),
              orden: Number(v("orden")) }, `Hecho ${fila.dataset.codigo} guardado.`);
          }
          recargar();
        } catch (err) { aviso(err.message, "error", 8000); }
      }));
    }

    if (seccion === "hipotesis" || seccion === "granulos") {
      const lista = kb.hipotesis;
      const actual = lista.find((h) => h.codigo === seleccion) || lista[0];
      cont.innerHTML = `<div class="editor-grid">
        <div class="superficie"><ul class="lista-seleccion">${lista.map((h) => `
          <li><button type="button" data-codigo="${esc(h.codigo)}"${h.codigo === actual.codigo ? ' aria-current="true"' : ""}>
            <span>${esc(h.codigo)} ${esc(nombreHipotesis(h))}</span><small>${esc(detalleHipotesis(h)) || "&nbsp;"}</small></button></li>`).join("")}
          ${editable && seccion === "hipotesis" ? `<li><button type="button" data-codigo="nueva">
            <span>Nueva hipótesis</span><small>Agregar una rutina</small></button></li>` : ""}</ul></div>
        <div id="editor"></div></div>`;
      $$(".lista-seleccion button", cont).forEach((b) => b.addEventListener("click", () => {
        location.hash = `#/conocimiento/${seccion}/${b.dataset.codigo}`; }));
      const editor = $("#editor");

      if (seccion === "hipotesis") {
        const nueva = seleccion === "nueva";
        const h = nueva ? { codigo: "H" + String(Math.max(...lista.map((x) => Number(x.codigo.slice(1)))) + 1).padStart(2, "0"),
          nivel: "Principiante", equipo: "Básico o en casa", probabilidad_previa: 1, descripcion_rutina: "" } : actual;
        const sel = (campo, opcional) => `<select name="${campo}"${dis}>
          ${opcional ? `<option value="">No aplica</option>` : ""}
          ${DOMINIOS[campo].map((v) => `<option${h[campo] === v ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
        editor.innerHTML = `<form class="superficie relleno formulario" id="form-hip">
          <h2>${nueva ? `Nueva hipótesis ${esc(h.codigo)}` : `${esc(h.codigo)} ${esc(nombreHipotesis(h))}`}</h2>
          <div class="fila-campos">
            <label class="campo"><span>Nivel</span>${sel("nivel")}</label>
            <label class="campo"><span>Equipo</span>${sel("equipo")}</label>
            <label class="campo"><span>Objetivo</span>${sel("objetivo", true)}</label>
            <label class="campo"><span>Fase</span>${sel("fase", true)}</label>
            <label class="campo"><span>Días por semana</span>${sel("dias_semana", true)}</label>
            <label class="campo"><span>Actividad actual</span>${sel("actividad", true)}</label>
          </div>
          <label class="campo"><span>Rutina</span><textarea name="descripcion_rutina" required${dis}>${esc(h.descripcion_rutina)}</textarea></label>
          <label class="campo"><span>Probabilidad previa</span>
            <input type="number" name="probabilidad_previa" min="0.01" step="0.01" value="${esc(h.probabilidad_previa)}" class="peso-input"${dis}>
            <small>Ventaja de esta rutina antes de cualquier respuesta. Con 1 parte igual que las demás.</small></label>
          ${editable ? `<div class="acciones"><button class="boton" type="submit">${nueva ? "Crear hipótesis" : "Guardar hipótesis"}</button>
            ${nueva ? "" : '<button class="boton peligro" type="button" id="eliminar-hip">Eliminar hipótesis</button>'}</div>
            ${nueva ? '<p class="nota">Después de crearla, asóciale sus hechos en «Gránulos y pesos».</p>' : ""}` : ""}
        </form>`;
        const f = $("#form-hip");
        f.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const d = Object.fromEntries(new FormData(f));
          for (const k of ["objetivo", "fase", "dias_semana", "actividad"]) if (!d[k]) d[k] = null;
          d.probabilidad_previa = Number(d.probabilidad_previa);
          try {
            await guardarKB("PUT", `/base-conocimiento/hipotesis/${h.codigo}`, d, `Hipótesis ${h.codigo} guardada.`);
            location.hash = `#/conocimiento/${nueva ? "granulos" : "hipotesis"}/${h.codigo}`;
            if (!nueva) recargar();
          } catch (err) { aviso(err.message, "error", 8000); }
        });
        const borrar = $("#eliminar-hip");
        if (borrar) borrar.addEventListener("click", async () => {
          if (!confirm(`¿Eliminar la hipótesis ${h.codigo} y sus gránulos?`)) return;
          try {
            await guardarKB("DELETE", `/base-conocimiento/hipotesis/${h.codigo}`, undefined, `Hipótesis ${h.codigo} eliminada.`);
            if (location.hash === "#/conocimiento/hipotesis") recargar(); else location.hash = "#/conocimiento/hipotesis";
          } catch (err) { aviso(err.message, "error", 8000); }
        });
      }

      if (seccion === "granulos") {
        const propios = kb.granulos.filter((g) => g.hipotesis === actual.codigo);
        const hechos = kb.preguntas.flatMap((p) => p.opciones.map((o) => ({ ...o, pregunta: p })));
        const deHecho = (c) => hechos.find((o) => o.codigo_hecho === c);
        // Mismas reglas que fn_coherencia en la base: solo se ofrecen hechos que la base aceptaría
        const tiempo = { Principiante: "Menos de 6 meses", Intermedio: "6 meses a 2 años", Avanzado: "Más de 2 años" };
        const coherente = (o, h) => ({
          equipo_disponible: o.valor === h.equipo,
          objetivo_principal: !!h.objetivo && o.valor === h.objetivo,
          fase_priorizada: !!h.fase && o.valor === h.fase,
          tiempo_entrenando: o.valor === tiempo[h.nivel],
          tecnica_dominada: h.nivel === "Principiante" || o.valor === "Sí",
          dias_semana: !!h.dias_semana && o.valor === h.dias_semana,
          actividad_actual: !!h.actividad && o.valor === h.actividad,
        })[o.pregunta.atributo] ?? true;
        const libres = hechos.filter((o) => !propios.some((g) => g.hecho === o.codigo_hecho) && coherente(o, actual));
        editor.innerHTML = `<section class="superficie">
          <div class="relleno"><h2>${esc(actual.codigo)} ${esc(nombreHipotesis(actual))}</h2>
            <p class="tenue">Respuestas que respaldan esta rutina y su peso. Cuanto más alto el peso, más fuerza pierde la
              rutina cuando la persona responde otra cosa a esa pregunta.</p></div>
          <div class="tabla-contenedor"><table>
            <thead><tr><th scope="col">Pregunta</th><th scope="col">Hecho</th><th scope="col">Peso</th>${editable ? "<th></th>" : ""}</tr></thead>
            <tbody>${propios.map((g) => { const o = deHecho(g.hecho) || { pregunta: {} }; return `
              <tr data-hecho="${esc(g.hecho)}"><td>${esc(o.pregunta.codigo)} <span class="tenue">${esc(o.pregunta.atributo)}</span></td>
                <td>${esc(g.hecho)} ${esc(o.valor)}</td>
                <td><input type="number" name="peso" min="0.01" max="0.99" step="0.01" value="${esc(g.peso)}" class="peso-input" aria-label="Peso de ${esc(g.hecho)}"${dis}></td>
                ${editable ? `<td><div class="acciones"><button class="boton pequeno" data-accion="guardar" type="button">Guardar</button>
                  <button class="boton peligro pequeno" data-accion="quitar" type="button">Quitar</button></div></td>` : ""}</tr>`; }).join("")}
            </tbody></table></div>
          ${editable && !libres.length ? '<p class="relleno tenue">Todos los hechos compatibles con esta hipótesis ya están asociados.</p>' : ""}
          ${editable && libres.length ? `<form class="relleno acciones" id="agregar-granulo">
            <label class="campo"><span>Agregar hecho</span><select name="hecho">${libres.map((o) =>
              `<option value="${esc(o.codigo_hecho)}">${esc(o.pregunta.codigo)} ${esc(o.codigo_hecho)} ${esc(o.valor)}</option>`).join("")}</select></label>
            <label class="campo"><span>Peso</span><input type="number" name="peso" min="0.01" max="0.99" step="0.01" placeholder="Base" class="peso-input"></label>
            <button class="boton claro" type="submit">Agregar gránulo</button></form>` : ""}
        </section>`;
        $$("button[data-accion]", editor).forEach((b) => b.addEventListener("click", async () => {
          const fila = b.closest("tr");
          try {
            if (b.dataset.accion === "quitar") {
              await guardarKB("DELETE", `/base-conocimiento/granulos/${fila.dataset.hecho}/${actual.codigo}`, undefined,
                `Gránulo ${fila.dataset.hecho} quitado de ${actual.codigo}.`);
            } else {
              await guardarKB("PUT", "/base-conocimiento/granulos", { hecho: fila.dataset.hecho,
                hipotesis: actual.codigo, peso: Number($("[name=peso]", fila).value) },
                `Peso de ${fila.dataset.hecho} en ${actual.codigo} guardado.`);
            }
            recargar();
          } catch (err) { aviso(err.message, "error", 8000); }
        }));
        const agregar = $("#agregar-granulo");
        if (agregar) agregar.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const d = new FormData(agregar);
          try {
            await guardarKB("PUT", "/base-conocimiento/granulos", { hecho: d.get("hecho"), hipotesis: actual.codigo,
              peso: d.get("peso") ? Number(d.get("peso")) : null }, `Gránulo agregado a ${actual.codigo}.`);
            recargar();
          } catch (err) { aviso(err.message, "error", 8000); }
        });
      }
    }

    if (seccion === "frases") {
      const { frases } = await api("GET", "/base-conocimiento/frases");
      const opcionDe = (codigo) => kb.preguntas.flatMap((p) => p.opciones.map((o) => ({ ...o, pregunta: p.codigo })))
        .find((o) => o.codigo_hecho === codigo);
      cont.innerHTML = `<section class="superficie">
        <div class="relleno"><h2>Frases por revisar</h2>
          <p class="tenue">${editable
            ? "Frases cortas que escribieron los usuarios y que el sistema entendió con ayuda de Lex o de Nova, o que la persona confirmó. Revisa cada una: si se entendió bien, agrégala como sinónimo; si se entendió mal, elige la opción correcta y agrégala ahí. Desde ese momento se reconoce al instante, sin servicios externos."
            : ""}</p></div>
        ${frases.length ? `<div class="tabla-contenedor"><table>
          <thead><tr><th scope="col">Frase escrita</th><th scope="col">Se entendió como</th><th scope="col">Con ayuda de</th><th scope="col" class="num">Veces</th><th scope="col">Agregar como sinónimo de</th></tr></thead>
          <tbody>${frases.map((f, i) => `<tr>
            <td>«${esc(f.frase)}»</td><td>${esc(f.pregunta)}: ${esc(f.opcion)} <span class="tenue">${esc(f.hecho)}</span></td>
            <td>${esc({ lex: "Amazon Lex", nova: "Bedrock Nova", confirmada: "Nova, confirmada por la persona" }[f.metodo] || f.metodo)}</td>
            <td class="num">${num(f.veces)}</td>
            <td><div class="fila-accion"><select aria-label="Opción correcta para «${esc(f.frase)}»" data-opcion="${i}">${(kb.preguntas.find((p) => p.codigo === f.pregunta)?.opciones || []).map((o) =>
                `<option value="${esc(o.codigo_hecho)}"${o.codigo_hecho === f.hecho ? " selected" : ""}>${esc(o.texto_opcion)}</option>`).join("")}</select>
              <button class="boton claro pequeno" type="button" data-frase="${i}">Agregar</button></div></td></tr>`).join("")}
          </tbody></table></div>` : '<p class="relleno tenue">No hay frases pendientes. Cuando los usuarios escriban respuestas nuevas aparecerán aquí.</p>'}
      </section>`;
      $$("button[data-frase]", cont).forEach((b) => b.addEventListener("click", async () => {
        const f = frases[Number(b.dataset.frase)];
        const o = opcionDe($(`select[data-opcion="${b.dataset.frase}"]`, cont).value);
        if (!o) return aviso("La opción ya no existe en la base.", "error");
        try {
          await guardarKB("PUT", `/base-conocimiento/hechos/${o.codigo_hecho}`, {
            pregunta: o.pregunta, valor: o.valor, texto_opcion: o.texto_opcion,
            sinonimos: [...(o.sinonimos || []), f.frase], orden: o.orden }, `«${f.frase}» ahora es sinónimo de ${o.texto_opcion}.`);
          recargar();
        } catch (err) { aviso(err.message, "error", 8000); }
      }));
    }

    if (seccion === "validacion") {
      cont.innerHTML = `<section class="superficie">
        <div class="relleno encabezado"><div><h2>Validador de la base de conocimiento</h2>
          <p>Revisa que no falten opciones, que cada rutina tenga respaldo y que no haya reglas incoherentes. Ejecútala después de cada cambio importante.</p></div>
          <button class="boton" type="button" id="validar-base">Ejecutar validación</button></div>
        <div class="tabla-contenedor" id="resultado-validacion"></div></section>`;
      $("#validar-base").addEventListener("click", async (ev) => {
        ev.target.disabled = true;
        try {
          const { validacion } = await api("GET", "/base-conocimiento/validacion");
          $("#resultado-validacion").innerHTML = `<table><thead><tr><th scope="col">Prueba</th>
            <th scope="col">Resultado</th><th scope="col">Detalle</th></tr></thead><tbody>${validacion.map((v) => `
            <tr><td>${esc(v.prueba)}</td><td><span class="etiqueta ${v.resultado === "OK" ? "ok" : v.resultado === "INFO" ? "" : "error"}">${esc(v.resultado === "INFO" ? "Info" : v.resultado === "OK" ? "Correcto" : "Falla")}</span></td>
              <td>${esc(v.detalle)}</td></tr>`).join("")}</tbody></table>`;
        } catch (err) { aviso(err.message, "error"); }
        ev.target.disabled = false;
      });
    }
  }

  /* ============================================================ administrador */
  async function vistaUsuarios() {
    const { usuarios } = await api("GET", "/usuarios");
    const yo = estado.perfil.id_usuario;
    vista.innerHTML = `
      <div class="encabezado"><div><h1>Usuarios</h1>
        <p>Crea las cuentas del equipo y asigna su rol. Antes de cambiar algo, ten en cuenta: los usuarios finales se registran solos, un cambio de rol se aplica cuando la persona vuelve a iniciar sesión y desactivar una cuenta cierra sus sesiones abiertas.</p></div></div>
      <details class="superficie relleno" id="crear-detalle">
        <summary>Crear una cuenta</summary>
        <form class="formulario" id="crear" novalidate>
          <div class="fila-campos">
            <label class="campo"><span>Nombre</span><input type="text" name="nombre" required maxlength="120"></label>
            <label class="campo"><span>Correo</span><input type="email" name="correo" required></label>
            <label class="campo"><span>Rol</span><select name="rol">${Object.entries(NOMBRE_ROL).map(([v, t]) =>
              `<option value="${v}"${v === "experto" ? " selected" : ""}>${t}</option>`).join("")}</select></label>
          </div>
          <p class="acciones"><button class="boton" type="submit">Crear cuenta</button></p>
        </form>
        <div id="creada"></div>
      </details>
      <div class="superficie tabla-contenedor"><table>
        <thead><tr><th scope="col">Alias</th><th scope="col">Nombre</th><th scope="col">Correo</th>
          <th scope="col">Rol</th><th scope="col">Estado</th></tr></thead>
        <tbody>${usuarios.map((u) => `
          <tr data-id="${u.id_usuario}">
            <td>${esc(u.alias)}${u.id_usuario === yo ? ' <span class="tenue">(tú)</span>' : ""}</td>
            <td>${esc(u.nombre)}</td><td>${esc(u.correo)}</td>
            <td><div class="acciones"><select name="rol" aria-label="Rol de ${esc(u.alias)}"${u.id_usuario === yo ? " disabled" : ""}>
              ${Object.entries(NOMBRE_ROL).map(([v, t]) => `<option value="${v}"${v === u.rol ? " selected" : ""}>${t}</option>`).join("")}
              </select>${u.id_usuario === yo ? "" : '<button class="boton claro pequeno" data-accion="rol" type="button">Cambiar</button>'}</div></td>
            <td><div class="acciones">${u.activo ? '<span class="etiqueta ok">Activa</span>' : '<span class="etiqueta error">Inactiva</span>'}
              ${u.id_usuario === yo ? "" : `<button class="boton ${u.activo ? "peligro" : "claro"} pequeno" data-accion="estado"
                data-activo="${!u.activo}" type="button">${u.activo ? "Desactivar" : "Activar"}</button>`}</div></td>
          </tr>`).join("")}</tbody></table></div>`;
    $(".tabla-contenedor", vista).classList.add("seccion-separada");

    if (sessionStorage.getItem("se.crear")) {
      sessionStorage.removeItem("se.crear");
      $("#crear-detalle").open = true;
      $("#crear input[name=nombre]").focus();
    }
    ponerAccionPrincipal(["usuarios"]);
    $("#crear").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = Object.fromEntries(new FormData(ev.target));
      try {
        const r = await api("POST", "/usuarios", d);
        await vistaUsuarios();
        $("#crear-detalle").open = true;
        $("#creada").innerHTML = `<p class="aviso ok">Cuenta creada para <b>${esc(r.correo)}</b>.
          Contraseña temporal: <code>${esc(r.contrasena_temporal)}</code>. Compártela con la persona;
          deberá cambiarla en su primer ingreso. No se volverá a mostrar.</p>`;
      } catch (err) { aviso(err.message, "error", 8000); }
    });
    $$("button[data-accion]", vista).forEach((b) => b.addEventListener("click", async () => {
      const fila = b.closest("tr");
      try {
        if (b.dataset.accion === "rol") {
          const rol = $("select[name=rol]", fila).value;
          await api("PUT", `/usuarios/${fila.dataset.id}/rol`, { rol });
          aviso("Rol actualizado. Aplica en el próximo inicio de sesión de esa persona.");
        } else {
          await api("PUT", `/usuarios/${fila.dataset.id}/estado`, { activo: b.dataset.activo === "true" });
          aviso(b.dataset.activo === "true" ? "Cuenta activada." : "Cuenta desactivada y sesiones cerradas.");
        }
        vistaUsuarios();
      } catch (err) { aviso(err.message, "error", 8000); }
    }));
  }

  function resumenCambio(a) {
    const antes = a.antes || {}, despues = a.despues || {};
    const clave = despues.codigo || antes.codigo || despues.alias || antes.alias || "";
    if (a.accion === "UPDATE") {
      const cambios = Object.keys(despues).filter((k) => JSON.stringify(antes[k]) !== JSON.stringify(despues[k]));
      return `${clave ? esc(clave) + ": " : ""}${cambios.map((k) =>
        `${esc(k)} ${esc(antes[k])} a ${esc(despues[k])}`).join("; ")}`;
    }
    if (a.tabla === "hechos_hipotesis") {
      const g = a.accion === "DELETE" ? antes : despues;
      return `gránulo hecho ${esc(g.id_hecho)} con hipótesis ${esc(g.id_hipotesis)}, peso ${esc(g.peso)}`;
    }
    return esc(clave);
  }

  async function vistaAuditoria() {
    const { auditoria } = await api("GET", "/auditoria?limite=200");
    const ACCION = { INSERT: "Creación", UPDATE: "Cambio", DELETE: "Eliminación" };
    vista.innerHTML = `
      <div class="encabezado"><div><h1>Auditoría</h1>
        <p>Quién cambió qué y cuándo, en la base de conocimiento y en las cuentas. Úsala para rastrear un cambio que no esperabas.</p></div></div>
      <div class="superficie tabla-contenedor">${auditoria.length ? `<table>
        <thead><tr><th scope="col">Fecha</th><th scope="col">Usuario</th><th scope="col">Rol en la base</th>
          <th scope="col">Tabla</th><th scope="col">Acción</th><th scope="col">Cambio</th></tr></thead>
        <tbody>${auditoria.map((a) => `<tr>
          <td>${esc(fecha(a.fecha))}</td><td>${esc(a.usuario_app || "carga inicial")}</td><td>${esc(a.rol_bd)}</td>
          <td>${esc(a.tabla)}</td><td>${ACCION[a.accion] || esc(a.accion)}</td>
          <td>${resumenCambio(a)}<details><summary>Detalle</summary><pre>${esc(JSON.stringify({ antes: a.antes, despues: a.despues }, null, 1))}</pre></details></td>
        </tr>`).join("")}</tbody></table>` : '<p class="vacio">Aún no hay cambios registrados.</p>'}</div>`;
  }

  /* ============================================================ arranque */
  $("#salir").addEventListener("click", () => cerrarSesion());
  window.addEventListener("hashchange", enrutar);
  if (!CFG.api || !CFG.cliente) {
    vista.innerHTML = '<p class="vacio">Falta la configuración del servicio (config.js).</p>';
    return;
  }
  iniciar();
})();
