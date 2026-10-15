# 📋 Guía de Preguntas del Agente Logístico Tottus

Este documento explica de forma clara y directa:
1. **Los archivos y fuentes exactas que consulta el agente.**
2. **Qué datos son 100% REALES y cuáles son "IMAGINARIOS" (simulados/prototipo).**
3. **Las restricciones y reglas obligatorias para formular las preguntas.**
4. **La lista de preguntas que responde según cada fuente.**

---

## 🗂️ 1. Archivos y Fuentes de Datos que Revisa el Agente

El agente consulta **4 archivos y fuentes principales** dependiendo de la pregunta:

| # | Archivo o Fuente | Ubicación / Nombre exacto | ¿Qué información saca de ahí? |
| :-: | :--- | :--- | :--- |
| **1** | **Base de Datos Google BigQuery** *(Nube)* | Tabla: `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS` | Despachos históricos y recientes, camiones (placas), transferencias (TIM), hora exacta de carga en CD, cajas, unidades, peso, volumen, detalle de productos/SKUs, Shipments y Delivery Orders (DO). |
| **2** | **Archivo Excel de SharePoint** *(Local/Nube)* | `Monitoreo General UT Provincia 2030.xlsx`<br>Hoja: **`Perú`** / Tabla: **`Tabla3`** | Ubicación geográfica actual del camión en carretera (ej. `CHAO`, `Casapalca`), placa del `TRACTO`, hora real de salida a ruta, hora de llegada y registro en tienda, estado operativo y percances (`MOTIVO`). |
| **3** | **Archivo de Reglas y Directivas** *(Código)* | `backend/agents/logistica/prompts.py` | Reglas de tiempos de viaje (Lead Times: 24h, 48h, 72h), guardrails de seguridad y el protocolo de respuestas para reprogramaciones de órdenes de compra (OC). |
| **4** | **Bitácora de Auditoría** *(Historial real)* | `data/audit_log.jsonl` | Registro histórico de todas las preguntas reales que los usuarios ya han realizado en sus pruebas con fecha, hora, usuario y respuestas. |

---

## ⚖️ 2. ¿Se usa Data REAL o "IMAGINARIA"?

Es fundamental distinguir qué consultas traen datos reales de las bases de datos corporativas y cuáles son un prototipo guiado:

### 🟢 DATA 100% REAL (BigQuery y SharePoint)
Todas estas consultas viajan a los sistemas corporativos reales y devuelven datos verídicos de la operación:
* **Despachos, camiones, bultos y pesos:** Vienen de BigQuery (`FT_LOG_SALIDAS`). Si preguntas por la TIM `676169276`, busca esa fila exacta en la base de datos de Tottus.
* **Detalle de SKUs y mercadería:** Viene de BigQuery. Los nombres de productos (ej. *"Manzana Royal Gala"*, *"Chorizo Precocido Segoviana"*) son los artículos reales cargados en ese camión.
* **Ubicación en vivo y seguimiento en ruta:** Viene del Excel de SharePoint. Si dice `CHAO` o `AME860`, es el dato que el equipo de monitoreo escribió en la hoja.
* **Camiones pendientes de salida:** Viene de BigQuery. Identifica camiones con hora de carga terminada pero sin fecha de despacho.

### 🟡 DATA "IMAGINARIA" / PROTOTIPO SIMULADO (Reprogramaciones de OC)
* **Órdenes de Compra (OC):** **NO consulta ninguna base de datos real.** 
* Está configurado como un **prototipo conversacional guiado** (en cuarentena en `prompts.py`).
* **Acepta cualquier OC inventada o ficticia** (ej. `123`, `123456`, `OC-999`, `mi-pedido-1`).
* El agente simula el estado del pedido y evalúa las causales de excepción (*"cliente ausente"*, *"fuera de horario"*, *"zona peligrosa"*) aplicando la tabla oficial de procedimiento de Home Delivery sin tocar BigQuery.

### 🔵 CÁLCULOS MATEMÁTICOS ESTIMADOS (Derivados de datos reales)
* **Fecha y hora estimada de llegada a tienda:** No está escrita en una celda fija de la base de datos; el agente la **calcula matemáticamente** sumando el Lead Time oficial de la tienda a la hora de carga real de BigQuery:
  $$\text{Llegada Estimada} = \text{Hora de Carga Real} + \text{Lead Time (24h / 48h / 72h)}$$

---

## ⚠️ 3. Restricciones y Reglas Obligatorias en las Preguntas

Para que el agente responda correctamente y no te pida aclaraciones, ten en cuenta estas restricciones:

1. **Exigencia obligatoria de Fecha o Rango de Fechas (Para BigQuery):**
   * BigQuery es una tabla inmensa particionada por fecha. Si preguntas *"¿qué camiones salieron a Atocongo?"* sin decir fecha, el agente **no ejecutará la consulta** y te responderá obligatoriamente: *"Indícame la fecha puntual (ej. 20.09) o rango de fechas para continuar"*.
   * **Excepción:** Si preguntas por un número de **TIM**, **Placa**, **Shipment** o **DO** específico, no requiere fecha porque busca directamente ese código único.
2. **Contexto del Año en Curso:**
   * Todas las fechas coloquiales (ej. *"el 26 de septiembre"*, *"ayer"*, *"el 03.10"*) se interpretan automáticamente como el año actual (`2026`).
3. **Distinción estricta: Fecha de Carga vs Fecha de Envío:**
   * La **Fecha de Carga** es el momento en que se terminó de llenar el camión en el CD (`hora_carga`).
   * La **Fecha de Envío / Despacho** es el día en que el camión salió del CD a la carretera. No son lo mismo y el agente no las confunde.
4. **Productos vs TIMs (Cuidado con saturación):**
   * El detalle de artículos/SKUs solo debe pedirse para una TIM o camión puntual (ej. *"¿qué mercadería lleva la TIM 676169276?"*). 
   * Si pides *"dame todos los productos enviados a la tienda 123 en el mes"*, el agente te pedirá acotar la búsqueda porque son decenas de miles de filas.
5. **Restricción de Alcance (Guardrails):**
   * El agente **rechaza cortésmente** preguntas ajenas a Tottus Perú: cálculos matemáticos escolares (ej. *"25 * 25"*), programación, recetas, poemas o chistes.

---

## 💬 4. Catálogo de Preguntas que Puedes Hacerle

### A. Consultas con DATA REAL de BigQuery

#### Despachos y Llegadas a Tienda (Requiere Fecha o Tienda)
* *"¿Cuántos camiones llegaron hoy a mi tienda?"*
* *"¿Cuántos camiones llegaron ayer a la tienda 123 de Angamos?"*
* *"¿Cuántos camiones están en camino hacia la tienda 451 de Huánuco?"*
* *"¿Qué camiones se despacharon a la tienda 107 el día 20 de septiembre?"*
* *"¿Cuántas transferencias (TIMs) salieron a Atocongo entre el 01 y el 03 de octubre?"*

#### Camiones Pendientes de Envío en CD (Patio/Andén)
* *"¿Hay camiones que se encuentren cargados en el CD pero que no se hayan enviado hasta el día de hoy?"*
* *"¿Hay camiones cargados que no tengan fecha de envío?"*
* *"¿Tiene la placa BFX756 alguna carga pendiente de despacho en patio?"*

#### Detalle de Mercadería y SKUs (Requiere TIM o Placa)
* *"¿Qué mercadería está trayendo la TIM 676169276?"*
* *"Necesito la lista de productos de la TIM 655429144."*
* *"¿Qué productos o artículos lleva el camión de placa Z3H976?"*

#### Hora de Carga en CD
* *"¿Cuándo se cargó la TIM 655428906?"*
* *"¿A qué hora terminó de cargar la transferencia 655423810?"*

#### Rastreo por Shipment o Delivery Order (DO)
* *"Rastrea el despacho con Shipment 6760115785."*
* *"¿Qué camión transporta la DO 519321996?"*

#### Despachos por División Comercial y Alertas
* *"Dame el resumen de despachos por división comercial para la tienda 123 de los últimos 7 días."*
* *"¿Hay alertas de productos próximos a vencer en tránsito hacia mi tienda?"*

---

### B. Consultas con DATA REAL de SharePoint / Excel en Vivo (Provincia y Oriente)

*Estas preguntas consultan la herramienta `consultar_monitoreo_provincia` sobre el archivo sincronizado de SharePoint (`Monitoreo General UT Provincia 2030.xlsx`, hoja `Perú`, `Tabla3`).*

> **⚠️ Alcance Geográfico:** Exclusivo para tiendas de **Provincia (`3xx`)** y **Oriente / Selva (`4xx`, ej. 451 Huánuco, 474 Pucallpa)**. No aplica para tiendas locales de Lima/Callao (`1xx`).

#### Lógica Inteligente de Viaje COMPARTIDO vs ÚNICO (Campo `PUNTO`):
* El campo `PUNTO` indica el **orden secuencial de paradas de la unidad** (Punto 1 = primera parada, Punto 2 = segunda, Punto 3 = tercera).
* **Validación de Viaje (Umbral de 2 horas en `FIN DE CARGA`):** El sistema agrupa todas las transferencias asociadas a la misma placa/tracto cuyo `FIN DE CARGA` esté dentro de una ventana de **±2 horas** (ej. entre 08:05 y 12:05 para una carga de las 10:05).
* **Respuesta en el Chat:**
  * Indica si es **Carga ÚNICA** (1 solo punto) o **Carga COMPARTIDA** (múltiples puntos).
  * Muestra la **ruta programada completa**: `1° Tienda 352 ➔ 2° Tienda 356 ➔ 3° Tienda 391`.
  * Aclara si el camión descargará **primero la TIM consultada** o si visitará otra tienda previamente.

#### Preguntas modelo:
* *"¿En dónde se encuentra el camión de la TIM 676169276?"* $\rightarrow$ *(Indica ubicación en vivo, si es compartido/único y el orden de paradas).*
* *"¿Cuál es la ubicación actual del camión de placa A0B981?"*
* *"¿El viaje de la TIM 80071667 es carga compartida o única? ¿A qué tiendas va?"*
* *"¿Dónde está el tracto AME860?"*
* *"¿A qué hora salió a ruta el camión de la TIM 676169276?"*
* *"¿El camión de la TIM 676169276 tiene alguna incidencia o motivo reportado?"* $\rightarrow$ *(Responde `SIN OBSERVACION` o el percance registrado).*
* *"¿El camión ya llegó a tienda o sigue esperando descarga?"*

---

### C. Consultas con DATA IMAGINARIA / PROTOTIPO (Reprogramaciones OC)

*Estas preguntas usan un número de orden de compra inventado para probar el flujo de atención al cliente:*

1. Paso 1 (Iniciar flujo):
   * *"Quiero realizar una reprogramación"* o *"Reprogramaciones"*.
   * *(El agente te responderá: "Indícame el estado del pedido o envíame la OC del pedido")*.
2. Paso 2 (Ingresar OC inventada):
   * *"Mi OC es la 123456, ¿cuál es el estado?"*
   * *(El agente acepta el número inventado y te informa un estado simulado, por ejemplo que tuvo una excepción de entrega)*.
3. Paso 3 (Resolver la causal):
   * *"Fue por cliente ausente"* $\rightarrow$ *(Te dirá el plazo de reprogramación automática: 48h local / 72h provincia)*.
   * *"Fue por dirección incorrecta"* $\rightarrow$ *(Te indicará el enlace de SharePoint para subir el formato y asunto del correo)*.
   * *"Fue por fuera de horario"* $\rightarrow$ *(Te indicará la acción requerida oficial)*.
