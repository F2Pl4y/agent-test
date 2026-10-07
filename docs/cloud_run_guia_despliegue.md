# ☁️ Guía de Despliegue en Google Cloud Run — Asistente de Transporte Tottus Perú 🇵🇪

Esta guía detalla la arquitectura de producción y el procedimiento paso a paso para desplegar el backend y frontend unificados del Asistente de Transporte y Despachos en **Google Cloud Run** bajo los estándares oficiales de **Google ADK (Agent Development Kit)** y **GenAI Toolbox MCP**.

---

## 🏛️ Arquitectura del Sistema en Google Cloud (GCP)

Al desplegar en Cloud Run, eliminamos por completo la dependencia de laptops encendidas, túneles locales y problemas de red corporativa:

```mermaid
flowchart TD
    subgraph Usuarios ["👥 Usuarios Corporativos"]
        Navegador["Navegador Web / Celular\nhttps://asistente-transporte-xxxx.a.run.app/app/"]
        Teams["Microsoft Teams / Copilot Studio\n(Próxima Fase)"]
    end

    subgraph GCP_CloudRun ["☁️ Google Cloud Run (Servicio Administrado)"]
        NginxFastAPI["FastAPI + Uvicorn (:8080)\n• Servidor API Gateway\n• Servidor Web Estático (/app/)"]
        AuthRBAC["🛡️ Control Dual de Acceso\n• Dominio @tottus.com.pe\n• Whitelist RBAC"]
        AgentCore["🧠 Agente Logístico (LogisticaAgent)\nOrquestador Google ADK"]
        CacheMem["⚡ Caché en Memoria\n(AsyncTTLCache LRU+TTL)"]
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
    AgentCore -->|SQL Parametrizado / MCP| BigQuery
    IAM -.->|Autorización Automática| GCP_CloudRun
```

---

## 📋 Mapeo con el Modelo de Datos (PE - Modelo TMS Detalle)

El asistente conecta en tiempo real con las dimensiones del modelo oficial **`PE - Modelo TMS Detalle`** de Looker / BigQuery:

| Sección Looker | Dimensiones / Métricas Clave | Herramienta MCP Asociada | Propósito en el Asistente |
| :--- | :--- | :--- | :--- |
| **02. Transferencias** | `TIM`, `Fecha_Enviado`, `Hora_de_Carga` | `resumen_carga_transporte` | Rastreo de envíos entre CD y tiendas. |
| **03. Guías** | `Trf_DO`, `Shipment` | `buscar_por_shipment_o_do` | Rastreo por número de orden de entrega o despacho. |
| **04. Sellos** | Precintos de seguridad | `consultar_despachos_logistica` | Trazabilidad física del vehículo. |
| **05. Rechazo** | Mercadería devuelta | `alertas_vencimiento_transito` | Alertas preventivas en sala y tránsito. |
| **06. Lpn o Pallet** | `LPN`, `Pallet`, `sku`, `Descripcion`, `Unidades`, `Cajas`, `Peso_Total`, `Vol_Enviado` | `consultar_despachos_logistica`, `resumen_carga_transporte` | Detalle fino a nivel de bulto, producto, peso (kg) y volumen ($m^3$). |
| **07. Pagos / WMS** | `Shipment WMS Estado`, `Inventario_Whse` | `consultar_cargas_pendientes_despacho` | Detección de cargas listas en CD aún sin despacho. |

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

### 3. Despliegue Directo desde Código Fuente (Cloud Build)
Ubícate en la raíz del proyecto `agent-test` y ejecuta el comando de despliegue:

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
  --set-env-vars "BIGQUERY_PROJECT=tot-corp-plo-sbx,VERTEXAI_PROJECT=tot-corp-plo-sbx,USE_VERTEXAI=true,GEMINI_MODEL=gemini-3.5-flash-lite,GOOGLE_CLOUD_LOCATION=us-central1,PILOT_ACCESS_KEY=D4t4-PL$2026,ALLOWED_USERS=all_users"
```

---

## 🔐 Configuración de Permisos IAM para la Cuenta de Servicio de Cloud Run

Para que Cloud Run pueda consultar Vertex AI y BigQuery sin contraseñas ni archivos `.json` locales, la cuenta de servicio predeterminada de Compute Engine (o la que se asigne al servicio) debe tener los siguientes roles en GCP:

1. **Usuario de Vertex AI (`roles/aiplatform.user`)**: Para invocar el modelo Gemini 3.5 Flash-Lite.
2. **Usuario de BigQuery (`roles/bigquery.user`)**: Para ejecutar consultas en el proyecto.
3. **Visor de Datos de BigQuery (`roles/bigquery.dataViewer`)**: Para leer las tablas del dataset `tot_bi_logistica_pe`.

---

## 🌐 Verificación y Acceso

Una vez terminado el despliegue (toma entre 2 y 3 minutos), Cloud Run mostrará la URL pública oficial con HTTPS:
```text
Service URL: https://tottus-asistente-transporte-xxxx.a.run.app
```

* **Interfaz Web Completa:**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/app/`
* **Diagnóstico de Salud (Healthcheck):**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/api/health`
* **Documentación Interactiva Swagger:**  
  `https://tottus-asistente-transporte-xxxx.a.run.app/docs`
