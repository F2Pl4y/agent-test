# 🚛 Tottus Logistics AI Agent — Backend API Gateway 🇵🇪
### Motor de Inteligencia Operativa, Orquestación con Gemini y Acceso Seguro a BigQuery + SharePoint

Este repositorio contiene el **Backend y Motor de Inteligencia Artificial** del Asistente de Transporte y Despachos de **Tottus Perú (Falabella)**. Proporciona una arquitectura de API Gateway con **FastAPI**, orquestación de modelos de lenguaje con **Google Gemini** (`google-genai` / Vertex AI), integración de herramientas de datos mediante **Toolbox MCP** sobre **Google BigQuery**, seguimiento en tiempo real de unidades de provincia mediante **MonitoreoService (SharePoint / Excel)**, y un sistema de control de acceso corporativo y auditoría en **Modo Dual**.

> 🔗 **Repositorio Frontend asociado:** `agente-transporte-front` (Interfaz web estática que consume este API Gateway o se monta automáticamente en la ruta `/app/`).

---

## 🏛️ Arquitectura del Sistema

```text
+-----------------------------------------------------------------------------------+
|                        CLIENTES Y CANALES DE ACCESO                               |
|   Frontend Local (:3000 / :8000/app)  |  Frontend GitHub Pages  |  Teams (Fase 2) |
+-----------------------------------------------------------------------------------+
                                         |
                       [ Authorization: Bearer <token> ]
                                         v
+-----------------------------------------------------------------------------------+
|                    GATEWAY DE SEGURIDAD Y AUTENTICACIÓN                           |
|   1. Validación de dominio corporativo: @tottus.com.pe                            |
|   2. Modo Dual: Clave Piloto (.env) O Google OAuth 2.0 (JWT)                      |
|   3. Whitelist RBAC: Filtro por lista blanca de correos autorizados               |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                         BACKEND FASTAPI (:8000)                                   |
|   - Router: /api/auth/verify, /api/chat, /api/audit, /api/sessions, /api/health   |
|   - Orquestador: LogisticaAgent (Ciclo de razonamiento y Function Calling)        |
|   - Auditoría: SessionManager (Historial JSON por sesión y audit_log.jsonl)       |
|   - Conectores: Toolbox MCP (BigQuery) + MonitoreoService (SharePoint Excel)      |
+-----------------------------------------------------------------------------------+
        |                            |                               |
        v                            v                               v
+----------------+          +-------------------+          +-------------------+
|  MOTOR DE IA   |          |    TOOLBOX MCP    |          | MONITOREO SERVICE |
| Google Gemini  |          |  (:5001 / tools)  |          | (SharePoint/Excel)|
| 3.5 Flash-Lite |          +---------+---------+          +---------+---------+
+----------------+                    |                              |
                             [ SQL Parametrizado ]         [ Búsqueda en Memoria ]
                                      v                              v
                            +-------------------+          +-------------------+
                            |  GOOGLE BIGQUERY  |          | SHAREPOINT FALAB. |
                            |  FT_LOG_SALIDAS   |          | Tabla3 (UT Prov.) |
                            +-------------------+          +-------------------+
```

---

## 🛡️ Seguridad y Control de Acceso (Modo Dual)

El backend implementa un mecanismo de defensa en profundidad en [`backend/routers/chat.py`](backend/routers/chat.py) para garantizar que ningún dato corporativo de BigQuery sea expuesto a personas no autorizadas:

### 1. Validación Estricta de Dominio Corporativo
En el inicio de sesión (`/api/auth/verify`) y en cada petición de consulta (`/api/chat`), el correo del usuario es validado:
* **Regla:** Debe terminar obligatoriamente en `@tottus.com.pe`.
* **Respuesta ante fallo:** `403 Forbidden` (*"Acceso denegado: El asistente logístico está restringido exclusivamente a colaboradores con cuenta corporativa @tottus.com.pe"*).

### 2. Validación de Credencial en Cabecera HTTP (`Authorization`)
Los endpoints protegidos evalúan la credencial bajo dos modalidades simultáneas:

* **Modo A (Piloto Operativo — Activo):**
  * La credencial enviada se compara contra la variable `PILOT_ACCESS_KEY` definida en el archivo `.env`.
  * Utiliza la función criptográfica `secrets.compare_digest()` de Python para prevenir ataques de temporización (*timing attacks*).
* **Modo B (Google OAuth 2.0 — Preparado para Producción):**
  * Al configurar un `GOOGLE_CLIENT_ID` en el `.env`, el backend valida automáticamente la firma criptográfica del token JWT recibido contra los servidores de Google (`google.oauth2.id_token.verify_oauth2_token`) y verifica que el correo autenticado pertenezca a `@tottus.com.pe`.
* **Respuesta ante fallo:** `401 Unauthorized` (*"Credencial no autorizada. Ingresa la clave válida del piloto o inicia sesión con tu cuenta corporativa"*).

### 3. Control por Lista Blanca de Colaboradores (Whitelist RBAC)
Configurado mediante la variable `ALLOWED_USERS` en [`backend/config.py`](backend/config.py):
* **Lista restringida:** `ALLOWED_USERS=colaborador1@tottus.com.pe,colaborador2@tottus.com.pe` permite el acceso únicamente a los correos especificados.
* **Apertura controlada a todo el dominio:** `ALLOWED_USERS=all_users` habilita el acceso a cualquier cuenta corporativa `@tottus.com.pe` que cuente con la credencial válida.
* **Política Fail-Closed:** Si `ALLOWED_USERS` se deja vacío en el `.env`, el backend deniega el acceso por defecto (`403 Forbidden`).

---

## 🎯 Catálogo de Herramientas MCP y Alcance Operativo (`tools.yaml` + `MonitoreoService`)

> 📄 **Documentación adicional:**
> * [**`docs/catalogo_y_arquitectura_mcp.md`**](docs/catalogo_y_arquitectura_mcp.md): Detalle técnico de gobernanza SQL, parámetros tipados, reglas de *Lead Time*, caché TTL, paginación automática y pruebas JSON-RPC 2.0.
> * [**`Preguntas.md`**](Preguntas.md): Guía funcional de fuentes de datos (Reales vs Simuladas), restricciones y catálogo de preguntas operativas.

El agente combina **7 herramientas SQL gobernadas** en BigQuery (`tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`) servidas por Toolbox MCP y **1 herramienta de monitoreo en vivo** sobre SharePoint/Excel:

### 🚛 Dominio Transporte, Despachos y Flota Logística (8 Herramientas Activas)

1. **`resumen_carga_transporte` — Consolidado de Carga por Camión (Placa) o TIM (BigQuery MCP):** Consolida despachos por camión o transferencia. Devuelve placa, fecha de despacho, hora de carga en CD, *lead time* estimado, fecha estimada de llegada, total de pallets, cajas, unidades, peso total (kg) y volumen ($m^3$).
   * **Parámetros:** `tim`, `placa`, `tienda`, `fecha`, `fecha_fin`, `pagina`.

2. **`consultar_despachos_logistica` — Detalle Fino de Despachos y SKUs en Tránsito (BigQuery MCP):** Detalle a nivel de producto/SKU (código SKU, descripción del artículo, orden de entrega `Trf_DO`, embarque `Shipment`, hora de carga y tienda destino).
   * **Parámetros:** `tim`, `tienda`, `sku`, `placa`, `pagina`.

3. **`resumen_despachos_por_division` — Despachos Agregados por División Comercial J01 a J11 (BigQuery MCP):** Desglose agregado de unidades, cajas, peso y TIMs por división comercial en los últimos $N$ días.
   * **Parámetros:** `tienda`, `dias_atras`.

4. **`alertas_vencimiento_transito` — Control Preventivo de Calidad y Vencimiento en Tránsito (BigQuery MCP):** Identifica productos perecibles próximos a vencer que se encuentran en despacho o tránsito desde el CD hacia las tiendas.
   * **Parámetros:** `tienda`, `dias_margen`.

5. **`buscar_por_shipment_o_do` — Rastreo Logístico por Shipment o Delivery Order `Trf_DO` (BigQuery MCP):** Rastreo de despachos cuando el usuario no cuenta con el TIM pero tiene el número de Shipment o DO (Delivery Order).
   * **Parámetros:** `shipment`, `trf_do`.

6. **`buscar_tienda_por_nombre` — Búsqueda y Validación de Tiendas por Nombre o Código (BigQuery MCP):** Resuelve nombres comerciales (ej. *"Angamos"*, *"San Luis"*, *"Huánuco"*) o códigos a sus IDs oficiales en BigQuery (`123`, `114`, `451`).
   * **Parámetros:** `nombre_parcial`.

7. **`consultar_cargas_pendientes_despacho` — Camiones y TIMs Cargados en Espera de Salida (BigQuery MCP):** Identifica vehículos cargados en el Centro de Distribución (con `Hora_de_Carga` registrada) pendientes de despacho en los últimos $N$ días.
   * **Parámetros:** `tienda`, `placa`, `dias_atras`.

8. **`consultar_monitoreo_provincia` (`consultar_monitoreo_unidades`) — Monitoreo Operativo en Tiempo Real (SharePoint / Excel — Provincia y Oriente):** Información viva de seguimiento de unidades de transporte para tiendas de Provincia (`3xx`) y Oriente (`4xx`) desde `Monitoreo General UT Provincia 2030.xlsx` (hoja `Perú`, `Tabla3`). Aporta ubicación actual en carretera (`UBICACIÓN`), placa del `TRACTO`, tipo de unidad (`TIPO DE UT`), análisis de viaje con carga **ÚNICA** o **COMPARTIDA** (ventana de $\pm 2\text{ h}$ en `FIN DE CARGA`), secuencia de paradas (`Punto 1, 2, 3`), hora de salida a ruta, llegada a destino, estado (`STATUS`) y percances (`MOTIVO`).
   * **Parámetros:** `tim`, `placa`, `tienda`, `tracto`.

*(Nota: Existe adicionalmente una definición `consultar_estado_pedido_oc` en `tools.yaml` mantenida en cuarentena/plantilla y desactivada del toolset expuesto al agente).*

---

## 📡 Catálogo de Endpoints de la API

La aplicación expone una API REST documentada automáticamente bajo el estándar OpenAPI 3.1:

* **Documentación interactiva Swagger UI:** `http://localhost:8000/docs`
* **Especificación OpenAPI (JSON):** `http://localhost:8000/openapi.json`

### 1. `POST /api/auth/verify`
Valida en tiempo real el correo institucional `@tottus.com.pe`, la pertenencia a `ALLOWED_USERS` y la clave de acceso del piloto (o token Google OAuth) antes de permitir el ingreso en el frontend.
* **Cuerpo de la petición (JSON):**
  ```json
  {
    "email": "colaborador@tottus.com.pe",
    "key": "<CLAVE_PILOTO_O_GOOGLE_JWT>"
  }
  ```

### 2. `POST /api/chat`
Endpoint principal conversacional. Incluye control de concurrencia por sesión (`429 Too Many Requests` si ya existe una consulta en curso para la misma sesión).
* **Headers requeridos:**
  * `Content-Type: application/json`
  * `Authorization: Bearer <CLAVE_PILOTO_O_GOOGLE_JWT>`
* **Cuerpo de la petición (JSON):**
  ```json
  {
    "message": "¿Qué camiones salieron a la tienda 451 de Huánuco ayer?",
    "session_id": "session_abc123",
    "tienda_id": "451",
    "user_email": "colaborador@tottus.com.pe",
    "include_data": true,
    "pais": "PE"
  }
  ```
* **Respuesta (JSON):**
  ```json
  {
    "answer": "Se identificó 1 camión despachado a la tienda Huánuco...",
    "session_id": "session_abc123",
    "tools_executed": [
      {
        "tool_name": "resumen_carga_transporte",
        "arguments": { "tienda": "451" },
        "result_count": 1
      }
    ],
    "data": [ ... ]
  }
  ```

### 3. `GET /api/health`
Monitoreo de estado de salud del sistema (con caché de 60s).
* Verifica conectividad con el servidor Toolbox MCP en `TOOLBOX_URL`.
* Lista las herramientas activas en BigQuery y el modelo Gemini configurado.

### 4. `GET /api/tools`
Devuelve las definiciones y esquemas de todas las herramientas MCP disponibles en el servidor Toolbox.

### 5. `POST /api/cache/clear`
Purga tanto la memoria caché LRU+TTL (`SimpleTTLCache`) de consultas MCP como la caché en memoria de `MonitoreoService` para forzar lecturas frescas desde BigQuery y SharePoint/Excel.

### 6. `GET /api/sessions`, `GET /api/sessions/{session_id}` y `DELETE /api/sessions/{session_id}`
Gestión y trazabilidad de sesiones individuales resguardadas en disco (`data/sessions/`). Requiere cabecera `Authorization: Bearer <token>`.

### 7. `GET /api/audit`
Devuelve la bitácora cronológica unificada (`data/audit_log.jsonl`) de todas las consultas realizadas por los colaboradores para fines de gobernanza y auditoría. Requiere cabecera `Authorization: Bearer <token>`.

### 8. `GET /api/monitoreo/status`
Verifica en tiempo real el archivo Excel de monitoreo sincronizado desde SharePoint (`Monitoreo General UT Provincia 2030.xlsx`), recargando si hubo cambios y reportando el total de registros activos, `mtime` y tamaño en bytes.

---

## 📁 Estructura del Proyecto

```text
agent-test/
├── backend/
│   ├── main.py                  # Entrada principal FastAPI, CORS, GZip y montaje estático (/app)
│   ├── config.py                # Gestor centralizado de variables de entorno (.env)
│   ├── models.py                # Esquemas de datos Pydantic (Auth, Chat, Health, Auditoría)
│   ├── routers/
│   │   └── chat.py              # Endpoints /api/* con seguridad Modo Dual y control de sesión
│   ├── agents/
│   │   ├── _shared/
│   │   │   └── loader.py        # Cliente JSON-RPC 2.0 para Toolbox MCP, paginación y caché TTL
│   │   └── logistica/
│   │       ├── agent.py         # Orquestador de Gemini, Function Calling, reintentos y síntesis
│   │       └── prompts.py       # Directivas del sistema, reglas de negocio y glosario logístico
│   └── services/
│       ├── monitoreo_service.py # Lector resiliente de Excel/SharePoint (Tabla3) e itinerario de paradas
│       └── session_manager.py   # Resguardo atómico de sesiones JSON y bitácora audit_log.jsonl
├── toolbox/
│   └── tools.yaml               # Definición declarativa de las consultas SQL en BigQuery MCP
├── docs/
│   ├── catalogo_y_arquitectura_mcp.md # Documentación técnica detallada del servidor y herramientas MCP
│   └── cloud_run_guia_despliegue.md   # Guía paso a paso para despliegue en Google Cloud Run
├── data/                        # Almacenamiento local de sesiones, estado de monitoreo y bitácora
├── Preguntas.md                 # Guía funcional de preguntas, fuentes de datos y reglas operativas
├── Dockerfile                   # Definición de contenedor Python 3.11-slim para Cloud Run
├── requirements.txt             # Dependencias de Python (FastAPI, Uvicorn, google-genai, openpyxl, etc.)
├── .env.example                 # Plantilla de variables de entorno (sin secretos)
├── .env                         # Variables de entorno locales (Ignorado en Git)
├── toolbox.exe                  # Binario local del servidor MCP Toolbox (Ignorado en Git)
└── README.md                    # Documentación técnica del repositorio
```

---

## 🚀 Guía de Puesta en Marcha (Entorno Local)

### 1. Prerrequisitos e Instalación
* **Python 3.11+** instalado.
* Credenciales de Google Cloud autenticadas localmente (`gcloud auth application-default login`) o `GEMINI_API_KEY` configurada.
* Instalar dependencias de Python:
  ```powershell
  pip install -r requirements.txt
  ```
* Crear el archivo `.env` a partir de la plantilla y completar los valores:
  ```powershell
  Copy-Item .env.example .env
  ```

### 2. Ejecución de Servicios (Dos Terminales)

#### Terminal 1: Iniciar el Servidor de Datos MCP
```powershell
.\toolbox.exe --config toolbox\tools.yaml --port 5001
```
*(Debe mostrar que el servidor MCP inició en el puerto `5001`)*

#### Terminal 2: Iniciar el Servidor FastAPI
```powershell
uvicorn backend.main:app --reload --port 8000
```
*(Debe mostrar: `Uvicorn running on http://127.0.0.1:8000` y `Toolbox MCP conectado exitosamente`)*

---

## 🔗 Armonización con el Frontend y Pruebas Remotas

### 1. Pruebas Locales Unificadas
Si el repositorio `agente-transporte-front` se encuentra junto a `agent-test` (`../agente-transporte-front`), FastAPI lo detecta y sirve automáticamente:
* Visita directamente: 👉 **`http://localhost:8000/app/`**
* O inicia el frontend por separado en el puerto `3000` (`python -m http.server 3000`).

### 2. Pruebas Remotas (GitHub Pages + Túnel HTTPS)
1. Expón el puerto `8000` mediante **VS Code Dev Tunnels**, Cloudflare Tunnel o ngrok (ej. `https://xxxx-8000.use.devtunnels.ms`).
2. Comparte la URL del frontend alojado en **GitHub Pages** pasando el parámetro `?api=`:
   ```text
   https://<tu-usuario>.github.io/agente-transporte-front/?api=https://xxxx-8000.use.devtunnels.ms
   ```
3. Los colaboradores autorizados ingresan con su correo corporativo `@tottus.com.pe` y la clave configurada en `PILOT_ACCESS_KEY`.
