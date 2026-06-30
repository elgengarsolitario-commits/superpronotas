import streamlit as st
import pdfplumber
import re
import io
import requests

# Configuración de la página web
st.set_page_config(page_title="SUPERPRO de Notas", page_icon="🎯", layout="wide")

# --- BARRA LATERAL: CONFIGURACIÓN GLOBAL ---
with st.sidebar:
    st.header("⚙️ Configuración Global")
    st.caption("👆 Revisa esto antes de cargar tus notas: define cómo se calculan tus promedios.")

    nota_minima_global = st.number_input(
        "Nota mínima de aprobación", min_value=0.0, max_value=20.0,
        value=10.50, step=0.5, format="%.2f"
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

# --- ALMACÉN PERSISTENTE DE CURSOS (compartido entre archivo y modo manual) ---
if "cursos" not in st.session_state:
    st.session_state.cursos = {}

def calcular_pf_curso(codigo, pcs, labs, ep, ef, sus, tiene_labs, tiene_ep, tiene_ef, tiene_sus, formula_texto,
                       nota_minima=9.5, n_pcs_eliminar=1, n_labs_eliminar=2, pcs_protegidas=None):
    """
    Calcula los promedios oficiales aplicando pesos dinámicos extras basados en siglas:
    PC (Práctica), LB (Laboratorio), EP (Parcial), EF (Final).
    """
    if pcs_protegidas is None:
        pcs_protegidas = []
    # Convertir nombres tipo "PC1" a índices (0-based) protegidos contra eliminación
    indices_protegidos = set()
    for p in pcs_protegidas:
        m = re.match(r'^PC\s*(\d+)$', str(p).strip().upper())
        if m:
            indices_protegidos.add(int(m.group(1)) - 1)
    # Inicializar pesos base
    pesos_pcs = [1] * len(pcs)
    pesos_labs = [1] * len(labs)
    peso_ep = 1
    peso_ef = 2  # Peso 2 por defecto
    
    es_valido = True
    msg_error = ""

    if formula_texto.strip():
        partes = [p.strip() for p in formula_texto.split(',') if p.strip()]
        reglas_encontradas = 0
        for parte in partes:
            coincidencia = re.match(r'^(pc|lb|ep|ef)\s*(\d*)\s*vale\s*por\s*(\d+)$', parte.lower())
            if coincidencia:
                reglas_encontradas += 1
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
            else:
                es_valido = False
                if parte.lower() in ['pc', 'lb', 'ep', 'ef'] or re.match(r'^(pc|lb)\d+$', parte.lower()):
                    msg_error = f"⚠️ Sintaxis incompleta en '{parte}'. Recuerda usar el formato completo, ej: '{parte} vale por 2'."
                else:
                    msg_error = f"❌ Parámetro inválido: '{parte}'."
                break

    # Identificar cuáles PCs faltan (están en 0)
    indices_pcs_faltantes = [i for i, nota in enumerate(pcs) if nota == 0]
    hay_pcs_faltantes = len(indices_pcs_faltantes) > 0

    # 1. Lógica de Prácticas Calificadas (Eliminación de las N peores, respetando protegidas)
    indices_candidatos = [i for i in range(len(pcs)) if i not in indices_protegidos]
    n_eliminar_real = min(n_pcs_eliminar, max(0, len(indices_candidatos) - 1)) if len(pcs) > 1 else 0

    if n_eliminar_real > 0 and not hay_pcs_faltantes:
        indices_a_eliminar_pc = sorted(indices_candidatos, key=lambda i: pcs[i])[:n_eliminar_real]
        suma_ponderada_pc = sum(pcs[i] * pesos_pcs[i] for i in range(len(pcs)) if i not in indices_a_eliminar_pc)
        suma_pesos_pc = sum(pesos_pcs[i] for i in range(len(pesos_pcs)) if i not in indices_a_eliminar_pc)
        prom_pc = suma_ponderada_pc / suma_pesos_pc if suma_pesos_pc > 0 else 0
    else:
        suma_ponderada_pc = sum(nota * peso for nota, peso in zip(pcs, pesos_pcs))
        suma_pesos_pc = sum(pesos_pcs)
        prom_pc = suma_ponderada_pc / suma_pesos_pc if suma_pesos_pc > 0 else 0

    # 2. Lógica de laboratorios/láminas (Eliminación de las N peores)
    prom_lab = 0
    if tiene_labs and labs:
        hay_ceros_lab = any(nota == 0 for nota in labs)
        n_labs_eliminar_real = min(n_labs_eliminar, max(0, len(labs) - 1))
        if not hay_ceros_lab and n_labs_eliminar_real > 0:
            labs_con_indices = sorted(enumerate(labs), key=lambda x: x[1])
            indices_a_eliminar = [idx for idx, _ in labs_con_indices[:n_labs_eliminar_real]]
            suma_ponderada_lab = sum(labs[i] * pesos_labs[i] for i in range(len(labs)) if i not in indices_a_eliminar)
            suma_pesos_lab = sum(pesos_labs[i] for i in range(len(labs)) if i not in indices_a_eliminar)
            prom_lab = suma_ponderada_lab / suma_pesos_lab if suma_pesos_lab > 0 else 0
        else:
            suma_ponderada_lab = sum(nota * peso for nota, peso in zip(labs, pesos_labs))
            suma_pesos_lab = sum(pesos_labs)
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
        
        # Caso 1: Falta rendir alguna PC y el Examen Final está en 0
        if hay_pcs_faltantes and tiene_ef and ef == 0:
            nota_simulada_pc = 14
            pcs_simuladas = [nota if nota > 0 else nota_simulada_pc for nota in pcs]
            
            if len(pcs_simuladas) >= 4:
                hay_ceros_sim = any(pcs_simuladas[i] == 0 for i in [0, 1, 2])
                if not hay_ceros_sim:
                    peor_idx = min([0,1,2], key=lambda i: pcs_simuladas[i])
                    s_pc = sum(pcs_simuladas[i] * pesos_pcs[i] for i in range(len(pcs_simuladas)) if i != peor_idx)
                    w_pc = sum(pesos_pcs[i] for i in range(len(pesos_pcs)) if i != peor_idx)
                    p_pc_sim = s_pc / w_pc
                else:
                    p_pc_sim = sum(n * w for n, w in zip(pcs_simuladas, pesos_pcs)) / sum(pesos_pcs)
            else:
                p_pc_sim = sum(n * w for n, w in zip(pcs_simuladas, pesos_pcs)) / sum(pesos_pcs)
                
            pp_simulado = (p_pc_sim + prom_lab) / 2 if tiene_labs else p_pc_sim
            ef_comb_necesario = (puntos_objetivo_totales - (ep_final * peso_ep) - pp_simulado) / peso_ef
            
            nombre_pcs_faltantes = ", ".join([f"PC {i+1}" for i in indices_pcs_faltantes])
            if 0 < ef_comb_necesario <= 20:
                tip_estrategia = f"💡 Plan de Remonte: Si sacas un **{nota_simulada_pc}** en la {nombre_pcs_faltantes}, solo necesitarás un **{ef_comb_necesario:.1f}** en el Examen Final."
            else:
                ef_comb_necesario = (puntos_objetivo_totales - (ep_final * peso_ep) - ((20 + prom_lab)/2 if tiene_labs else 20)) / peso_ef
                tip_estrategia = f"⚠️ ¡Falta presión!: Necesitas asegurar notas altas. Si sacas **20** en la {nombre_pcs_faltantes}, requieres mínimo un **{max(0.0, ef_comb_necesario):.1f}** en el Final."

        # Caso 2: Falta rendir alguna PC pero el EF ya se rindió
        elif hay_pcs_faltantes:
            pp_necesario = puntos_objetivo_totales - (ep_final * peso_ep) - (ef_final * peso_ef)
            prom_pc_objetivo = (pp_necesario * 2) - prom_lab if tiene_labs else pp_necesario
            
            suma_actual_pcs = sum(nota * peso for nota, peso in zip(pcs, pesos_pcs))
            diferencia_necesaria = (prom_pc_objetivo * sum(pesos_pcs)) - suma_actual_pcs
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


class ArchivoDesdeURL(io.BytesIO):
    """
    Envuelve el contenido binario descargado desde un link para que se comporte
    igual que un archivo subido con st.file_uploader (necesita el atributo .type).
    """
    def __init__(self, data, tipo_mime):
        super().__init__(data)
        self.type = tipo_mime


def descargar_archivo_desde_url(url):
    """
    Descarga un PDF desde un link directo y devuelve un ArchivoDesdeURL,
    o None junto con un mensaje de error si algo falla.
    """
    try:
        respuesta = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        respuesta.raise_for_status()
    except requests.exceptions.RequestException as e:
        return None, f"❌ No se pudo descargar el archivo del enlace: {e}"

    contenido = respuesta.content
    content_type = respuesta.headers.get("Content-Type", "").split(";")[0].strip().lower()

    if content_type != "application/pdf":
        url_lower = url.strip().lower()
        if url_lower.endswith(".pdf") or contenido[:4] == b"%PDF":
            content_type = "application/pdf"

    if content_type != "application/pdf":
        return None, "❌ El enlace no parece apuntar directamente a un PDF. Verifica que sea un link de descarga directa."

    return ArchivoDesdeURL(contenido, content_type), None

# --- INTERFAZ GRÁFICA ---
st.title("🎯 SUPERPRO de Notas")

st.warning(
    "📱 **¿Estás en el celular?** Toca la flecha **«** o el ícono **☰** en la esquina superior "
    "izquierda para abrir el panel de **⚙️ Configuración de Notas** (nota mínima, PCs/Laboratorios "
    "a eliminar, etc.). Es importante revisarlo antes de cargar tus notas."
)

st.markdown("""
Esta aplicación ha sido diseñada como una herramienta avanzada de apoyo para estudiantes universitarios de pregrado. 
Su propósito es facilitar el control, simulación y cálculo automatizado de promedios ponderados por ciclo de forma precisa, 
permitiendo proyectar las calificaciones necesarias en evaluaciones pendientes (prácticas, parciales, finales y sustitutorios) 
para lograr la meta académica de aprobación.
""")

# --- GUÍA VISUAL DE EJEMPLOS PARA EL REGISTRO OPTIMO ---
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
    *Nota: Las evaluaciones que aún no rindas pueden figurar con `0` o `00` y el sistema las identificará automáticamente como pendientes para sugerirte la estrategia de remonte.*
    """)

st.markdown("---")

# --- CREACIÓN MANUAL DE CURSOS (SIN ARCHIVO) ---
with st.expander("➕ Agregar curso manualmente (sin subir archivo)", expanded=False):
    st.markdown("Crea un curso desde cero. Luego, dentro de su bloque podrás pulsar **➕ Agregar PC** o **➕ Agregar Laboratorio** todas las veces que necesites.")

    col_a, col_b = st.columns(2)
    with col_a:
        nuevo_codigo = st.text_input("Código del curso", key="m_codigo", placeholder="Ej: MA123")
    with col_b:
        nuevo_nombre = st.text_input("Nombre del curso", key="m_nombre", placeholder="Ej: CÁLCULO I")

    col_c, col_d, col_e, col_f = st.columns(4)
    with col_c:
        m_tiene_ep = st.checkbox("Tiene Parcial", value=True, key="m_tiene_ep")
    with col_d:
        m_tiene_ef = st.checkbox("Tiene Final", value=True, key="m_tiene_ef")
    with col_e:
        m_tiene_sus = st.checkbox("Tiene Sustitutorio", value=True, key="m_tiene_sus")
    with col_f:
        m_tiene_labs = st.checkbox("Tiene Laboratorios", value=False, key="m_tiene_labs")

    col_g, col_h, col_i = st.columns(3)
    with col_g:
        m_n_pcs = st.number_input("N° de Prácticas (PC) iniciales", min_value=1, max_value=10, value=4, key="m_n_pcs")
    with col_h:
        m_n_labs = st.number_input("N° de Laboratorios iniciales", min_value=0, max_value=10, value=2, key="m_n_labs", disabled=not m_tiene_labs)
    with col_i:
        m_creditos = st.number_input("Créditos del curso", min_value=1, max_value=10, value=3, key="m_creditos")

    if st.button("✅ Crear curso"):
        codigo_norm = nuevo_codigo.strip().upper()
        if not codigo_norm or not nuevo_nombre.strip():
            st.warning("⚠️ Completa el código y el nombre del curso antes de crear.")
        elif codigo_norm in st.session_state.cursos:
            st.warning("⚠️ Ya existe un curso (cargado o manual) con ese código.")
        else:
            st.session_state.cursos[codigo_norm] = {
                "nombre": nuevo_nombre.strip().upper(),
                "pcs": [0] * int(m_n_pcs),
                "labs": [0] * int(m_n_labs) if m_tiene_labs else [],
                "ep": 0, "ef": 0, "sus": 0,
                "tiene_labs": m_tiene_labs, "tiene_ep": m_tiene_ep,
                "tiene_ef": m_tiene_ef, "tiene_sus": m_tiene_sus,
                "creditos": int(m_creditos)
            }
            st.success(f"✅ Curso {codigo_norm} creado. Bájalo para registrar sus notas.")
            st.rerun()

st.markdown("---")

archivo_subido = st.file_uploader(
    "📂 Arrastra aquí tu archivo 'doc.pdf'",
    type=["pdf"]
)

st.markdown("**...o si prefieres, analiza un documento PDF directamente desde un link:**")
col_link1, col_link2 = st.columns([4, 1])
with col_link1:
    url_documento = st.text_input(
        "🔗 Pega el link directo a tu PDF de notas",
        placeholder="https://ejemplo.com/mis-notas.pdf",
        key="url_documento",
        label_visibility="collapsed"
    )
with col_link2:
    analizar_link = st.button("📥 Analizar enlace", use_container_width=True)

if "archivo_desde_link" not in st.session_state:
    st.session_state.archivo_desde_link = None

if analizar_link:
    if not url_documento.strip():
        st.warning("⚠️ Primero pega un link válido.")
    else:
        with st.spinner("📡 Descargando documento desde el enlace..."):
            archivo_descargado, error_descarga = descargar_archivo_desde_url(url_documento.strip())
        if error_descarga:
            st.error(error_descarga)
            st.session_state.archivo_desde_link = None
        else:
            st.session_state.archivo_desde_link = archivo_descargado
            st.success("✅ Documento descargado correctamente desde el enlace.")

# El archivo subido manualmente tiene prioridad sobre el del link si ambos están presentes
if archivo_subido is None and st.session_state.archivo_desde_link is not None:
    archivo_subido = st.session_state.archivo_desde_link
    archivo_subido.seek(0)

if archivo_subido is not None:
    cursos_archivo = {}
    institucion_detectada = "Centro de Estudios No Identificado"
    curso_actual = None
    with pdfplumber.open(archivo_subido) as pdf:
        for pagina in pdf.pages:
            texto_completo = pagina.extract_text() or ""

            # Identificación institucional inteligente mediante texto analizado
            if "UNIVERSIDAD NACIONAL DE INGENIERÍA" in texto_completo.upper() or "UNI" in texto_completo.upper():
                institucion_detectada = "Universidad Nacional de Ingeniería (UNI)"

            tablas = pagina.extract_tables()
            for tabla in tablas:
                for fila in tabla:
                    if not fila or len(fila) < 2: continue
                    celda_0, celda_1 = str(fila[0]).strip(), str(fila[1]).strip()

                    if "-" in celda_0 and any(char.isdigit() for char in celda_0[:6]):
                        partes = celda_0.split("-")
                        codigo_actual = partes[0].strip()
                        cursos_archivo[codigo_actual] = {
                            "nombre": partes[1].strip(),
                            "pcs": [], "labs": [], "ep": 0, "ef": 0, "sus": 0,
                            "tiene_labs": False, "tiene_ep": False, "tiene_ef": False, "tiene_sus": False
                        }
                        curso_actual = codigo_actual
                        continue
                
                    if not curso_actual: continue
                
                    eval_nom = celda_0.upper()
                    if "LETRA" in eval_nom or "FECHA" in eval_nom or "MODALIDAD" in eval_nom: continue
                
                    if "LABORATORIO" in eval_nom or "LÁMINA" in eval_nom or curso_actual == "AA237F":
                        cursos_archivo[curso_actual]["tiene_labs"] = True
                    if "PARCIAL" in eval_nom: cursos_archivo[curso_actual]["tiene_ep"] = True
                    if "FINAL" in eval_nom: cursos_archivo[curso_actual]["tiene_ef"] = True
                    if "SUSTITUTORIO" in eval_nom or "SUST." in eval_nom: cursos_archivo[curso_actual]["tiene_sus"] = True
                    if "FINAL" in eval_nom or "PARCIAL" in eval_nom: cursos_archivo[curso_actual]["tiene_sus"] = True
                
                    nota = int(celda_1) if celda_1.isdigit() else 0
                    if "PRACTICA" in eval_nom: cursos_archivo[curso_actual]["pcs"].append(nota)
                    elif "LABORATORIO" in eval_nom or "LÁMINA" in eval_nom: cursos_archivo[curso_actual]["labs"].append(nota)
                    elif "PARCIAL" in eval_nom: cursos_archivo[curso_actual]["ep"] = nota
                    elif "FINAL" in eval_nom: cursos_archivo[curso_actual]["ef"] = nota
                    elif "SUSTITUTORIO" in eval_nom: cursos_archivo[curso_actual]["sus"] = nota

    # Mostrar de qué institución provienen los datos analizados
    st.info(f"🏫 **Institución Académica Detectada:** {institucion_detectada}")
    st.success("✅ ¡Análisis de documentos pregrado completado!")

    # Fusionar con el almacén persistente: si el curso ya existe (porque el usuario
    # ya lo editó manualmente, agregó bloques extra, etc.) no se sobreescribe.
    for codigo_arch, info_arch in cursos_archivo.items():
        if codigo_arch not in st.session_state.cursos:
            st.session_state.cursos[codigo_arch] = info_arch

notas_modificadas = {}

if not st.session_state.cursos:
    st.info("📭 Sube un archivo o agrega un curso manualmente arriba para comenzar.")

for codigo in list(st.session_state.cursos.keys()):
    info = st.session_state.cursos[codigo]

    if not info["pcs"] and not info["labs"] and not info["tiene_ep"] and not info["tiene_ef"]: continue

    if info["pcs"] and len(info["pcs"]) < 4:
        while len(info["pcs"]) < 4: info["pcs"].append(0)

    with st.expander(f"📖 {info['nombre']} ({codigo})", expanded=True):
        # --- BOTONES PARA AUMENTAR/QUITAR BLOQUES Y ELIMINAR EL CURSO ---
        col_btn1, col_btn2, col_btn3, col_btn4, col_btn5 = st.columns(5)
        with col_btn1:
            if st.button("➕ Agregar PC", key=f"add_pc_{codigo}"):
                st.session_state.cursos[codigo]["pcs"].append(0)
                st.rerun()
        with col_btn2:
            if len(info["pcs"]) > 1 and st.button("➖ Quitar PC", key=f"rm_pc_{codigo}"):
                st.session_state.cursos[codigo]["pcs"].pop()
                st.rerun()
        with col_btn3:
            if not info["tiene_labs"]:
                if st.button("➕ Activar Laboratorios", key=f"act_lab_{codigo}"):
                    st.session_state.cursos[codigo]["tiene_labs"] = True
                    if not st.session_state.cursos[codigo]["labs"]:
                        st.session_state.cursos[codigo]["labs"] = [0, 0]
                    st.rerun()
            else:
                if st.button("➕ Agregar Laboratorio", key=f"add_lab_{codigo}"):
                    st.session_state.cursos[codigo]["labs"].append(0)
                    st.rerun()
        with col_btn4:
            if info["tiene_labs"] and len(info["labs"]) > 1 and st.button("➖ Quitar Laboratorio", key=f"rm_lab_{codigo}"):
                st.session_state.cursos[codigo]["labs"].pop()
                st.rerun()
        with col_btn5:
            if st.button("🗑️ Eliminar curso", key=f"del_curso_{codigo}"):
                del st.session_state.cursos[codigo]
                st.rerun()

        num_cols = 1 + int(info["tiene_ep"]) + int(info["tiene_ef"]) + int(info["tiene_sus"])
        cols_cab = st.columns(num_cols)

        idx_col = 0
        with cols_cab[idx_col]:
            cred = st.number_input("Créditos:", min_value=1, max_value=10, value=info.get("creditos", sugerir_creditos(codigo)), key=f"cred_{codigo}")
        idx_col += 1

        ep_val = 0
        if info["tiene_ep"]:
            with cols_cab[idx_col]:
                ep_val = st.number_input("Examen Parcial:", min_value=0, max_value=20, value=info["ep"], key=f"ep_{codigo}")
            idx_col += 1

        ef_val = 0
        if info["tiene_ef"]:
            with cols_cab[idx_col]:
                ef_val = st.number_input("Examen Final:", min_value=0, max_value=20, value=info["ef"], key=f"ef_{codigo}")
            idx_col += 1

        sus_val = 0
        if info["tiene_sus"]:
            with cols_cab[idx_col]:
                sus_val = st.number_input("📝 Examen Sustitutorio:", min_value=0, max_value=20, value=info["sus"], key=f"sus_{codigo}")

        formula_input = st.text_input(
            "⚙️ Configuración de Pesos y Observaciones del Curso:",
            value="",
            placeholder="Ejemplo: ep vale por 2, pc4 vale por 2, ef vale por 3",
            key=f"form_{codigo}"
        )

        nuevas_pcs = []
        if info["pcs"]:
            st.markdown("**Prácticas Calificadas:**")
            cols_pcs = st.columns(len(info["pcs"]))
            for idx, nota_pc in enumerate(info["pcs"]):
                with cols_pcs[idx]:
                    n_pc = st.number_input(f"PC {idx+1}", min_value=0, max_value=20, value=nota_pc, key=f"pc_{codigo}_{idx}")
                    nuevas_pcs.append(n_pc)

        nuevos_labs = []
        if info["tiene_labs"] and info["labs"]:
            st.markdown("**Laboratorios / Láminas de Dibujo:**")
            cols_labs = st.columns(len(info["labs"]))
            for idx, nota_lab in enumerate(info["labs"]):
                with cols_labs[idx]:
                    n_lab = st.number_input(f"L/L {idx+1}", min_value=0, max_value=20, value=nota_lab, key=f"lab_{codigo}_{idx}")
                    nuevos_labs.append(n_lab)

        prom_pc, prom_lab, pp, pf, ef_nec, sus_nec, hay_pcs_faltantes, formula_valida, mensaje_validacion, tip_estrategia = calcular_pf_curso(
            codigo, nuevas_pcs, nuevos_labs, ep_val, ef_val, sus_val,
            info["tiene_labs"], info["tiene_ep"], info["tiene_ef"], info["tiene_sus"], formula_input,
            nota_minima=nota_minima_global, n_pcs_eliminar=n_pcs_eliminar_global,
            n_labs_eliminar=n_labs_eliminar_global, pcs_protegidas=pcs_protegidas_global
        )

        if formula_input.strip():
            if formula_valida: st.success("✅ Configuración de pesos aplicada con éxito.")
            else: st.error(mensaje_validacion)

        notas_modificadas[codigo] = {"pf": pf, "creditos": cred}

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
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
            if info["tiene_ef"] and ef_val == 0 and 0 < ef_nec <= 20:
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
    st.metric(label="PROMEDIO PONDERADO TOTAL", value=f"{ponderado_ciclo:.2f}", delta="- Alerta: Bajo 10", delta_color="inverse")
