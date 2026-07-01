import streamlit as st
import pdfplumber
import re
from PIL import Image
import pytesseract

# Configuración de la página web
st.set_page_config(page_title="SUPERPRO de Notas", page_icon="🎯", layout="wide")

# --- CSS: OPTIMIZACIÓN DE ESPACIO PARA MÓVIL Y PC ---
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1.5rem;
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        max-width: 1100px;
    }
    div[data-testid="stVerticalBlock"] { gap: 0.3rem; }
    div[data-testid="stExpander"] details summary p {
        font-size: 0.95rem;
        font-weight: 600;
    }
    div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] { padding-top: 0.3rem; }
    div[data-testid="stMetricValue"] { font-size: 1.3rem; }
    div[data-testid="stMetricLabel"] { font-size: 0.78rem; }
    div[data-testid="column"] { padding: 0 0.3rem !important; }
    .stNumberInput input { padding: 0.3rem 0.4rem; }
    .stNumberInput, .stSelectbox, .stCheckbox, .stTextInput { margin-bottom: -0.4rem; }
    .stCheckbox { padding-top: 0.1rem; }
    label[data-testid="stWidgetLabel"] p { margin-bottom: 0.1rem; }
    hr { margin: 0.4rem 0; }

    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.4rem;
            padding-right: 0.4rem;
            padding-top: 0.6rem;
        }
        h1 { font-size: 1.25rem; }
        h2 { font-size: 1.05rem; }
        h3 { font-size: 0.95rem; }
        div[data-testid="stExpander"] details summary p { font-size: 0.8rem; }
        div[data-testid="stMetricValue"] { font-size: 0.95rem; }
        div[data-testid="stMetricLabel"] { font-size: 0.65rem; }
        div[data-testid="column"] { padding: 0 0.15rem !important; min-width: 0 !important; }
        .stNumberInput label, .stCheckbox label, .stTextInput label, .stSelectbox label { font-size: 0.68rem; }
        .stMarkdown p { font-size: 0.8rem; }
        /* En pantallas angostas ocultamos los botones +/- para ganar ancho;
           el valor se sigue pudiendo escribir directamente. */
        .stNumberInput button { display: none; }
        .stNumberInput input { text-align: center; padding: 0.3rem 0.2rem; }
    }
</style>
""", unsafe_allow_html=True)

# --- BARRA LATERAL: CONFIGURACIÓN GLOBAL ---
with st.sidebar:
    st.header("⚙️ Configuración Global")

    nota_minima_global = st.number_input(
        "Nota mínima de aprobación", min_value=0.0, max_value=20.0,
        value=10.00, step=0.5, format="%.2f"
    )

    n_pcs_eliminar_global = st.number_input(
        "N° PCs a eliminar", min_value=0, max_value=5, value=1, step=1
    )

    n_labs_eliminar_global = st.number_input(
        "N° Laboratorios a eliminar", min_value=0, max_value=5, value=2, step=1
    )

    pcs_protegidas_global = st.multiselect(
        "PCs que NO se pueden eliminar",
        options=["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"]
    )

    st.caption(
        "💡 En 'Configuración de Pesos' de cada curso puedes escribir reglas separadas "
        "por comas, ej: `ef vale por 2, pc4 vale por 2, pc4 se elimina`. "
        "La regla `se elimina` es un caso especial: saca esa nota del promedio aunque "
        "esté protegida arriba."
    )


def calcular_pf_curso(codigo, pcs, labs, ep, ef, sus, tiene_labs, tiene_ep, tiene_ef, tiene_sus, formula_texto,
                       nota_minima=10.0, n_pcs_eliminar=1, n_labs_eliminar=2, pcs_protegidas=None,
                       pcs_nd=None, pcs_0a=None, ef_nd=False):
    """
    Calcula los promedios oficiales aplicando pesos dinámicos extras basados en siglas:
    PC (Práctica), LB (Laboratorio), EP (Parcial), EF (Final).

    Cuando una práctica vale 0 hay tres estados posibles (definidos por pcs_nd / pcs_0a):
    - ND (pendiente):        pcs_nd[i] = True  -> aún no se rinde, activa el modo "falta rendir"
                              y queda fuera de la eliminación automática.
    - 0 real (eliminable):   pcs_nd[i] = False, pcs_0a[i] = False -> cuenta en el promedio como
                              cualquier nota real y SÍ puede salir elegida como "la peor nota".
    - 0A (obligatorio):      pcs_0a[i] = True -> cuenta en el promedio y JAMÁS se elimina,
                              sin importar si está o no en la lista de PCs protegidas.
    ef_nd:  True -> el Examen Final aún no se rindió (0 = pendiente).
            False -> el 0 (si lo hay) es una nota real ya rendida.
    """
    if pcs_protegidas is None:
        pcs_protegidas = []
    if pcs_nd is None:
        pcs_nd = [nota == 0 for nota in pcs]
    if pcs_0a is None:
        pcs_0a = [False] * len(pcs)
    pcs_nd = list(pcs_nd)
    pcs_0a = list(pcs_0a)
    while len(pcs_nd) < len(pcs):
        pcs_nd.append(pcs[len(pcs_nd)] == 0)
    while len(pcs_0a) < len(pcs):
        pcs_0a.append(False)

    # Convertir nombres tipo "PC1" a índices (0-based) protegidos contra eliminación
    indices_protegidos = set()
    for p in pcs_protegidas:
        m = re.match(r'^PC\s*(\d+)$', str(p).strip().upper())
        if m:
            indices_protegidos.add(int(m.group(1)) - 1)

    # "0A": marcado explícitamente como obligatorio -> nunca se elimina como "peor nota"
    for i, es_0a in enumerate(pcs_0a):
        if es_0a:
            indices_protegidos.add(i)

    # Inicializar pesos base
    pesos_pcs = [1] * len(pcs)
    pesos_labs = [1] * len(labs)
    peso_ep = 1
    peso_ef = 2  # Peso 2 por defecto

    # Índices forzados a eliminar por fórmula (caso especial, ignora protección)
    indices_forzados_eliminar_pc = set()
    indices_forzados_eliminar_lb = set()

    es_valido = True
    msg_error = ""

    if formula_texto.strip():
        partes = [p.strip() for p in formula_texto.split(',') if p.strip()]
        for parte in partes:
            coincidencia = re.match(r'^(pc|lb|ep|ef)\s*(\d*)\s*vale\s*por\s*(\d+)$', parte.lower())
            coincidencia_elim = None
            if not coincidencia:
                coincidencia_elim = re.match(r'^(pc|lb)\s*(\d+)\s*se\s*elimina$', parte.lower())

            if coincidencia:
                tipo, num, peso = coincidencia.groups()
                valor_peso = int(peso)
                if tipo == 'pc':
                    if num:
                        idx = int(num) - 1
                        if 0 <= idx < len(pesos_pcs): pesos_pcs[idx] = valor_peso
                    else:
                        pesos_pcs = [valor_peso] * len(pcs)
                elif tipo == 'lb':
                    if num:
                        idx = int(num) - 1
                        if 0 <= idx < len(pesos_labs): pesos_labs[idx] = valor_peso
                    else:
                        pesos_labs = [valor_peso] * len(labs)
                elif tipo == 'ep': peso_ep = valor_peso
                elif tipo == 'ef': peso_ef = valor_peso

            elif coincidencia_elim:
                tipo_e, num_e = coincidencia_elim.groups()
                idx_e = int(num_e) - 1
                if tipo_e == 'pc' and 0 <= idx_e < len(pcs):
                    indices_forzados_eliminar_pc.add(idx_e)
                elif tipo_e == 'lb' and 0 <= idx_e < len(labs):
                    indices_forzados_eliminar_lb.add(idx_e)

            else:
                es_valido = False
                if parte.lower() in ['pc', 'lb', 'ep', 'ef'] or re.match(r'^(pc|lb)\d+$', parte.lower()):
                    msg_error = f"⚠️ Sintaxis incompleta en '{parte}'. Usa, ej: '{parte} vale por 2' o 'pc4 se elimina'."
                else:
                    msg_error = f"❌ Parámetro inválido: '{parte}'."
                break

    # Índices activos de PC (los forzados a eliminar por fórmula quedan totalmente fuera)
    indices_activos_pc = [i for i in range(len(pcs)) if i not in indices_forzados_eliminar_pc]

    # Identificar cuáles PCs faltan por rendir (ND), solo entre las activas
    indices_pcs_faltantes = [i for i in indices_activos_pc if pcs_nd[i]]
    hay_pcs_faltantes = len(indices_pcs_faltantes) > 0

    # 1. Lógica de Prácticas Calificadas (Eliminación de las N peores, respetando protegidas y 0A)
    indices_candidatos = [i for i in indices_activos_pc if i not in indices_protegidos]
    n_eliminar_real = min(n_pcs_eliminar, max(0, len(indices_candidatos) - 1)) if len(indices_activos_pc) > 1 else 0

    if n_eliminar_real > 0 and not hay_pcs_faltantes:
        indices_a_eliminar_pc = sorted(indices_candidatos, key=lambda i: pcs[i])[:n_eliminar_real]
    else:
        indices_a_eliminar_pc = []

    indices_finales_pc = [i for i in indices_activos_pc if i not in indices_a_eliminar_pc]
    suma_ponderada_pc = sum(pcs[i] * pesos_pcs[i] for i in indices_finales_pc)
    suma_pesos_pc = sum(pesos_pcs[i] for i in indices_finales_pc)
    prom_pc = suma_ponderada_pc / suma_pesos_pc if suma_pesos_pc > 0 else 0

    # 2. Lógica de laboratorios/láminas (Eliminación de las N peores)
    prom_lab = 0
    if tiene_labs and labs:
        indices_activos_lb = [i for i in range(len(labs)) if i not in indices_forzados_eliminar_lb]
        labs_activos = [labs[i] for i in indices_activos_lb]
        hay_ceros_lab = any(nota == 0 for nota in labs_activos)
        n_labs_eliminar_real = min(n_labs_eliminar, max(0, len(indices_activos_lb) - 1))

        if not hay_ceros_lab and n_labs_eliminar_real > 0:
            ordenados = sorted(indices_activos_lb, key=lambda i: labs[i])
            indices_a_eliminar_lb = ordenados[:n_labs_eliminar_real]
        else:
            indices_a_eliminar_lb = []

        indices_finales_lb = [i for i in indices_activos_lb if i not in indices_a_eliminar_lb]
        suma_ponderada_lab = sum(labs[i] * pesos_labs[i] for i in indices_finales_lb)
        suma_pesos_lab = sum(pesos_labs[i] for i in indices_finales_lb)
        prom_lab = suma_ponderada_lab / suma_pesos_lab if suma_pesos_lab > 0 else 0

    pp = (prom_pc + prom_lab) / 2 if tiene_labs else prom_pc

    # Sustitutorio
    ep_final, ef_final = ep, ef
    if tiene_sus and sus > 0:
        if tiene_ep and tiene_ef:
            if ep_final < ef_final:
                if sus > ep_final: ep_final = sus
            else:
                if sus > ef_final: ef_final = sus
        elif tiene_ef and sus > ef_final: ef_final = sus
        elif tiene_ep and sus > ep_final: ep_final = sus

    # Promedio Final actual
    divisor_examen = (peso_ep if tiene_ep else 0) + (peso_ef if tiene_ef else 0) + 1
    if tiene_ep and tiene_ef:
        pf_actual = ((ep_final * peso_ep) + (ef_final * peso_ef) + pp) / divisor_examen
        ef_necesario = ((nota_minima * divisor_examen) - (ep_final * peso_ep) - pp) / peso_ef
    elif tiene_ef:
        pf_actual = ((ef_final * peso_ef) + pp) / divisor_examen
        ef_necesario = ((nota_minima * divisor_examen) - pp) / peso_ef
    elif tiene_ep:
        pf_actual = ((ep_final * peso_ep) + pp) / divisor_examen
        ef_necesario = 0
    else:
        pf_actual = pp
        ef_necesario = 0

    # --- MOTOR DE TIPS PRO ACTIVO ---
    tip_estrategia = ""
    sus_necesario = 0

    if pf_actual < nota_minima:
        puntos_objetivo_totales = nota_minima * divisor_examen

        # Caso 1: Falta rendir alguna PC y el Examen Final aún no se rindió (ND)
        if hay_pcs_faltantes and tiene_ef and ef_nd:
            nota_simulada_pc = 14
            pcs_simuladas = list(pcs)
            for i in indices_pcs_faltantes:
                pcs_simuladas[i] = nota_simulada_pc

            if n_eliminar_real > 0:
                elim_sim = sorted(indices_candidatos, key=lambda i: pcs_simuladas[i])[:n_eliminar_real]
            else:
                elim_sim = []
            finales_sim = [i for i in indices_activos_pc if i not in elim_sim]
            suma_sim = sum(pcs_simuladas[i] * pesos_pcs[i] for i in finales_sim)
            pesos_sim = sum(pesos_pcs[i] for i in finales_sim)
            p_pc_sim = suma_sim / pesos_sim if pesos_sim > 0 else 0

            pp_simulado = (p_pc_sim + prom_lab) / 2 if tiene_labs else p_pc_sim
            ef_comb_necesario = (puntos_objetivo_totales - (ep_final * peso_ep) - pp_simulado) / peso_ef

            nombre_pcs_faltantes = ", ".join([f"PC {i+1}" for i in indices_pcs_faltantes])
            if 0 < ef_comb_necesario <= 20:
                tip_estrategia = f"💡 Plan de Remonte: Si sacas un **{nota_simulada_pc}** en la {nombre_pcs_faltantes}, solo necesitarás un **{ef_comb_necesario:.1f}** en el Examen Final."
            else:
                ef_comb_necesario = (puntos_objetivo_totales - (ep_final * peso_ep) - ((20 + prom_lab)/2 if tiene_labs else 20)) / peso_ef
                tip_estrategia = f"⚠️ ¡Falta presión!: Necesitas asegurar notas altas. Si sacas **20** en la {nombre_pcs_faltantes}, requieres mínimo un **{max(0.0, ef_comb_necesario):.1f}** en el Final."

        # Caso 2: Falta rendir alguna PC pero el EF ya se rindió (o no existe)
        elif hay_pcs_faltantes:
            pp_necesario = puntos_objetivo_totales - (ep_final * peso_ep) - (ef_final * peso_ef)
            prom_pc_objetivo = (pp_necesario * 2) - prom_lab if tiene_labs else pp_necesario

            suma_pesos_activos = sum(pesos_pcs[i] for i in indices_activos_pc)
            suma_actual_pcs = sum(pcs[i] * pesos_pcs[i] for i in indices_activos_pc)
            diferencia_necesaria = (prom_pc_objetivo * suma_pesos_activos) - suma_actual_pcs
            pesos_faltantes = sum(pesos_pcs[i] for i in indices_pcs_faltantes)

            if pesos_faltantes > 0:
                nota_pc_requerida = diferencia_necesaria / pesos_faltantes
                nombre_pcs_faltantes = ", ".join([f"PC {i+1}" for i in indices_pcs_faltantes])

                if 0 < nota_pc_requerida <= 20:
                    tip_estrategia = f"🎯 Para aprobar directo con las prácticas: Necesitas un promedio de **{nota_pc_requerida:.1f}** en la {nombre_pcs_faltantes}."
                else:
                    tip_estrategia = f"❌ Matemáticamente imposible aprobar solo con las prácticas (requieres {nota_pc_requerida:.1f}). Tu camino es el Examen Sustitutorio."

        # Calcular Sustitutorio
        if tiene_sus:
            if tiene_ep and tiene_ef:
                sus_reemplaza_ef = (puntos_objetivo_totales - (ep_final * peso_ep) - pp) / peso_ef
                sus_reemplaza_ep = (puntos_objetivo_totales - (ef_final * peso_ef) - pp) / peso_ep
                sus_necesario = sus_reemplaza_ep if ep_final < ef_final else sus_reemplaza_ef
            elif tiene_ef: sus_necesario = (puntos_objetivo_totales - pp) / peso_ef
            elif tiene_ep: sus_necesario = (puntos_objetivo_totales - pp) / peso_ep

    return prom_pc, prom_lab, pp, pf_actual, max(0.0, ef_necesario), sus_necesario, hay_pcs_faltantes, es_valido, msg_error, tip_estrategia


def sugerir_creditos(codigo):
    if "BMA" in codigo or "BQU" in codigo: return 5
    if "BIC" in codigo: return 3
    return 2


def extraer_texto_ocr(archivo_imagen):
    """Aplica OCR a una imagen (foto/captura de notas) y devuelve el texto detectado."""
    imagen = Image.open(archivo_imagen)
    if imagen.mode != "RGB":
        imagen = imagen.convert("RGB")
    texto = pytesseract.image_to_string(imagen, lang="eng")
    return texto


# --- HELPERS COMPARTIDOS DE PARSEO (tabla PDF, texto de respaldo y OCR) ---

def _crear_curso(cursos, codigo, nombre):
    cursos[codigo] = {
        "nombre": nombre, "pcs": [], "labs": [], "ep": 0, "ef": 0, "sus": 0,
        "tiene_labs": False, "tiene_ep": False, "tiene_ef": False, "tiene_sus": False
    }
    return codigo


def _procesar_fila_evaluacion(cursos, curso_actual, eval_nombre_raw, nota_raw):
    """Registra una fila (nombre de evaluación + nota) dentro del curso activo."""
    if not curso_actual or curso_actual not in cursos:
        return
    eval_nom = str(eval_nombre_raw).upper()
    if "LETRA" in eval_nom or "FECHA" in eval_nom or "MODALIDAD" in eval_nom:
        return

    nota_str = str(nota_raw).strip()
    nota = int(nota_str) if nota_str.isdigit() else 0
    info = cursos[curso_actual]

    if "LABORATORIO" in eval_nom or "LÁMINA" in eval_nom or "LAMINA" in eval_nom or curso_actual == "AA237F":
        info["tiene_labs"] = True
    if "PARCIAL" in eval_nom: info["tiene_ep"] = True
    if "FINAL" in eval_nom: info["tiene_ef"] = True
    if "SUSTITUTORIO" in eval_nom or "SUST." in eval_nom: info["tiene_sus"] = True
    if "FINAL" in eval_nom or "PARCIAL" in eval_nom: info["tiene_sus"] = True

    if "PRACTICA" in eval_nom or "PRÁCTICA" in eval_nom:
        info["pcs"].append(nota)
    elif "LABORATORIO" in eval_nom or "LÁMINA" in eval_nom or "LAMINA" in eval_nom:
        info["labs"].append(nota)
    elif "PARCIAL" in eval_nom:
        info["ep"] = nota
    elif "FINAL" in eval_nom:
        info["ef"] = nota
    elif "SUSTITUTORIO" in eval_nom:
        info["sus"] = nota


_PATRON_CURSO_TEXTO = re.compile(r'^([A-Za-z]{2,4}\s?\d{2,4}[A-Za-z]?)\s*[-–—]\s*(.+)$')
_PATRON_EVAL_TEXTO = re.compile(r'^(.*?\D)\s*(\d{1,2})\s*$')


def procesar_lineas_a_cursos(texto):
    """
    Parsea texto plano (proveniente de OCR de una imagen, o de una página de PDF
    donde no se detectó ninguna tabla) línea por línea y construye el diccionario
    'cursos', detectando encabezados de curso (CODIGO-NOMBRE) y filas de evaluación.
    """
    cursos = {}
    curso_actual = None
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]

    for linea in lineas:
        m_curso = _PATRON_CURSO_TEXTO.match(linea)
        if m_curso:
            codigo_actual = m_curso.group(1).replace(" ", "").upper()
            curso_actual = _crear_curso(cursos, codigo_actual, m_curso.group(2).strip())
            continue

        if not curso_actual:
            continue

        m_eval = _PATRON_EVAL_TEXTO.match(linea)
        if not m_eval:
            continue

        _procesar_fila_evaluacion(cursos, curso_actual, m_eval.group(1).strip(), m_eval.group(2))

    return cursos


def _combinar_curso(cursos_base, cursos_nuevos):
    """Fusiona cursos detectados por texto de respaldo en el diccionario principal,
    evitando pisar un curso que ya exista con datos."""
    for codigo, info in cursos_nuevos.items():
        if codigo not in cursos_base:
            cursos_base[codigo] = info
        else:
            base = cursos_base[codigo]
            # Solo añade lo que falte, para no duplicar filas ya leídas por tabla
            if not base["pcs"] and info["pcs"]: base["pcs"] = info["pcs"]
            if not base["labs"] and info["labs"]: base["labs"] = info["labs"]
            if not base["ep"] and info["ep"]: base["ep"] = info["ep"]
            if not base["ef"] and info["ef"]: base["ef"] = info["ef"]
            if not base["sus"] and info["sus"]: base["sus"] = info["sus"]
            base["tiene_labs"] = base["tiene_labs"] or info["tiene_labs"]
            base["tiene_ep"] = base["tiene_ep"] or info["tiene_ep"]
            base["tiene_ef"] = base["tiene_ef"] or info["tiene_ef"]
            base["tiene_sus"] = base["tiene_sus"] or info["tiene_sus"]


# --- INTERFAZ GRÁFICA ---
st.title("🎯 SUPERPRO de Notas")

st.markdown("""
Esta aplicación ha sido diseñada como una herramienta avanzada de apoyo para estudiantes universitarios de pregrado.
Su propósito es facilitar el control, simulación y cálculo automatizado de promedios ponderados por ciclo de forma precisa,
permitiendo proyectar las calificaciones necesarias en evaluaciones pendientes (prácticas, parciales, finales y sustitutorios)
para lograr la meta académica de aprobación.
""")

with st.expander("ℹ️ ¿Cómo debe verse tu documento para que el programa lo registre correctamente?", expanded=False):
    st.markdown("""
    Para garantizar que el lector automático procese tus asignaturas sin errores, el archivo PDF cargado (ej. reporte de la **DIRCE**) debe contener una estructura limpia y tabular similar a la siguiente:

    ### 1. Estructura de Bloque por Curso
    Cada asignatura debe iniciar con su respectivo código y nombre oficial separados por un guion:
    * `BMA01-ANÁLISIS MATEMÁTICO I`
    * `MS211-SEGURIDAD E HIGIENE INDUSTRIAL`

    ### 2. Formato de las Tablas de Calificaciones
    Dentro de cada bloque de curso, las evaluaciones y sus respectivas notas deben estar dispuestas en dos columnas claras (Evaluación | Nota):

    ```text
    +----------------------------------+----+
    | PRACTICA CALIFICADA 1            | 08 |
    | PRACTICA CALIFICADA 2            | 04 |
    | PRACTICA CALIFICADA 3            | 07 |
    | PRACTICA CALIFICADA 4            | 10 |
    | EXAMEN PARCIAL                   | 11 |
    | EXAMEN FINAL                     | 00 |
    +----------------------------------+----+
    ```
    *Nota: Las evaluaciones que aún no rindas pueden figurar con `0` o `00`. Cada vez que una PC quede en 0, la app te deja elegir qué significa ese 0: **ND** (pendiente, aún no la rindes), **0 real** (nota tomada, puede salir elegida como la peor y eliminarse) o **0A** (nota tomada, cuenta obligatoria y nunca se elimina).*

    ### 3. Tablas partidas entre dos caras/páginas
    Si una tabla de un curso continúa en la siguiente página sin repetir bordes, el lector ahora también revisa el texto plano de esa página como respaldo, para no perder las filas que quedaron en la segunda cara.
    """)

st.markdown("---")

archivo_subido = st.file_uploader(
    "📂 Arrastra aquí tu archivo 'doc.pdf' o una foto/captura de tus notas",
    type=["pdf", "png", "jpg", "jpeg"]
)

if archivo_subido is not None:
    cursos = {}
    institucion_detectada = "Centro de Estudios No Identificado"
    es_imagen = archivo_subido.type in ["image/png", "image/jpeg", "image/jpg"]

    if es_imagen:
        with st.spinner("🔎 Leyendo notas desde la imagen (OCR)..."):
            texto_ocr = extraer_texto_ocr(archivo_subido)
            cursos = procesar_lineas_a_cursos(texto_ocr)

        if "UNIVERSIDAD NACIONAL DE INGENIERÍA" in texto_ocr.upper() or "UNI" in texto_ocr.upper():
            institucion_detectada = "Universidad Nacional de Ingeniería (UNI)"

        with st.expander("📝 Texto detectado por OCR (revisa si algo no se leyó bien)", expanded=False):
            st.text(texto_ocr if texto_ocr.strip() else "No se detectó texto en la imagen.")

        if not cursos:
            st.warning(
                "⚠️ No se pudo identificar ningún curso en la imagen. Asegúrate de que la foto esté nítida, "
                "bien iluminada y que cada curso siga el formato 'CODIGO-NOMBRE' seguido de sus evaluaciones."
            )
    else:
        curso_actual = None
        with pdfplumber.open(archivo_subido) as pdf:
            for pagina in pdf.pages:
                texto_completo = pagina.extract_text() or ""

                # Identificación institucional inteligente mediante texto analizado
                if "UNIVERSIDAD NACIONAL DE INGENIERÍA" in texto_completo.upper() or "UNI" in texto_completo.upper():
                    institucion_detectada = "Universidad Nacional de Ingeniería (UNI)"

                tablas = pagina.extract_tables()
                filas_totales = []
                for tabla in tablas:
                    filas_totales.extend(tabla)

                if filas_totales:
                    for fila in filas_totales:
                        if not fila or len(fila) < 2: continue
                        celda_0 = str(fila[0] or "").strip()
                        celda_1 = str(fila[1] or "").strip()
                        if not celda_0: continue

                        if "-" in celda_0 and any(char.isdigit() for char in celda_0[:6]):
                            partes = celda_0.split("-")
                            codigo_actual = partes[0].strip()
                            curso_actual = _crear_curso(cursos, codigo_actual, partes[1].strip())
                            continue

                        if not curso_actual: continue
                        _procesar_fila_evaluacion(cursos, curso_actual, celda_0, celda_1)
                else:
                    # Respaldo: esta página no tuvo tabla detectable (típico cuando una
                    # tabla de un curso continúa de la cara anterior sin bordes propios).
                    # Analizamos el texto plano línea por línea con la misma lógica del OCR.
                    cursos_respaldo = procesar_lineas_a_cursos(texto_completo)
                    if cursos_respaldo:
                        _combinar_curso(cursos, cursos_respaldo)
                    elif curso_actual:
                        # Ni siquiera hay encabezado de curso nuevo en esta página: puede ser
                        # pura continuación de filas sueltas del curso anterior.
                        for linea in [l.strip() for l in texto_completo.split("\n") if l.strip()]:
                            m_eval = _PATRON_EVAL_TEXTO.match(linea)
                            if m_eval:
                                _procesar_fila_evaluacion(cursos, curso_actual, m_eval.group(1).strip(), m_eval.group(2))

    # Mostrar de qué institución provienen los datos analizados
    st.info(f"🏫 **Institución Académica Detectada:** {institucion_detectada}")
    st.success("✅ ¡Análisis de documentos pregrado completado!")

    notas_modificadas = {}

    # Estados posibles para una nota en 0 (aplican a las Prácticas Calificadas)
    OPCIONES_CERO = ["ND (pendiente)", "0 real (eliminable)", "0A (obligatorio)"]

    def _interpretar_estado_cero(valor_nota, estado):
        """Traduce el valor de una PC + su selector de estado a (es_nd, es_0a)."""
        if valor_nota != 0:
            return False, False
        if estado == OPCIONES_CERO[1]:
            return False, False
        if estado == OPCIONES_CERO[2]:
            return False, True
        return True, False

    def _valores_previos(codigo, info):
        """Lee del session_state los valores ya elegidos por el usuario en un run
        anterior (o los originales del documento si aún no existen), para poder
        mostrar el promedio del curso en la etiqueta del bloque plegable."""
        pcs_prev, nd_prev, a0_prev = [], [], []
        for i, v in enumerate(info["pcs"]):
            v_prev = st.session_state.get(f"pc_{codigo}_{i}", v)
            estado_prev = st.session_state.get(f"estado_pc_{codigo}_{i}", OPCIONES_CERO[0])
            nd_i, a0_i = _interpretar_estado_cero(v_prev, estado_prev)
            pcs_prev.append(v_prev)
            nd_prev.append(nd_i)
            a0_prev.append(a0_i)
        labs_prev = [st.session_state.get(f"lab_{codigo}_{i}", v) for i, v in enumerate(info["labs"])]
        ep_prev = st.session_state.get(f"ep_{codigo}", info["ep"])
        ef_prev = st.session_state.get(f"ef_{codigo}", info["ef"])
        sus_prev = st.session_state.get(f"sus_{codigo}", info["sus"])
        ef_nd_prev = st.session_state.get(f"nd_ef_{codigo}", info["ef"] == 0)
        formula_prev = st.session_state.get(f"form_{codigo}", "")
        return pcs_prev, nd_prev, a0_prev, labs_prev, ep_prev, ef_prev, sus_prev, ef_nd_prev, formula_prev

    for codigo, info in list(cursos.items()):

        if not info["pcs"] and not info["labs"] and not info["tiene_ep"] and not info["tiene_ef"]: continue

        if info["pcs"] and len(info["pcs"]) < 4:
            while len(info["pcs"]) < 4: info["pcs"].append(0)

        # --- Etiqueta del bloque plegable con el promedio ya calculado ---
        etiqueta_pf = ""
        try:
            pcs_prev, nd_prev, a0_prev, labs_prev, ep_prev, ef_prev, sus_prev, ef_nd_prev, formula_prev = _valores_previos(codigo, info)
            _, _, _, pf_prev, *_ = calcular_pf_curso(
                codigo, pcs_prev, labs_prev, ep_prev, ef_prev, sus_prev,
                info["tiene_labs"], info["tiene_ep"], info["tiene_ef"], info["tiene_sus"], formula_prev,
                nota_minima=nota_minima_global, n_pcs_eliminar=n_pcs_eliminar_global,
                n_labs_eliminar=n_labs_eliminar_global, pcs_protegidas=pcs_protegidas_global,
                pcs_nd=nd_prev, pcs_0a=a0_prev, ef_nd=ef_nd_prev
            )
            etiqueta_pf = f" — Promedio: {pf_prev:.2f}"
        except Exception:
            etiqueta_pf = ""

        # key fijo (independiente del texto de la etiqueta) para que el bloque
        # NO se cierre solo cuando el promedio mostrado cambia al tocar un checkbox.
        with st.expander(f"📖 {info['nombre']} ({codigo}){etiqueta_pf}", expanded=False, key=f"exp_{codigo}"):
            num_cols = 1 + int(info["tiene_ep"]) + int(info["tiene_ef"]) + int(info["tiene_sus"])
            cols_cab = st.columns(num_cols, gap="small")

            idx_col = 0
            with cols_cab[idx_col]:
                cred = st.number_input("Créditos:", min_value=1, max_value=8, value=sugerir_creditos(codigo), key=f"cred_{codigo}")
            idx_col += 1

            ep_val = 0
            if info["tiene_ep"]:
                with cols_cab[idx_col]:
                    ep_val = st.number_input("Examen Parcial:", min_value=0, max_value=20, value=info["ep"], key=f"ep_{codigo}")
                idx_col += 1

            ef_val = 0
            ef_nd = False
            if info["tiene_ef"]:
                with cols_cab[idx_col]:
                    ef_val = st.number_input("Examen Final:", min_value=0, max_value=20, value=info["ef"], key=f"ef_{codigo}")
                    if ef_val == 0:
                        ef_nd = st.checkbox("ND (no rendido)", value=(info["ef"] == 0), key=f"nd_ef_{codigo}",
                                             help="Si lo desmarcas, el 0 se toma como nota real ya rendida.")
                idx_col += 1

            sus_val = 0
            if info["tiene_sus"]:
                with cols_cab[idx_col]:
                    sus_val = st.number_input("📝 Examen Sustitutorio:", min_value=0, max_value=20, value=info["sus"], key=f"sus_{codigo}")

            formula_input = st.text_input(
                "⚙️ Configuración de Pesos y Observaciones del Curso:",
                value="",
                placeholder="Ej: ep vale por 2, pc4 vale por 2, pc4 se elimina",
                key=f"form_{codigo}"
            )

            nuevas_pcs = []
            pcs_es_nd = []
            pcs_es_0a = []
            if info["pcs"]:
                st.markdown("**Prácticas Calificadas:**")
                cols_pcs = st.columns(len(info["pcs"]), gap="small")
                for idx, nota_pc in enumerate(info["pcs"]):
                    with cols_pcs[idx]:
                        n_pc = st.number_input(f"PC {idx+1}", min_value=0, max_value=20, value=nota_pc, key=f"pc_{codigo}_{idx}")
                        if n_pc == 0:
                            estado = st.selectbox(
                                "¿Qué es este 0?", options=OPCIONES_CERO, index=0,
                                key=f"estado_pc_{codigo}_{idx}",
                                help="ND: aún no rendida. 0 real: nota tomada, puede salir como la peor y eliminarse. "
                                     "0A: nota tomada, cuenta obligatoria y nunca se elimina."
                            )
                        else:
                            estado = OPCIONES_CERO[0]
                        nd_i, a0_i = _interpretar_estado_cero(n_pc, estado)
                        nuevas_pcs.append(n_pc)
                        pcs_es_nd.append(nd_i)
                        pcs_es_0a.append(a0_i)

            nuevos_labs = []
            if info["tiene_labs"] and info["labs"]:
                st.markdown("**Laboratorios / Láminas de Dibujo:**")
                cols_labs = st.columns(len(info["labs"]), gap="small")
                for idx, nota_lab in enumerate(info["labs"]):
                    with cols_labs[idx]:
                        n_lab = st.number_input(f"L/L {idx+1}", min_value=0, max_value=20, value=nota_lab, key=f"lab_{codigo}_{idx}")
                        nuevos_labs.append(n_lab)

            prom_pc, prom_lab, pp, pf, ef_nec, sus_nec, hay_pcs_faltantes, formula_valida, mensaje_validacion, tip_estrategia = calcular_pf_curso(
                codigo, nuevas_pcs, nuevos_labs, ep_val, ef_val, sus_val,
                info["tiene_labs"], info["tiene_ep"], info["tiene_ef"], info["tiene_sus"], formula_input,
                nota_minima=nota_minima_global, n_pcs_eliminar=n_pcs_eliminar_global,
                n_labs_eliminar=n_labs_eliminar_global, pcs_protegidas=pcs_protegidas_global,
                pcs_nd=pcs_es_nd, pcs_0a=pcs_es_0a, ef_nd=ef_nd
            )

            if formula_input.strip():
                if formula_valida: st.success("✅ Configuración de pesos aplicada con éxito.")
                else: st.error(mensaje_validacion)

            notas_modificadas[codigo] = {"pf": pf, "creditos": cred}

            st.markdown("---")
            c1, c2, c3 = st.columns(3, gap="small")
            with c1:
                st.metric(label="Promedio Continuo (PP)", value=f"{pp:.2f}")
                if tip_estrategia:
                    st.warning(tip_estrategia)
            with c2:
                color_pf = "green" if pf >= nota_minima_global else "red"
                st.markdown(f"**Promedio Final Estimado:** <h3 style='color:{color_pf}; margin-top:0px;'>{pf:.2f}</h3>", unsafe_allow_html=True)
                if info["tiene_sus"] and pf < nota_minima_global and 0 < sus_nec <= 20:
                    st.info(f"🔄 Requieres sacar un **{sus_nec:.1f}** en el Sustitutorio para aprobar el curso.")
            with c3:
                if info["tiene_ef"] and ef_nd and 0 < ef_nec <= 20:
                    st.info(f"🎯 Requiere **{ef_nec:.1f}** en el Final para aprobar ({nota_minima_global:.1f}).")
                elif pf >= nota_minima_global:
                    st.success("✅ Asignatura Aprobada")
                else:
                    st.error("❌ Asignatura Desaprobada")

    # --- PROMEDIO PONDERADO TOTAL ---
    st.markdown("---")
    suma_ponderada = 0
    total_creditos = 0
    for c, d in notas_modificadas.items():
        suma_ponderada += d["pf"] * d["creditos"]
        total_creditos += d["creditos"]

    ponderado_ciclo = suma_ponderada / total_creditos if total_creditos > 0 else 0.0

    st.header("📊 Resumen del Promedio Ponderado del Ciclo")
    if ponderado_ciclo >= 14:
        st.metric(label="PROMEDIO PONDERADO TOTAL", value=f"{ponderado_ciclo:.2f}", delta="Rendimiento Sobresaliente")
        st.balloons()
    elif ponderado_ciclo >= nota_minima_global:
        st.metric(label="PROMEDIO PONDERADO TOTAL", value=f"{ponderado_ciclo:.2f}", delta="Ciclo Invicto")
    else:
        st.metric(label="PROMEDIO PONDERADO TOTAL", value=f"{ponderado_ciclo:.2f}", delta="- Alerta: Bajo la nota mínima", delta_color="inverse")
