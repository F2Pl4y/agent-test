# PoC — Agente de Insights Operativos (Tottus) — MVP v1.5 (Pivote Comercial)

El Agente de Insights Operativos permite a los gerentes de tienda interactuar con datos en tiempo real de BigQuery (ventas, avance de logro de plan, crecimiento vs año anterior, ranking clúster y márgenes de ganancia GPS) en lenguaje natural para diagnosticar desviaciones comerciales y recibir reportes matutinos automatizados de cierre.

Este repositorio está adaptado para el **Pivote Comercial del MVP v1.5**, enfocado en datos y métricas comerciales a nivel de tienda y sus **11 divisiones individuales (J01 a J11)**. Soporta diagnóstico de inventario (quiebres, stock negativo y tránsito de pedidos) exclusivamente para tiendas de Perú (PE), mientras mantiene un alcance enfocado exclusivamente en ventas y desempeño comercial para tiendas de Chile (CL).

---

## 🎯 Catálogo de Herramientas MCP y Alcance por País

El repositorio expone y ejecuta **22 herramientas analíticas gobernadas** de solo lectura hacia BigQuery, organizadas por país y dominio operativo:

### 🇵🇪 Alcance Perú (PE) — 22 Herramientas Activas
Perú cuenta con el alcance comercial completo de **Ventas (16 herramientas)** más el diagnóstico operativo de **Inventario, Quiebres y Mermas (6 herramientas)**:

#### 📊 Dominio Ventas y Desempeño Comercial (`mcp_ventas` - 16 Herramientas)
1. **`fetch_resumen_global_tienda` — Resumen Comercial Diario de Tienda (Cierre):** Venta neta física vs digital, logro presupuestal, crecimiento vs año anterior, margen GPS y penetración de marca propia.
2. **`fetch_resumen_mes_global_tienda` — Desempeño Acumulado del Mes (MTD):** Venta acumulada MTD, meta presupuestal del mes, proyección, % de logro, margen GPS y días calendario restantes.
3. **`fetch_resumen_semana_tienda` — Desempeño de la Semana Rodante (7 Días):** Venta y logro presupuestal de los últimos 7 días frente a la misma semana equivalente del año anterior.
4. **`fetch_performance_divisiones_semana` — Ranking Semanal de Categorías por Ingresos:** Desglose de las 11 divisiones comerciales (J01 a J11) para los últimos 7 días (venta, logro %, crecimiento % y margen).
5. **`top_divisiones_en_riesgo` — Detección Proactiva de Divisiones en Riesgo:** Filtro y ordenamiento de las Top N divisiones con peor logro presupuestal o mayor caída para alerta oportuna.
6. **`fetch_performance_divisiones` — Matriz Completa de las 11 Divisiones (Día y Mes):** Matriz consolidada 11x2 con logro y crecimiento de todas las categorías para el día y para el acumulado del mes.
7. **`fetch_venta_dia_division` — Diagnóstico de División Específica (Día):** Venta neta, unidades, presupuesto diario, margen GPS, venta física y e-commerce para una categoría puntual (ej. J01, J04).
8. **`fetch_venta_mes_comercial_division` — Diagnóstico de División Específica (Mes MTD):** Acumulado MTD, presupuesto mensual, tasa de margen GPS y penetración de marca propia por división.
9. **`drilldown_subclases_division` — Drill-down Multidireccional por Subclases:** Desglose a nivel clase y subclase ordenable por `TOP_CRECIMIENTO`, `PEOR_CAIDA` o `TOP_VENTA`.
10. **`evaluar_contexto_cluster` — Benchmarking de Tienda vs Promedio del Clúster:** Compara el crecimiento de la tienda piloto contra el promedio ponderado de sus pares del mismo clúster y formato.
11. **`fetch_tiendas_del_cluster` — Listado de Tiendas Pares del Clúster:** Mapeo de locales físicos que integran el mismo clúster operativo y formato de la tienda consultada.
12. **`fetch_venta_mes_historico` — Histórico Mensual y Comparativa Anual (R300):** Venta neta, meta presupuestal, unidades y margen GPS de cualquier mes cerrado del histórico anual (formato YYYYMM).
13. **`fetch_venta_sku` — Venta y Ranking de Productos / SKUs Individuales:** Ranking de facturación por producto para una fecha determinada, con opción de filtro por división y límite dinámico.
14. **`fetch_sku_caida_vs_promedio` — Detección de SKUs con Mayor Desplome vs Promedio Mensual:** Detección de caídas anómalas de venta diaria vs promedio móvil del mes para identificar quiebres ocultos.
15. **`fetch_ranking_tiendas` — Ranking de Desempeño de Tiendas de la Cadena:** Posición ordinal (Puesto 1..N) de todas las tiendas de la cadena según su logro de plan presupuestal y crecimiento.
16. **`buscar_tienda_por_nombre` — Búsqueda Semántica de Tienda por Nombre:** Resolución de nombres coloquiales o parciales (ej. *"Angamos"*, *"San Luis"*, *"Moyobamba"*) hacia su ID numérico de BigQuery.

#### 📦 Dominio Inventario, Quiebres y Mermas (`mcp_inventario` - 6 Herramientas)
17. **`resumen_inventario_division` — Diagnóstico Integral de Stock y Quiebres:** SKUs activos, productos en quiebre en sala, quiebres mitigados por pedido en tránsito (Stock On-Order) y stock negativo.
18. **`fetch_inventario_division` — Detalle de Stock On-Hand y Pedidos en Tránsito:** SKUs específicos con alertas operativas en sala, número de pedido de reposición y unidades en camino desde el CD.
19. **`ranking_divisiones_quiebre` — Ranking de Divisiones por Tasa de Quiebre:** Porcentaje de quiebre (% SKUs sin stock / Total SKUs activos) para cada una de las 11 divisiones ordenadas por criticidad.
20. **`fetch_top_merma_sku` — Top SKUs de Merma y Bajas Operacionales (Looker AM):** Ranking de productos con mayor pérdida o ajuste operativo (`mrpt = 'AM'`), con soporte a nivel general de toda la tienda o filtrable por división.
21. **`fetch_resumen_merma_division` — Resumen Consolidado de Mermas por División y Ratio sobre Venta:** Costo total de merma, unidades mermadas, % de participación de merma y ratio de merma (% sobre venta neta) de J01 a J11 y gran total tienda.
22. **`fetch_merma_mes_historico` — Evolución Mensual Histórica de Merma Anual:** Curva y consolidado mes a mes de pérdidas operacionales en el año actual (2026) para análisis de estacionalidad.

---

### 🇨🇱 Alcance Chile (CL) — 16 Herramientas Activas
Chile cuenta con el alcance comercial completo de **Ventas (16 herramientas)** (`fetch_resumen_global_tienda` a `buscar_tienda_por_nombre`), excluyendo el módulo de inventarios y stock en esta fase:
1. **`fetch_resumen_global_tienda`** — Resumen Comercial Diario de Tienda (Cierre)
2. **`fetch_resumen_mes_global_tienda`** — Desempeño Acumulado del Mes (MTD)
3. **`fetch_resumen_semana_tienda`** — Desempeño de la Semana Rodante (7 Días)
4. **`fetch_performance_divisiones_semana`** — Ranking Semanal de Categorías por Ingresos
5. **`top_divisiones_en_riesgo`** — Detección Proactiva de Divisiones en Riesgo
6. **`fetch_performance_divisiones`** — Matriz Completa de las 11 Divisiones (Día y Mes)
7. **`fetch_venta_dia_division`** — Diagnóstico de División Específica (Día)
8. **`fetch_venta_mes_comercial_division`** — Diagnóstico de División Específica (Mes MTD)
9. **`drilldown_subclases_division`** — Drill-down Multidireccional por Subclases
10. **`evaluar_contexto_cluster`** — Benchmarking de Tienda vs Promedio del Clúster
11. **`fetch_tiendas_del_cluster`** — Listado de Tiendas Pares del Clúster
12. **`fetch_venta_mes_historico`** — Histórico Mensual y Comparativa Anual (R300)
13. **`fetch_venta_sku`** — Venta y Ranking de Productos / SKUs Individuales
14. **`fetch_sku_caida_vs_promedio`** — Detección de SKUs con Mayor Desplome vs Promedio Mensual
15. **`fetch_ranking_tiendas`** — Ranking de Desempeño de Tiendas de la Cadena
16. **`buscar_tienda_por_nombre`** — Búsqueda Semántica de Tienda por Nombre

> [!NOTE]
> El módulo de inventario y control de mermas para Chile se encuentra en desarrollo y se habilitará oficialmente en la Fase 2.

---

## 📱 Estructura de Canales de Microsoft Teams (Piloto)

La solución está diseñada para operar nativamente en **Microsoft Teams** estructurada en equipos de trabajo y canales específicos según el rol del usuario:

### 1. 🇵🇪 Equipo: `Agente Operativo - PE` (Operaciones Perú)
* **`General`**: Canal público para anuncios y reportes globales.
* **`Tienda Angamos 🔒`**: Canal privado para el reporte y consultas de la tienda **Angamos (ID 123)**.
* **`Tienda San Luis 🔒`**: Canal privado para el reporte y consultas de la tienda **San Luis (ID 114)**.

### 2. 🇨🇱 Equipo: `Agente Operativo - CL` (Operaciones Chile)
* **`General`**: Canal público para anuncios y reportes globales.
* **`Tienda Nataniel 🔒`**: Canal privado para el reporte y consultas de la tienda **Nataniel (ID 104)**.
* **`Tienda Kennedy 🔒`**: Canal privado para el reporte y consultas de la tienda **Kennedy (ID 109)**.

### 3. 👔 Equipo: `Agente Operativo - Gerencia` (Consolidados Corporativos)
* **`General`**: Canal público de gerencia regional.
* **`Tiendas Chile 🔒`**: Canal para el Gerente Comercial de Chile. Recibe un resumen consolidado nacional del conjunto de tiendas clave en Chile.
* **`Tiendas Perú 🔒`**: Canal para el Gerente Comercial de Perú. Recibe un resumen consolidado nacional del conjunto de tiendas clave en Perú.

### 🛠️ Equipo: `Agente Operativo DEV` (Entorno de Desarrollo)
* **`Tiendas Chile 🔒`**: Canal de pruebas locales de Chile mapeado a webhooks de desarrollo.
* **`Tiendas Perú 🔒`**: Canal de pruebas locales de Perú mapeado a webhooks de desarrollo.

> [!NOTE]
> **Prototipo Frontend Local:** La carpeta `frontend/` contiene una aplicación web en Next.js. Este componente se desarrolló únicamente para la validación inicial y prototipado rápido en desarrollo local. **No se despliega en producción**, ya que los usuarios finales consumen la solución directamente en Microsoft Teams.

---

## 🏗️ Arquitectura Corporativa de MCPs e Inteligencia Operativa

La solución se basa en una arquitectura de **Nivel 1 (Catálogo Corporativo de MCPs Reutilizables)** y **Nivel 2 (Inteligencia & Orquestación de Casos de Uso)** sobre Google ADK y Vertex AI:

```
                                [ 📱 MS TEAMS / COPILOT STUDIO ]
                                               │
                                               ▼ (HTTP POST)
                              ┌─────────────────────────────────┐
                              │     🚪 Cloud Run API Gateway    │
                              │ (RBAC Tienda/País + Firestore)  │
                              └────────────────┬────────────────┘
                                               │
                                               ▼
                              ┌─────────────────────────────────┐
                              │  🛡️ Guardrail Entrada / Salida  │
                              │ (Model Armor / On-Topic Filter) │
                              └────────────────┬────────────────┘
                                               │
                                               ▼
                              ┌─────────────────────────────────┐
                              │      ⭐ 1. ORQUESTADOR RAÍZ     │
                              │ (Synthesis & Routing Engine)    │
                              └────────────────┬────────────────┘
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
             ┌─────────────────────────────┐               ┌─────────────────────────────┐
             │ 📊 MCP VENTAS (`mcp_ventas`)│               │ 📦 MCP INVENTARIO           │
             │ (16 tools: R300, MTD, Plan, │               │    (`mcp_inventario`)       │
             │  GPS, Subclases, Clúster,   │               │ (6 tools: Stock, Quiebres,  │
             │  Venta SKUs, Ranking BQ)    │               │  Stock OO, Mermas AM, Hist) │
             └──────────────┬──────────────┘               └──────────────┬──────────────┘
                            │                                             │
                            └──────────────────────┬──────────────────────┘
                                                   │
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │ 🗄️ BigQuery Enterprise Data  │
                                    │ (R300, FT_INVENTARIO,       │
                                    │  INVENTARIO_CONTROL)        │
                                    └─────────────────────────────┘
```

### 📦 Catálogo de MCPs Corporativos (Nivel 1):
1. **`MCP Ventas y Desempeño Comercial` (`mcp_ventas`)**: Expone 16 herramientas para consultar avance de ventas, cumplimiento presupuestal, comparativa vs año anterior, desglose por subclase (top ventas / top crecimiento / peores caídas), performance semanal por división (`fetch_performance_divisiones_semana`), comparativa histórica mensual (`fetch_venta_mes_historico`), ranking de tiendas y márgenes GPS.
2. **`MCP Inventario y Stock` (`mcp_inventario`)**: Expone 6 herramientas para consultar stock disponible (*on-hand*), quiebres de góndola, pedidos en tránsito desde el CD (*Stock OO*), ranking de quiebres y control de mermas/pérdidas operacionales por costo o unidades (`fetch_top_merma_sku`, `fetch_resumen_merma_division`, `fetch_merma_mes_historico` con filtros Looker `mrpt = 'AM'`).

---

## 🔌 Cómo Consumir los MCPs Corporativos desde Otros Equipos y Agentes (Nivel 1)

Uno de los principales pilares arquitectónicos de esta solución es que el **Catálogo de Herramientas MCP (GenAI Toolbox)** es un servicio desacoplado, reutilizable y auto-contenido. Cualquier otro equipo de Falabella/Tottus (Marketing, Supply Chain, Finanzas, etc.) puede consumir estas herramientas directamente sin necesidad de reescribir queries SQL complejas ni duplicar prompts extensos.

### 🧠 Principio de Herramientas Auto-Descriptivas (*Self-Describing*)
Las herramientas exponen automáticamente su schema JSON bajo el estándar OpenAPI y MCP. Esto significa que **el LLM del consumidor (Gemini, Claude o GPT) comprende de forma autónoma cuándo y cómo invocar cada herramienta**, leyendo su descripción y sus parámetros tipados sin necesidad de reglas manuales.

### 💻 Ejemplo de Integración en Python (Google ADK / Gemini):

```python
from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from toolbox_core import ToolboxSyncClient

# 1. Conexión al servidor MCP desplegado en Cloud Run (o local en desarrollo)
TOOLBOX_URL = "https://adk-agente-generador-insights-mcp-xxxxx.a.run.app"  # O "http://127.0.0.1:5001" en local
client = ToolboxSyncClient(TOOLBOX_URL)

# 2. Cargar el toolset corporativo de Ventas o Inventario
tools_ventas = client.load_toolset("insights_operativos")  # O "mcp_ventas"

# 3. Crear el agente de tu propio dominio con un prompt simple
agente_abastecimiento = LlmAgent(
    name="asistente_abastecimiento",
    model=Gemini(model="gemini-2.5-flash"),
    instruction="""
    Eres el asistente de Abastecimiento y Negociación Comercial de Falabella.
    Tu objetivo es responder consultas de ventas y stock usando las herramientas disponibles.
    Sé conciso, directo y utiliza las métricas provistas por las herramientas.
    """,
    tools=tools_ventas,  # 👈 Hereda automáticamente todas las queries y métricas gobernadas de BigQuery
)

# 4. El agente ahora puede responder preguntas complejas automáticamente:
# Ej: "¿Cuáles fueron las 5 subclases con mayor venta en Angamos (123)?"
# El LLM invocará 'drilldown_subclases_division(tienda_id='123', division_id='J01', pais='PE', orden='TOP_VENTA')' de forma autónoma.
```

---

## 🔒 Capa de Seguridad y Control de Accesos (Matriz RBAC y Alcance)

El sistema implementa un motor de seguridad desacoplado basado en **Atributos de Alcance (País y Tienda)** gobernado en Firestore (`permisos_tienda`), sincronizado directamente desde el archivo Excel corporativo (`docs/workshop_agente_insights.xlsx`).

### 🛡️ Validación por Coordenadas de Alcance (Scope ABAC / RBAC)
La autorización se evalúa matemáticamente en `backend/security_service.py` sin nombres de roles rígidos hardcodeados:
$$\text{Acceso Válido} = (\text{País Asignado} = * \lor \text{País Asignado} = \text{País Solicitado}) \land (\text{Tienda Asignada} = * \lor \text{Tienda Asignada} = \text{Tienda Solicitada})$$

| Rol en Matriz | País en Excel | Tienda en Excel | Alcance y Comportamiento |
| :--- | :---: | :---: | :--- |
| **`ADMIN`** | `*` | `*` | **Acceso Global:** Puede consultar cualquier tienda de cualquier país de la cadena en BigQuery. |
| **`GERENTE_COMERCIAL`** | `PE` (o `CL`) | `*` | **Acceso Nacional:** Puede consultar cualquier tienda del país asignado en BigQuery. |
| **`GERENTE_ZONAL`** | `PE` (o `CL`) | `104, 109` | **Acceso Multitienda:** Solo puede consultar el conjunto de tiendas que tenga asignadas. |
| **`GERENTE_TIENDA`** | `PE` (o `CL`) | `114` | **Acceso Local:** Restringido exclusivamente a su tienda asignada. |

---

### ⚡ Políticas de Sincronización y Caché (Rendimiento 0 ms)

Para garantizar un chat fluido y evitar golpear la base de datos transaccional en cada pregunta del chat de Teams:
1. **Caché en Sesión (Firestore):** Los permisos del usuario se leen desde BigQuery **únicamente en el primer mensaje de la sesión** (o al cambiar de contexto de tienda). Estos permisos se serializan y guardan en el documento de sesión de Firestore (`allowed_stores` y `rol`). Los turnos siguientes se validan en memoria usando Firestore en 0 ms.
2. **Webhooks Opcionales (Nullables):** Si deseas activar una tienda piloto de forma rápida en el chat privado 1-a-1, pero no quieres crearle un canal grupal de Teams ni webhook de Power Automate, puedes registrar la tienda en la tabla de webhooks con `webhook_url = NULL`. El scheduler diario la saltará automáticamente de forma silenciosa (sin enviar alertas), pero dejará a los usuarios autorizados chatear sobre ella.

---

## 👔 Reportes Consolidados de Gerencia Comercial (`tienda_id = 'GERENCIA'`)

Para la Gerencia Comercial (ej: Sebastian Quijada `squijadar@tottus.cl`), el bot cuenta con un flujo especial para generar y enviar reportes consolidados por país:

### ⚙️ Funcionamiento del Consolidado
* **Formato del Trigger:** El trigger de Cloud Scheduler (MLE) llama a la API con el ID genérico **`"tienda_id": "GERENCIA"`** y el país respectivo:
  * Chile: `{"tienda_id": "GERENCIA", "pais": "CL"}`
  * Perú: `{"tienda_id": "GERENCIA", "pais": "PE"}`
* **Agregación en Memoria:** El backend detecta el ID `"GERENCIA"`, selecciona las tiendas piloto del país (ej. `104` y `109` en Chile), suma las ventas y metas en vivo, y calcula las desviaciones e insights globales de la zona.
* **Envío Directo:** El reporte se envía al webhook de gerencia asignado a esa fila en BigQuery (ej. el canal de Teams **"Tiendas Chile"** de la Gerencia Comercial).
* **Independencia del Trigger:** Si se agrega una nueva tienda piloto al consolidado nacional, solo se modifica la base de datos. El trigger de MLE no requiere ningún cambio ni mantenimiento.

---

## 💻 Stack Tecnológico

| Capa | Tecnología |
|---|---|
| **Modelos LLM** | Gemini 2.5 Pro (resumen diario) y Gemini 2.5 Flash (chat) vía Vertex AI |
| **Orquestación** | Google ADK (Agent Development Kit) — `LlmAgent` ReAct |
| **Capa SQL** | MCP Toolbox (`genai-toolbox`) ejecutado en servidor Go |
| **API Backend** | FastAPI + Uvicorn |
| **Persistencia** | Firestore (`db-tot-bi-orquestador-experiencia`) para sesiones y TTL de 24h |
| **Seguridad** | API Key (`X-Copilot-Key`) para Copilot Studio / OIDC Tokens en GCP |
| **Canal Final** | Microsoft Teams (Copilot Studio + Power Automate Webhooks) |
| **Prototipado Local**| Next.js 14 + TailwindCSS (Fase 1 - opcional para pruebas de navegador) |
---

## 🧪 Pruebas de Resúmenes de Gerencia y Enrutamiento a DEV

Para iterar de forma segura sobre los diseños de las tarjetas adaptativas de gerencia sin sobrecargar el canal del Gerente Comercial de Chile en producción, puedes reconfigurar las llamadas y el enrutamiento siguiendo estas guías:

### 1. ⚙️ ¿Cómo desviar los reportes de Gerencia Comercial a tu equipo de DEV?

El backend cuenta con una variable de override de desarrollo en tu archivo `.env`. Si está activa, **todos los envíos de reportes de ese país se interceptan y se mandan a tu canal de desarrollo**:

1. Abre tu archivo `.env` local.
2. Descomenta la variable correspondiente al país que deseas probar:
   ```env
   # Webhooks de desarrollo (Redirección segura para pruebas de dev)
   # DEV_TEAMS_WEBHOOK_PE=https://...
   DEV_TEAMS_WEBHOOK_CL=https://[Webhook_de_tu_canal_de_pruebas_en_Agente_Operativo_DEV]
   ```
3. Guarda el archivo `.env`. El recargador automático de FastAPI (`--reload`) refrescará el servidor en 1 segundo.
4. **Resultado:** Al disparar el consolidado de Gerencia de Chile (`GERENCIA`, `CL`), el backend ignorará el webhook de Sebastian Quijada registrado en BigQuery y enviará la tarjeta adaptativa directamente a tu canal de pruebas de dev.

---

### 2. ⚡ Comandos de Trigger Manual (Templates de PowerShell)

Puedes forzar la generación y envío del reporte de Gerencia Comercial en cualquier momento llamando al endpoint del scheduler local:

* **Trigger para Gerencia de Chile (CL):**
  ```powershell
  Invoke-RestMethod -Uri "http://localhost:8000/jobs/daily-summary" `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"tienda_id": "GERENCIA", "pais": "CL"}'
  ```

* **Trigger para Gerencia de Perú (PE) (Fase 2):**
  ```powershell
  Invoke-RestMethod -Uri "http://localhost:8000/jobs/daily-summary" `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"tienda_id": "GERENCIA", "pais": "PE"}'
  ```

---

## 📁 Estructura del Repositorio

```
poc-tottus-insights-operativos/
├── backend/                      # FastAPI + Arquitectura Multi-Agente (Google ADK)
│   ├── main.py                   # Registro de rutas, middlewares, CORS y lifespan
│   ├── config.py                 # Variables de entorno, AI Gateway y Tool Cache LRU
│   ├── gateway.py                # Integración con AI Gateway KAIROS (Falabella) y fallback Vertex AI
│   ├── security_service.py       # Control de accesos RBAC (tienda/país) y ContextVar de sesión
│   ├── remote_config.py          # Gestión dinámica de umbrales comerciales desde Firestore
│   ├── guardrails.py             # Filtro On-Topic y validación de seguridad (Model Armor)
│   ├── streaming.py              # Generación de Server-Sent Events (SSE) en tiempo real
│   ├── firestore_service.py      # Persistencia de sesiones, preferencias y caché diario (24h)
│   ├── prompt.py                 # Directiva centralizada anti-jailbreak y encapsulamiento seguro
│   ├── bigquery_logger.py        # Registro asíncrono de telemetría, tokens y costos en BigQuery
│   ├── glossary.py               # Glosario corporativo de fórmulas y métricas
│   ├── models.py                 # Modelos de datos Pydantic para APIs
│   ├── senders/
│   │   └── teams.py              # Generación de Adaptive Cards interactivas y webhooks de Teams
│   ├── agents/                   # Capa Multi-Agente Especializada (Nivel 2)
│   │   ├── orquestador_adk.py    # Enrutador semántico híbrido (Fast-Path 0ms + Gemini Flash)
│   │   ├── _shared/
│   │   │   └── loader.py         # Singleton MCP Toolbox, AsyncTTLCache (LRU+TTL) y wrapper RBAC
│   │   ├── ventas/
│   │   │   ├── agent.py          # Agentes Pro PE/CL (resumen) y Flash PE/CL (chat 0ms thinking)
│   │   │   └── prompts.py        # Instrucciones comerciales PE/CL y consolidado de gerencia
│   │   └── inventario/
│   │       ├── agent.py          # Agente Flash PE (chat 0ms thinking)
│   │       └── prompts.py        # Diagnóstico de stock, quiebres y mermas (general y por división)
│   └── routers/
│       ├── jobs.py               # Scheduler diario de resúmenes (/jobs/daily-summary)
│       ├── copilot.py            # API Copilot Studio (/api/copilot/message y /api/copilot/stream)
│       ├── chat.py               # API WebSocket/REST para web chat local
│       └── preferences.py        # API para preferencias de tiendas locales
├── frontend/                     # Next.js 14 (Prototipo web local de desarrollo)
├── copilot/                      # Contratos para Microsoft Copilot Studio
│   └── swagger.json              # OpenAPI Spec para registrar el conector personalizado de Teams
├── toolbox/
│   └── tools.yaml                # 22 herramientas analíticas gobernadas de BigQuery
├── docs/                         # Documentación técnica, funcional y de arquitectura
│   ├── catalogo_herramientas_mcp.md # Catálogo exhaustivo de las 22 herramientas MCP
│   └── workshop_agente_insights.xlsx # Matriz de permisos, roadmap y fases de producto
├── scripts/
│   ├── run_toolbox.ps1           # Script PowerShell para levantar genai-toolbox local
│   ├── setup_permisos_excel.py   # Sincronización de matriz de usuarios Excel -> Firestore
│   └── check_bigquery_access.py  # Verificación de conectividad BQ desde local
├── .env.example                  # Plantilla de configuración de entorno
├── pyproject.toml                # Dependencias de Python gestionadas con uv
├── uv.lock                       # Lockfile reproducible de dependencias
└── README.md
```

---

## ⚡ Arquitectura de Alto Rendimiento y Optimización de Latencias

Para brindar una experiencia conversacional instantánea y ejecutiva en Microsoft Teams, el sistema cuenta con cuatro palancas de optimización de rendimiento:

```
                  ┌───────────────────────────────────────────────────────────┐
                  │ ⚡ 1. FAST-PATH DE ENRUTAMIENTO (0 ms)                    │
                  │ Clasificación heurística instantánea (Ventas vs Stock)    │
                  └─────────────────────────────┬─────────────────────────────┘
                                                │
                  ┌─────────────────────────────▼─────────────────────────────┐
                  │ ⚡ 2. IN-MEMORY QUERY CACHE (LRU + TTL) (< 0.2 ms)        │
                  │ AsyncTTLCache (200 entradas, TTL 30m) en loader.py        │
                  │ Evita re-consultar BigQuery para datos batch del día      │
                  └─────────────────────────────┬─────────────────────────────┘
                                                │
                  ┌─────────────────────────────▼─────────────────────────────┐
                  │ ⚡ 3. REDACCIÓN ULTRA-RÁPIDA (thinking_budget = 0)        │
                  │ Gemini 2.5 Flash genera respuestas en 1 a 3 segundos      │
                  └─────────────────────────────┬─────────────────────────────┘
                                                │
                  ┌─────────────────────────────▼─────────────────────────────┐
                  │ ⚡ 4. STREAMING SSE EN TIEMPO REAL                        │
                  │ Endpoint /api/copilot/stream emite tokens en vivo         │
                  └───────────────────────────────────────────────────────────┘
```

1. **Fast-Path Heurístico de Enrutamiento (0 ms):** En [`backend/agents/orquestador_adk.py`](backend/agents/orquestador_adk.py), las consultas evidentes de ventas (ej. *"ventas de ayer"*, *"logro MTD"*) o inventario (ej. *"quiebres"*, *"merma"*) se despachan directamente al especialista sin invocar al LLM enrutador, ahorrando entre 1 y 2 segundos de latencia.
2. **Caché en Memoria para Herramientas BigQuery (`AsyncTTLCache`):** En [`backend/agents/_shared/loader.py`](backend/agents/_shared/loader.py), las respuestas de las 22 herramientas de Toolbox se guardan en un caché LRU asíncrono con reloj monotónico (`maxsize=200`, `TTL=30 min`). Como los datos transaccionales se cargan de madrugada y son estables durante el día, las consultas repetidas pasan de **6–16 segundos a solo 0.11 milisegundos**. La seguridad RBAC se valida estrictamente **antes** de consultar el caché.
3. **Optimización de Pensamiento en Flash (`thinking_budget=0`):** En [`backend/agents/ventas/agent.py`](backend/agents/ventas/agent.py) y [`backend/agents/inventario/agent.py`](backend/agents/inventario/agent.py), los agentes de chat interactivo operan con `thinking_budget=0` y `temperature=0.0`. Esto reduce el tiempo de redacción de Gemini 2.5 Flash de 12–15s a solo **1 a 3 segundos**.
4. **Streaming SSE en Tiempo Real:** El endpoint `/api/copilot/stream` transmite la respuesta token por token mediante Server-Sent Events (SSE), mostrando de inmediato la escritura al usuario y eliminando la percepción de espera.

---

## 🗃️ Tablas de Configuración Dinámica (BigQuery)

Para desacoplar la base de código y evitar reiniciar los servidores al agregar nuevas tiendas piloto, el enrutamiento y envío se gestiona mediante una tabla centralizada en BigQuery:
`tot-bi-corp-arq-dev.tot_bi_generador_insights.mapeo_webhooks_teams`

### Esquema de la Tabla:
| Campo | Tipo | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `tienda_id` | `STRING` | ID físico numérico de la tienda. | `"104"` |
| `pais` | `STRING` | Código del país (`PE` o `CL`). | `"CL"` |
| `nombre_tienda` | `STRING` | Nombre comercial descriptivo. | `"Nataniel"` |
| `webhook_url` | `STRING` | Endpoint de Power Automate para el envío matutino. | `https://...` |
| `canal_teams_id` | `STRING` | ID del canal de Teams (para resolver origen de chat). | `19:jTef7miPE1p...` |

### ⚡ Optimización de Latencia (In-Memory Cache & Hot Refresh)
* **Carga en Inicio:** Al arrancar el backend FastAPI, lee esta tabla una sola vez y la guarda en un diccionario global de Python. Las consultas del chat en vivo resuelven el canal de origen en **0.00 ms (cero latencia)**.
* **Refresco en Caliente (Hot Refresh):** Si agregas un nuevo webhook o canal en BigQuery y quieres que el bot lo reconozca de inmediato sin reiniciar el servidor de producción, ejecuta:
  ```powershell
  Invoke-RestMethod -Uri "https://tu-servidor.com/api/copilot/refresh-channels" -Method Post -Headers @{"X-Copilot-Key" = "tottus-secret-key-1234"}
  ```

---

## 🚀 Configuración y Ejecución Local

### 📋 Prerrequisitos
* Python 3.13+ (gestionado con [uv](https://docs.astral.sh/uv/))
* SDK de Google Cloud (`gcloud`) instalado y autenticado:
  ```bash
  gcloud auth application-default login
  ```
* Binario `toolbox.exe` de Google (colocado en la ruta configurada en `TOOLBOX_BIN`).

### 1. Preparar el Entorno Virtual Python
uv crea el entorno virtual e instala las dependencias desde el lockfile:
```bash
uv sync
```

### 2. Configurar Variables de Entorno
Copia la plantilla de variables de entorno:
```powershell
Copy-Item .env.example .env
```
Completa las variables en el archivo `.env` recién creado (en especial `GOOGLE_CLOUD_PROJECT`, `TOOLBOX_BIN`, `FIRESTORE_DB` y los webhooks de prueba de Teams).

### 3. Cargar Matriz de Usuarios y Permisos en Firestore (Inicial / Opcional)
Sincroniza la tabla de permisos de usuarios y roles desde la pestaña `Usuarios_Permisos` del archivo Excel (`docs/workshop_agente_insights.xlsx`) hacia la colección `permisos_tienda` en Firestore:
```powershell
python scripts/setup_permisos_excel.py
```

### 4. Ejecutar los Componentes

#### Terminal 1: Servidor MCP Toolbox
Levanta el servidor MCP que expone las 22 herramientas SQL hacia BigQuery:
```powershell
.\scripts\run_toolbox.ps1
```
Debe finalizar mostrando: `Server ready to serve!` e `Initialized 22 tools.` (Si realizas algún cambio en `toolbox/tools.yaml`, reinicia esta terminal).

#### Terminal 2: API Backend (FastAPI)
Levanta la API que orquesta el agente:
```powershell
.venv\Scripts\activate
uvicorn backend.main:app --reload --port 8000
```
La documentación Swagger interactiva se expone en: http://localhost:8000/docs

---

## 🧪 Pruebas e Integración

### Generar Resumen Diario Manualmente
Para simular el trigger de Cloud Scheduler de las 8 AM, puedes hacer una petición POST en PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/jobs/daily-summary" -Method Post -ContentType "application/json" -Body '{"tienda_id": "104", "pais": "CL"}'
```
Esto creará el reporte, lo enviará al webhook de Teams de la tienda correspondiente (Nataniel `104` en Chile) con el formato de tablas compactas de 11 divisiones y los botones de feedback interactivos.

### 💬 Comandos Conversacionales en Teams (Chat 1-a-1)
En la interfaz de chat individual con el agente en Microsoft Teams, se admiten los siguientes comandos y resoluciones de contexto para **ambos países (Perú y Chile)**:

* **`/resumen [tienda_id | nombre_tienda]`**: Cambia instantáneamente la sesión activa del usuario a la tienda especificada y muestra el resumen diario correspondiente de la caché en milisegundos.
  * *Soporte por ID numérico o Nombre comercial:*
    * `/resumen 123` o `/resumen Angamos` (fija el chat en Angamos, PE)
    * `/resumen 114` o `/resumen San Luis` (fija el chat en San Luis, PE)
    * `/resumen 104` o `/resumen Nataniel` (fija el chat en Nataniel, CL)
    * `/resumen 109` o `/resumen Kennedy` (fija el chat en Kennedy, CL)
    * `/resumen Piedra Roja` (fija el chat en Piedra Roja, CL)
  * *Botones / Chips de Sugerencia Rápida:* La interfaz expone botones de un clic para saltar entre tiendas asignadas (`⚡ /resumen Angamos`, `⚡ /resumen Nataniel`, `⚡ /resumen Piedra Roja`).
  * *Deep-Linking:* Este comando se inyecta de forma automatizada en el cuadro de texto del chat cuando el gerente hace clic en el enlace *"Iniciar conversación 1-a-1"* de las alertas matutinas del canal.
* **`dame el resumen` / `resumen de hoy`**: Solicita el resumen comercial diario de la tienda activa en ese momento. Al estar cacheado por 24 horas en Firestore, el backend lo devuelve de inmediato en <500ms, evitando los 30 segundos de latencia de consulta y optimizando costos.
* **Búsqueda conversacional de tiendas por nombre**: Si preguntas por una tienda usando su nombre en lugar de su código ID (ej. *"¿Cómo fue la venta ayer en Moyobamba?"* en Perú, o *"avance del plan en Nataniel"* en Chile), el agente ejecutará internamente la herramienta `buscar_tienda_por_nombre` para identificar su `tienda_id` y `pais` mediante coincidencia parcial en BigQuery, reconfigurando la consulta automáticamente.

---

### 🛡️ Filtros de Seguridad y Guardrails Operativos
El backend cuenta con un middleware interceptor en FastAPI para garantizar la seguridad y optimizar costos de procesamiento en **ambos países (Perú y Chile)**:
* **Qué bloquea:** Preguntas off-topic (ej. fútbol, cultura general), lenguaje inapropiado e intentos de manipulación de instrucciones (Jailbreaks/Prompt Injections).
* **Cómo funciona:** Evalúa la pregunta con un modelo liviano de *Gemini 2.5 Flash* (con `thinking_budget=0` para reducir latencia a <500ms). Si la pregunta no está relacionada con la operación comercial, el bot bloquea el flujo hacia el agente principal y responde con un mensaje corporativo estándar.
* **Directiva Anti-Jailbreak Centralizada:** Todas las instrucciones de agentes en [`backend/prompt.py`](backend/prompt.py) heredan una directiva estricta de neutralización ante intentos de override, suplantación de identidad o escape de rol.


