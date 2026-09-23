import streamlit as st
import json
import requests
import google.auth
from google.auth.transport.requests import Request

# ---------------------------------------------------------------------------
# CONFIGURACIÓN VISUAL DE LA PÁGINA
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Asistente Logístico Tottus",
    page_icon="🟢",
    layout="centered"
)

st.title("🟢 Asistente Logístico Tottus")
st.caption("Consulta salidas, mercadería, TIMs y despachos en lenguaje natural.")

# ---------------------------------------------------------------------------
# PARÁMETROS DEL PROYECTO
# ---------------------------------------------------------------------------
PROJECT_ID = "tot-corp-plo-sbx"
LOCATION = "global"
DATASET_ID = "tot_bi_logistica_pe"
TABLE_ID = "FT_LOG_SALIDAS"

# ---------------------------------------------------------------------------
# AUTENTICACIÓN
# ---------------------------------------------------------------------------
@st.cache_resource
def get_credentials():
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return credentials

def obtener_token():
    creds = get_credentials()
    if not creds.valid:
        creds.refresh(Request())
    return creds.token

# ---------------------------------------------------------------------------
# CONSULTA A GEMINI DATA ANALYTICS
# ---------------------------------------------------------------------------
def consultar_gemini_logistica(pregunta: str) -> dict:
    token = obtener_token()
    url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/{LOCATION}:chat"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messages": [
            {
                "userMessage": {
                    "text": pregunta
                }
            }
        ],
        "inlineContext": {
            "systemInstruction": (
                "Eres el asistente oficial de datos logísticos de Tottus Perú. "
                "Responde con precisión a las consultas de salidas, códigos TIM y despachos. "
                "Sé claro, conciso y responde siempre en español."
            ),
            "datasourceReferences": {
                "bq": {
                    "tableReferences": [
                        {
                            "projectId": PROJECT_ID,
                            "datasetId": DATASET_ID,
                            "tableId": TABLE_ID
                        }
                    ]
                }
            }
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        return {"exito": False, "error": f"Error HTTP {response.status_code}", "detalle": response.text}
        
    try:
        return {"exito": True, "data": response.json()}
    except Exception as e:
        return {"exito": False, "error": "Error al decodificar JSON", "detalle": str(e)}

def parsear_respuesta(resultado: dict):
    if not resultado.get("exito"):
        return f"❌ {resultado.get('error')}: {resultado.get('detalle')}", None
        
    data = resultado.get("data", [])
    bloques = data if isinstance(data, list) else [data]
    
    sql_generado = None
    respuestas_texto = []
    
    for bloque in bloques:
        sys_msg = bloque.get("systemMessage", {})
        if "query" in sys_msg:
            sql_generado = sys_msg.get("query")
            
        text_obj = sys_msg.get("text")
        if isinstance(text_obj, str):
            respuestas_texto.append(text_obj)
        elif isinstance(text_obj, dict):
            parts = text_obj.get("parts", [])
            for p in parts:
                if isinstance(p, str):
                    respuestas_texto.append(p)
                elif isinstance(p, dict) and "text" in p:
                    respuestas_texto.append(p["text"])
                    
    texto_final = "\n\n".join(respuestas_texto) if respuestas_texto else "No se obtuvo respuesta en texto."
    return texto_final, sql_generado

# ---------------------------------------------------------------------------
# HISTORIAL DE CHAT EN PANTALLA
# ---------------------------------------------------------------------------
if "mensajes" not in st.session_state:
    st.session_state.mensajes = [
        {"role": "assistant", "content": "¡Hola! Soy tu asistente de logística. Pregúntame sobre cualquier TIM, despacho o salida de mercadería."}
    ]

# Dibujar mensajes anteriores
for msg in st.session_state.mensajes:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sql" in msg and msg["sql"]:
            with st.expander("🔍 Ver SQL ejecutado internamente"):
                st.code(msg["sql"], language="sql")

# Caja de texto para escribir la pregunta
if prompt := st.chat_input("Ej: ¿Qué productos hay en la TIM 655423723?"):
    st.session_state.mensajes.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    with st.chat_message("assistant"):
        with st.spinner("Consultando BigQuery a través de Gemini..."):
            res = consultar_gemini_logistica(prompt)
            texto, sql = parsear_respuesta(res)
            st.markdown(texto)
            if sql:
                with st.expander("🔍 Ver SQL ejecutado internamente"):
                    st.code(sql, language="sql")
                    
    st.session_state.mensajes.append({"role": "assistant", "content": texto, "sql": sql})