# Árbol de decisión actual · Rutigym (noviembre de 2026)

Reemplaza el árbol de octubre (`arbol_decision.png`). Ese árbol tenía 26 hojas y el nivel Principiante solo se dividía por equipo. Ahora el nivel Principiante se divide además por días por semana (P6) y por actividad actual (P7), y el árbol tiene **32 hojas (H01–H32)** y **48 caminos, que son las reglas R01–R48**.

## Cómo se lee

1. **P1 · Técnica.** Si la respuesta es No o No estoy seguro, el nivel es Principiante. Si es Sí, se pasa a P2.
2. **P2 · Tiempo entrenando.**
   - Menos de 6 meses: Principiante.
   - Entre 6 meses y 2 años: Intermedio.
   - Más de 2 años: Avanzado.
3. **P3 · Equipo** (Básico o en casa, o Gimnasio completo). Se pregunta en los tres niveles.
4. Después, cada nivel sigue su propia rama:
   - **Principiante:** P6, días por semana (2, o 3 o más), y luego P7, actividad (Sedentario o Algo activo). Son 8 hojas: H01, H02 y H27–H32.
   - **Intermedio:** P4, objetivo (Fuerza, Hipertrofia, Resistencia, Pérdida de grasa o Rendimiento deportivo). Son 10 hojas: H03–H12.
   - **Avanzado:** P4, objetivo. Si el objetivo es Fuerza o Hipertrofia, se pregunta además P5, fase (Volumen o Intensidad). Son 14 hojas: H13–H26.

Las reglas son 48 y las hojas 32 porque al nivel Principiante se llega por tres caminos: técnica No, técnica No estoy seguro, o técnica Sí con menos de 6 meses. Esos 3 caminos, por 2 equipos, 2 opciones de días y 2 de actividad, dan 24 reglas. A ellas se suman 10 reglas del nivel Intermedio y 14 del Avanzado.

## Del árbol al motor

El árbol es la referencia del experto. El motor no lo recorre con condicionales: cada camino se convierte en **gránulos** (`hechos_hipotesis`), es decir, hechos que respaldan una hipótesis con un peso. El motor calcula la probabilidad de las 32 hipótesis con esos gránulos y solo hace las preguntas que pueden cambiar la hipótesis líder.

Hay dos controles de que ambos dicen lo mismo:
- `verificar_caminos.py` recorre las 48 reglas y las 720 combinaciones de respuestas, y confirma que siempre gana la hoja del árbol.
- **Automated Reasoning** comprueba cada consulta terminada contra las 48 reglas traducidas a lógica formal.

## Diagrama (Mermaid)

```mermaid
flowchart LR
  S(["Solicitud de rutina"]) --> P1{"P1 · ¿Dominas la técnica básica?"}
  P1 -- "No / No estoy seguro" --> PR["Nivel PRINCIPIANTE<br>P3 · ¿Con qué equipo cuentas?"]
  P1 -- "Sí" --> P2{"P2 · ¿Cuánto tiempo llevas entrenando?"}
  P2 -- "Menos de 6 meses" --> PR
  P2 -- "6 meses a 2 años" --> IN["Nivel INTERMEDIO<br>P3 · ¿Con qué equipo cuentas?"]
  P2 -- "Más de 2 años" --> AV["Nivel AVANZADO<br>P3 · ¿Con qué equipo cuentas?"]
  PR -- "Básico o en casa" --> PRC{"P6 · ¿Días por semana?"}
  PRC -- "2 días" --> PRC2{"P7 · ¿Actividad actual?"}
  PRC -- "3 o más días" --> PRC3{"P7 · ¿Actividad actual?"}
  PR -- "Gimnasio completo" --> PRG{"P6 · ¿Días por semana?"}
  PRG -- "2 días" --> PRG2{"P7 · ¿Actividad actual?"}
  PRG -- "3 o más días" --> PRG3{"P7 · ¿Actividad actual?"}
  PRC3 -- "Sedentario" --> H01[["H01"]]
  PRG3 -- "Sedentario" --> H02[["H02"]]
  PRC2 -- "Sedentario" --> H27[["H27"]]
  PRC2 -- "Algo activo" --> H28[["H28"]]
  PRC3 -- "Algo activo" --> H29[["H29"]]
  PRG2 -- "Sedentario" --> H30[["H30"]]
  PRG2 -- "Algo activo" --> H31[["H31"]]
  PRG3 -- "Algo activo" --> H32[["H32"]]
  IN -- "Básico o en casa" --> INC{"P4 · ¿Objetivo principal?"}
  INC -- "Fuerza" --> H03[["H03"]]
  INC -- "Hipertrofia" --> H04[["H04"]]
  INC -- "Resistencia" --> H05[["H05"]]
  INC -- "Pérdida de grasa" --> H06[["H06"]]
  INC -- "Rendimiento deportivo" --> H07[["H07"]]
  IN -- "Gimnasio completo" --> ING{"P4 · ¿Objetivo principal?"}
  ING -- "Fuerza" --> H08[["H08"]]
  ING -- "Hipertrofia" --> H09[["H09"]]
  ING -- "Resistencia" --> H10[["H10"]]
  ING -- "Pérdida de grasa" --> H11[["H11"]]
  ING -- "Rendimiento deportivo" --> H12[["H12"]]
  AV -- "Básico o en casa" --> AVC{"P4 · ¿Objetivo principal?"}
  AVC -- "Fuerza" --> AVCF{"P5 · ¿Fase priorizada?"}
  AVCF -- "Volumen" --> H13[["H13"]]
  AVCF -- "Intensidad" --> H14[["H14"]]
  AVC -- "Hipertrofia" --> AVCH{"P5 · ¿Fase priorizada?"}
  AVCH -- "Volumen" --> H15[["H15"]]
  AVCH -- "Intensidad" --> H16[["H16"]]
  AVC -- "Resistencia" --> H17[["H17"]]
  AVC -- "Pérdida de grasa" --> H18[["H18"]]
  AVC -- "Rendimiento deportivo" --> H19[["H19"]]
  AV -- "Gimnasio completo" --> AVG{"P4 · ¿Objetivo principal?"}
  AVG -- "Fuerza" --> AVGF{"P5 · ¿Fase priorizada?"}
  AVGF -- "Volumen" --> H20[["H20"]]
  AVGF -- "Intensidad" --> H21[["H21"]]
  AVG -- "Hipertrofia" --> AVGH{"P5 · ¿Fase priorizada?"}
  AVGH -- "Volumen" --> H22[["H22"]]
  AVGH -- "Intensidad" --> H23[["H23"]]
  AVG -- "Resistencia" --> H24[["H24"]]
  AVG -- "Pérdida de grasa" --> H25[["H25"]]
  AVG -- "Rendimiento deportivo" --> H26[["H26"]]
  classDef hoja fill:#262626,color:#fff,stroke:#262626
  classDef nivel fill:#c8102e,color:#fff,stroke:#c8102e
  class H01,H02,H03,H04,H05,H06,H07,H08,H09,H10,H11,H12,H13,H14,H15,H16,H17,H18,H19,H20,H21,H22,H23,H24,H25,H26,H27,H28,H29,H30,H31,H32 hoja
  class PR,IN,AV nivel
```
