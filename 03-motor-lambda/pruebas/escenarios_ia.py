"""
Escenarios de la Fase 3: conversación en lenguaje natural (Lex), mensajes y
explicación redactados (Nova) y verificación formal (Automated Reasoning).
"""

from escenarios import (AUTOMATICO as LAURA, CRISTIAN, NUEVA, REGLAS, Resultados, SIMON,
                        cargar_textos, consulta_completa)

CONVERSACIONES = [
    ("Principiante en casa, 2 días, sedentario", "H27",
     ["la verdad no", "en mi casa", "solo los fines de semana", "trabajo sentado todo el día"]),
    ("Avanzado, gimnasio, fuerza, intensidad", "H21",
     ["sí, los domino", "llevo como tres años", "voy al gym", "quiero ser más fuerte",
      "prefiero cargas altas"]),
    ("Intermedio, gimnasio, pérdida de grasa", "H11",
     ["claro", "como un año", "en el gimnasio", "quiero bajar de peso"]),
]


def conversar(llamar, identidad, frases):
    st, c = llamar("iniciar_consulta", identidad, NUEVA)
    if st != 200:
        return None, [], c
    mensajes = [c.get("mensaje")]
    for frase in frases:
        if c.get("estado") != "en_curso":
            break
        st, c = llamar("responder_texto", identidad, {"id_consulta": c["id_consulta"], "texto": frase})
        if st != 200:
            return None, mensajes, c
        if c.get("no_entendido"):
            return c, mensajes, f"no entendió «{frase}» ({c.get('interpretacion')})"
        mensajes.append(c.get("mensaje"))
    return c, mensajes, None


def correr_ia(llamar):
    res = Resultados()
    verificables = []

    print("\n1. Bedrock Nova (redacción) con una consulta por botones")
    st, c = llamar("iniciar_consulta", LAURA, NUEVA)
    res.check(st == 200 and c.get("mensaje"), "Nova redacta el mensaje de bienvenida",
              c.get("mensaje") or c.get("error"))
    cargar_textos(llamar)
    perfil = dict(next(cond for r, h, cond in REGLAS if r == "R25"))
    final, _, error = consulta_completa(llamar, LAURA, perfil)
    ok = final is not None and final.get("estado") == "terminada"
    res.check(ok and final["diagnostico"]["rutina"]["codigo"] == "H21",
              "Consulta por botones (R25) concluye H21", error)
    if ok:
        verificables.append((final["id_consulta"], "H21"))
        explicacion = final["diagnostico"].get("explicacion_ia")
        res.check(bool(explicacion), "Nova redacta la explicación final de la rutina", explicacion)
        if explicacion:
            print(f"     «{explicacion[:220]}»")

    print("\n2. Conversación en lenguaje natural (Amazon Lex)")
    for nombre, esperada, frases in CONVERSACIONES:
        final, mensajes, error = conversar(llamar, LAURA, frases)
        obtenida = final and final.get("diagnostico", {}).get("rutina", {}).get("codigo")
        res.check(error is None and obtenida == esperada,
                  f"{nombre}: {' / '.join(frases)} → {esperada}", error or obtenida)
        if final and final.get("estado") == "terminada":
            verificables.append((final["id_consulta"], esperada))
            origenes = {h["origen"] for h in final["hechos"]}
            res.check(origenes == {"texto_libre"},
                      "   los hechos quedaron registrados como texto libre con la frase original")

    st, c = llamar("iniciar_consulta", LAURA, NUEVA)
    pregunta = c.get("pregunta", {}).get("codigo")
    st, r = llamar("responder_texto", LAURA, {"id_consulta": c.get("id_consulta"),
                                               "texto": "me gusta mucho el helado de mora"})
    res.check(st == 200 and r.get("no_entendido") and r.get("pregunta", {}).get("codigo") == pregunta,
              "Una frase sin relación no cambia nada: el sistema vuelve a preguntar lo mismo")

    print("\n3. Verificación formal desde el motor (Bedrock Automated Reasoning)")
    for idc, esperada in verificables:
        st, v = llamar("verificar_formal", CRISTIAN, {"id_consulta": idc})
        res.check(st == 200 and v.get("resultado") == "VALID",
                  f"El experto verifica la consulta {idc} ({esperada}): VALID",
                  f"{v.get('resultado') or v.get('error')} {v.get('detalle', {}).get('error', '')}")
    if verificables:
        st, v = llamar("verificar_formal", LAURA, {"id_consulta": verificables[0][0]})
        res.check(st == 403, "El usuario final no puede lanzar la verificación formal")
        st, v = llamar("obtener_consulta", SIMON, {"id": verificables[0][0]})
        tipos = [t["tipo"] for t in v.get("traza", [])]
        res.check(st == 200 and "verificacion_formal" in tipos and v.get("verificacion_formal") == "VALID",
                  "La verificación queda en la traza y en la consulta")

    fallos = sum(not ok for ok, _, _ in res.filas)
    print(f"\n{len(res.filas) - fallos}/{len(res.filas)} correctas"
          + (" · TODO CORRECTO" if not fallos else f" · {fallos} FALLOS"))
    return fallos
