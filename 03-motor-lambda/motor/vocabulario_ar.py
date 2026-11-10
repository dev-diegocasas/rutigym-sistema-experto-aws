"""Nombres en inglés de atributos y valores para la política de Automated Reasoning."""

# atributo de la BD -> (variable de la política, tipo, descripción)
# Variables, tipos y valores comparten un solo espacio de nombres en la
# política: los tipos llevan el sufijo "Type" para no chocar con las variables.
VARIABLES = {
    "tecnica_dominada": ("technique", "TechniqueMasteryType",
                         "Whether the user masters the technique of basic exercises "
                         "(squat, push-up, row, deadlift)."),
    "tiempo_entrenando": ("trainingTime", "TrainingTimeType",
                          "How long the user has been training consistently."),
    "equipo_disponible": ("equipment", "EquipmentType",
                          "Training equipment available to the user."),
    "objetivo_principal": ("goal", "GoalType", "The user's main training goal."),
    "fase_priorizada": ("phase", "PhaseType",
                        "Training phase the user wants to prioritize (advanced users)."),
    "dias_semana": ("daysPerWeek", "DaysPerWeekType",
                    "How many days per week the user can train (beginners)."),
    "actividad_actual": ("activityLevel", "ActivityLevelType",
                         "The user's current physical activity level (beginners)."),
}

# (atributo, valor en la BD) -> (valor del enum, descripción)
VALORES = {
    ("tecnica_dominada", "Sí"): ("TECHNIQUE_YES", "The user masters the basic technique."),
    ("tecnica_dominada", "No"): ("TECHNIQUE_NO", "The user does not master the basic technique."),
    ("tecnica_dominada", "No estoy seguro"): ("TECHNIQUE_UNSURE",
                                             "The user is not sure about their technique."),
    ("tiempo_entrenando", "Menos de 6 meses"): ("TIME_UNDER_6_MONTHS", "Less than 6 months."),
    ("tiempo_entrenando", "6 meses a 2 años"): ("TIME_6_MONTHS_TO_2_YEARS",
                                               "Between 6 months and 2 years."),
    ("tiempo_entrenando", "Más de 2 años"): ("TIME_OVER_2_YEARS", "More than 2 years."),
    ("equipo_disponible", "Básico o en casa"): ("EQUIPMENT_HOME_BASIC",
                                               "Basic equipment or training at home."),
    ("equipo_disponible", "Gimnasio completo"): ("EQUIPMENT_FULL_GYM", "A fully equipped gym."),
    ("objetivo_principal", "Fuerza"): ("GOAL_STRENGTH", "Gain strength."),
    ("objetivo_principal", "Hipertrofia"): ("GOAL_HYPERTROPHY", "Gain muscle mass."),
    ("objetivo_principal", "Resistencia"): ("GOAL_ENDURANCE", "Improve endurance."),
    ("objetivo_principal", "Pérdida de grasa"): ("GOAL_FAT_LOSS", "Lose body fat."),
    ("objetivo_principal", "Rendimiento deportivo"): ("GOAL_SPORTS_PERFORMANCE",
                                                     "Improve sports performance."),
    ("fase_priorizada", "Volumen"): ("PHASE_VOLUME", "Prioritize training volume."),
    ("fase_priorizada", "Intensidad"): ("PHASE_INTENSITY", "Prioritize training intensity."),
    ("dias_semana", "2 días"): ("DAYS_TWO", "Two days per week."),
    ("dias_semana", "3 o más días"): ("DAYS_THREE_OR_MORE", "Three or more days per week."),
    ("actividad_actual", "Sedentario"): ("ACTIVITY_SEDENTARY", "Mostly sedentary."),
    ("actividad_actual", "Algo activo"): ("ACTIVITY_SOMEWHAT_ACTIVE",
                                         "Somewhat active (walks or plays sports occasionally)."),
}

VARIABLE_RUTINA = ("assignedRoutine", "RoutineType",
                   "The training routine the expert system assigns to the user.")


def valor_rutina(codigo_hipotesis):
    return f"ROUTINE_{codigo_hipotesis}"


def enunciado_verificacion(hechos, codigo_hipotesis):
    """Construye la pregunta (premisas) y la respuesta (afirmación) en inglés,
    usando exactamente los nombres de la política para evitar ambigüedad."""
    partes = []
    for h in hechos:
        var = VARIABLES[h["atributo"]][0]
        enum, desc = VALORES[(h["atributo"], h["valor"])]
        partes.append(f"{var} is {enum} ({desc.rstrip('.').lower()})")
    pregunta = ("A user of the training expert system reports: " + "; ".join(partes)
                + ". Which training routine should be assigned to this user?")
    respuesta = f"The assignedRoutine for this user is {valor_rutina(codigo_hipotesis)}."
    return pregunta, respuesta
