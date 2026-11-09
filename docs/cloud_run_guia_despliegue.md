# ☁️ Guía de Despliegue en Google Cloud Run — Asistente de Transporte Tottus Perú 🇵🇪

Esta guía detalla la arquitectura de producción y el procedimiento paso a paso para desplegar el backend y frontend del Asistente de Transporte y Despachos en **Google Cloud Run** bajo los estándares de **Google GenAI / ADK** y **GenAI Toolbox MCP**.

---

## 🏛️ Arquitectura del Sistema en Google Cloud (GCP)

Al desplegar en Cloud Run, se elimina la dependencia de equipos locales encendidos o túneles temporales:

```mermaid
flowchart TD
    subgraph Usuarios ["👥 Usuarios Corporativos"]
        Navegador["Navegador Web / Celular\nhttps://asistente-transporte-xxxx.a.run.app/app/"]
        Teams["Microsoft Teams / Copilot Studio\n(Próxima Fase)"]
    end

    subgraph GCP_CloudRun ["☁️ Google Cloud Run (Servicios Administrados)"]
        NginxFastAPI["FastAPI + Uvicorn (:8080)\n• Servidor API Gateway\n• Servidor Web Estático (/app/)"]
        AuthRBAC["🛡️ Control Dual de Acceso\n• Dominio @tottus.com.pe\n• Whitelist RBAC"]
        AgentCore["🧠 Agente Logístico (LogisticaAgent)\nOrquestador Google GenAI"]
        CacheMem["⚡ Caché en Memoria\n(SimpleTTLCache LRU+TTL)"]
        ToolboxRun["🔧 Servicio Toolbox MCP\n(Contenedor genai-toolbox + tools.yaml)"]
    end

    subgraph GCP_Servicios ["🌐 Servicios Nativos de Google Cloud"]
        VertexAI["Vertex AI Gemini 3.5 Flash-Lite\n(Function Calling Determinista)"]
        BigQuery[("Google BigQuery\nDataset: tot_bi_logistica_pe\nTabla: FT_LOG_SALIDAS")]
        IAM["IAM Service Account\n(Credenciales ADC Nativas)"]
    end

    Usuarios -->|HTTPS Seguro (Port 443)| NginxFastAPI
    NginxFastAPI --> AuthRBAC
    AuthRBAC --> AgentCore
    AgentCore <--> CacheMem
    AgentCore <-->|Razonamiento / Prompts| VertexAI
    AgentCore -->|JSON-RPC 2.0 (TOOLBOX_URL)| ToolboxRun
    ToolboxRun -->|SQL Parametrizado| BigQuery
    IAM -.->|Autorización Automática| GCP_CloudRun
```

---

## 📋 Mapeo con el Modelo de Datos (`PE - Modelo TMS Detalle`)

El asistente consulta en tiempo real las dimensiones de la tabla `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS` en BigQuery:

| Sección Looker | Dimensiones / Métricas Clave | Herramienta MCP Asociada | Propósito en el Asistente |
| :--- | :--- | :--- | :--- |
| **02. Transferencias** | `TIM`, `Fecha_Enviado`, `Hora_de_Carga` | `resumen_carga_transporte` | Rastreo de envíos entre CD y tiendas. |
| **03. Guías** | `Trf_DO`, `Shipment` | `buscar_por_shipment_o_do` | Rastreo por número de orden de entrega o despacho. |
| **04. Sellos / Detalle** | `Placa`, `sku`, `Descripcion`, `Tipo_DO` | `consultar_despachos_logistica` | Trazabilidad física del vehículo y mercadería. |
| **05. Perecibles** | `Fecha_Vencimiento`, `dias_para_vencer` | `alertas_vencimiento_transito` | Alertas preventivas de vencimiento en tránsito. |
| **06. Lpn o Pallet** | `Pallet`, `sku`, `Unidades`, `Cajas`, `Peso_Total`, `Vol_Enviado` | `consultar_despachos_logistica`, `resumen_carga_transporte` | Detalle fino a nivel de bulto, producto, peso (kg) y volumen ($m^3$). |
| **07. CD / Pendientes** | `Hora_de_Carga`, `Inventario_Whse` | `consultar_cargas_pendientes_despacho` | Detección de cargas listas en CD pendientes de salida. |

---

## 🚀 Pasos para el Despliegue en Cloud Run

### 1. Autenticación en Google Cloud SDK
Desde tu terminal corporativa con permisos en el proyecto de GCP de Tottus:
```powershell
gcloud auth login
gcloud config set project tot-corp-plo-sbx
```

### 2. Habilitar las APIs de Google Cloud Requeridas
```powershell
gcloud services enable run.googleapis.com `
                       artifactregistry.googleapis.com `
                       cloudbuild.googleapis.com `
                       aiplatform.googleapis.com `
                       bigquery.googleapis.com
```

### 3. Preparación del Contexto de Compilación
1. **Frontend unificado (Opcional):** El `Dockerfile` copia la carpeta `./frontend` para servir la interfaz web en `/app/`. Antes de desplegar en modo unificado, copia el contenido de `agente-transporte-front` dentro de `agent-test/frontend/` (o comenta `COPY frontend/ ./frontend/` en el `Dockerfile` si deseas desplegar el backend en modo *API Gateway Headless*).
2. **Servidor Toolbox MCP (`TOOLBOX_URL`):** Asegúrate de contar con el contenedor de `genai-toolbox` desplegado en Cloud Run (o como sidecar Linux) con el archivo `toolbox/tools.yaml` e inyecta su URL en la variable `TOOLBOX_URL`.

### 4. Despliegue desde Código Fuente (Cloud Build)
Ubícate en la raíz del proyecto `agent-test` y ejecuta el comando de despliegue reemplazando `<TU_CLAVE_PILOTO>` y `<URL_SERVICIO_TOOLBOX_MCP>`:

```powershell
gcloud run deploy tottus-asistente-transporte `
  --source . `
  --region us-central1 `
  --platform managed `
  --allow-unauthenticated `
  --memory 1Gi `
  --cpu 1 `
  --min-instances 0 `
  --max-instances 5 `
  --set-env-vars "BIGQUERY_PROJECT=tot-corp-plo-sbx,VERTEXAI_PROJECT=tot-corp-plo-sbx,USE_VERTEXAI=true,GEMINI_MODEL=gemini-3.5-flash-lite,GOOGLE_CLOUD_LOCATION=us-central1,TOOLBOX_URL=<URL_SERVICIO_TOOLBOX_MCP>,PILOT_ACCESS_KEY=<TU_CLAVE_PILOTO>,ALLOWED_USERS=all_users"
```

---

## 🔐 Configuración de Permisos IAM para la Cuenta de Servicio de Cloud Run

Para que Cloud Run consulte Vertex AI y BigQuery mediante credenciales nativas (ADC) sin archivos `.json` locales, la cuenta de servicio asignada debe contar con los siguientes roles en GCP:

1. **Usuario de Vertex AI (`roles/aiplatform.user`):** Para invocar el modelo Gemini (`gemini-3.5-flash-lite`).
2. **Usuario de BigQuery (`roles/bigquery.user`):** Para ejecutar trabajos de consulta en el proyecto.
3. **Visor de Datos de BigQuery (`roles/bigquery.dataViewer`):** Para leer las tablas del dataset `tot_bi_logistica_pe`.

---

## 🌐 Verificación y Acceso

Una vez finalizado el despliegue, Cloud Run entregará la URL oficial con HTTPS:
```text
Service URL: https://tottus-asistente-transporte-xxxx.a.run.app
```

* **Interfaz Web Unificada:**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/app/`
* **Diagnóstico de Salud (Healthcheck):**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/api/health`
* **Documentación Interactiva Swagger:**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/docs`
