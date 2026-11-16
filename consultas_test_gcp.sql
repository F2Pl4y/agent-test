-- ==============================================================================
-- CONSULTAS DE PRUEBA EN GOOGLE BIGQUERY (GCP BigQuery Studio)
-- Proyecto: tot-corp-plo-sbx
-- Tabla PE: tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS
-- Tabla CL: tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS
--
-- INSTRUCCIONES EN GCP BIGQUERY STUDIO:
-- Selecciona un bloque completo (desde su DECLARE hasta el END IF;) y haz clic
-- en "RUN SELECTED" para probar cada herramienta MCP de forma independiente.
-- ==============================================================================


-- ==============================================================================
-- TEST 1: consultar_despachos_logistica (Detalle fino de productos / SKUs)
-- Prueba buscando por TIM específico o por tienda / '*' (toda la cadena)
-- ==============================================================================
DECLARE t1_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t1_tim INT64 DEFAULT 0;                    -- Ej: 655423616 (0 = todos)
DECLARE t1_tienda STRING DEFAULT '123';            -- Ej: '123' Angamos, o '__ALL_TIENDA__' / '*' para todas
DECLARE t1_sku STRING DEFAULT '';                  -- Ej: '20001234' ('' = todos)
DECLARE t1_placa STRING DEFAULT '';                -- Ej: 'BHL888' ('' = todas)

IF UPPER(COALESCE(NULLIF(TRIM(t1_pais), ''), 'PE')) = 'PE' THEN
  SELECT
      'PE' AS pais,
      tim,
      Shipment,
      Placa,
      sku,
      Descripcion,
      Trf_DO,
      Tipo_DO,
      Inventario_Whse,
      Tienda,
      Nombre_Tienda,
      Fecha_Enviado,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', Hora_de_Carga) AS hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 1 DAY)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 2 DAY)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 3 DAY)
        ELSE DATE_ADD(DATE(Fecha_Enviado), INTERVAL 4 DAY)
      END AS fecha_estimada_llegada
  FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL 31 DAY)
    AND Fecha_Enviado <= CURRENT_DATE("America/Lima")
    AND (t1_tim = 0 OR Tim = t1_tim)
    AND (UPPER(TRIM(t1_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t1_tienda))
    AND (TRIM(t1_sku) = '' OR CAST(sku AS STRING) = TRIM(t1_sku))
    AND (TRIM(t1_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t1_placa)))
  ORDER BY Fecha_Enviado DESC, sku
  LIMIT 500;
ELSEIF UPPER(TRIM(t1_pais)) = 'CL' THEN
  SELECT
      'CL' AS pais,
      tim,
      Shipment,
      Placa,
      sku,
      Descripcion,
      Trf_DO,
      Tipo_DO,
      Inventario_Whse,
      Tienda,
      Nombre_Tienda,
      Fecha_Enviado,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', Hora_de_Carga) AS hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 1 DAY)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 2 DAY)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN DATE_ADD(DATE(Fecha_Enviado), INTERVAL 3 DAY)
        ELSE DATE_ADD(DATE(Fecha_Enviado), INTERVAL 4 DAY)
      END AS fecha_estimada_llegada
  FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL 31 DAY)
    AND Fecha_Enviado <= CURRENT_DATE("America/Santiago")
    AND (t1_tim = 0 OR Tim = t1_tim)
    AND (UPPER(TRIM(t1_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t1_tienda))
    AND (TRIM(t1_sku) = '' OR CAST(sku AS STRING) = TRIM(t1_sku))
    AND (TRIM(t1_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t1_placa)))
  ORDER BY Fecha_Enviado DESC, sku
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t1_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 2: resumen_carga_transporte (Consolidado por Camión / TIM)
-- Prueba con tienda puntual ('123') o comodín global ('*') y rango de fechas
-- ==============================================================================
DECLARE t2_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t2_tim INT64 DEFAULT 0;                    -- Ej: 655425244 (0 = todos)
DECLARE t2_placa STRING DEFAULT '';                -- Ej: 'BHL888' ('' = todas)
DECLARE t2_tienda STRING DEFAULT '*';              -- Ej: '123' o '*' / 'TODAS' / '__ALL_TIENDA__'
DECLARE t2_fecha STRING DEFAULT '';                -- Ej: '2026-11-10' ('' = últimos 31 días)
DECLARE t2_fecha_fin STRING DEFAULT '';            -- Ej: '2026-11-15' ('' = fecha única)

IF UPPER(COALESCE(NULLIF(TRIM(t2_pais), ''), 'PE')) = 'PE' THEN
  WITH datos AS (
    SELECT
        'PE' AS pais,
        tim,
        Placa,
        Tienda,
        Nombre_Tienda,
        Inventario_Whse,
        DATE(Fecha_Enviado) AS fecha_despacho,
        FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
        COUNT(DISTINCT Pallet) AS total_pallets,
        COUNT(DISTINCT sku) AS total_skus_distintos,
        ROUND(SUM(Unidades), 0) AS total_unidades,
        ROUND(SUM(Cajas), 0) AS total_cajas,
        ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
        ROUND(SUM(Vol_Enviado), 2) AS volumen_total_m3
    FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
    WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL 31 DAY)
      AND (t2_tim = 0 OR Tim = t2_tim)
      AND (TRIM(t2_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t2_placa)))
      AND (UPPER(TRIM(t2_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t2_tienda))
      AND (
        TRIM(t2_fecha) = ''
        OR (TRIM(t2_fecha_fin) != '' AND DATE(Fecha_Enviado) >= SAFE_CAST(TRIM(t2_fecha) AS DATE) AND DATE(Fecha_Enviado) <= SAFE_CAST(TRIM(t2_fecha_fin) AS DATE))
        OR (TRIM(t2_fecha_fin) = '' AND (
             CAST(DATE(Fecha_Enviado) AS STRING) = TRIM(t2_fecha)
             OR CAST(DATE(Fecha_Enviado) AS STRING) LIKE CONCAT('%', TRIM(t2_fecha), '%')
        ))
      )
    GROUP BY tim, Placa, Tienda, Nombre_Tienda, Inventario_Whse, DATE(Fecha_Enviado)
  )
  SELECT
      pais,
      tim,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      fecha_despacho,
      hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '1') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 24 HOUR))
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '3') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 48 HOUR))
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '4') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 72 HOUR))
        WHEN hora_carga IS NOT NULL THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 96 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 1 DAY) AS STRING)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 2 DAY) AS STRING)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 3 DAY) AS STRING)
        ELSE CAST(DATE_ADD(fecha_despacho, INTERVAL 4 DAY) AS STRING)
      END AS fecha_estimada_llegada,
      total_pallets,
      total_skus_distintos,
      total_unidades,
      total_cajas,
      peso_total_kg,
      volumen_total_m3
  FROM datos
  ORDER BY fecha_despacho DESC, hora_carga DESC, total_cajas DESC
  LIMIT 500;
ELSEIF UPPER(TRIM(t2_pais)) = 'CL' THEN
  WITH datos AS (
    SELECT
        'CL' AS pais,
        tim,
        Placa,
        Tienda,
        Nombre_Tienda,
        Inventario_Whse,
        DATE(Fecha_Enviado) AS fecha_despacho,
        FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
        COUNT(DISTINCT Pallet) AS total_pallets,
        COUNT(DISTINCT sku) AS total_skus_distintos,
        ROUND(SUM(Unidades), 0) AS total_unidades,
        ROUND(SUM(Cajas), 0) AS total_cajas,
        ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
        ROUND(SUM(Vol_Enviado), 2) AS volumen_total_m3
    FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
    WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL 31 DAY)
      AND (t2_tim = 0 OR Tim = t2_tim)
      AND (TRIM(t2_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t2_placa)))
      AND (UPPER(TRIM(t2_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t2_tienda))
      AND (
        TRIM(t2_fecha) = ''
        OR (TRIM(t2_fecha_fin) != '' AND DATE(Fecha_Enviado) >= SAFE_CAST(TRIM(t2_fecha) AS DATE) AND DATE(Fecha_Enviado) <= SAFE_CAST(TRIM(t2_fecha_fin) AS DATE))
        OR (TRIM(t2_fecha_fin) = '' AND (
             CAST(DATE(Fecha_Enviado) AS STRING) = TRIM(t2_fecha)
             OR CAST(DATE(Fecha_Enviado) AS STRING) LIKE CONCAT('%', TRIM(t2_fecha), '%')
        ))
      )
    GROUP BY tim, Placa, Tienda, Nombre_Tienda, Inventario_Whse, DATE(Fecha_Enviado)
  )
  SELECT
      pais,
      tim,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      fecha_despacho,
      hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '1') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 24 HOUR))
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '3') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 48 HOUR))
        WHEN hora_carga IS NOT NULL AND STARTS_WITH(CAST(Tienda AS STRING), '4') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 72 HOUR))
        WHEN hora_carga IS NOT NULL THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 96 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 1 DAY) AS STRING)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 2 DAY) AS STRING)
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN CAST(DATE_ADD(fecha_despacho, INTERVAL 3 DAY) AS STRING)
        ELSE CAST(DATE_ADD(fecha_despacho, INTERVAL 4 DAY) AS STRING)
      END AS fecha_estimada_llegada,
      total_pallets,
      total_skus_distintos,
      total_unidades,
      total_cajas,
      peso_total_kg,
      volumen_total_m3
  FROM datos
  ORDER BY fecha_despacho DESC, hora_carga DESC, total_cajas DESC
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t2_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 3: resumen_despachos_por_division (Despachos por División Comercial)
-- ==============================================================================
DECLARE t3_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t3_tienda STRING DEFAULT '123';            -- Ej: '123' o '*' / 'TODAS' para consolidado global
DECLARE t3_dias_atras INT64 DEFAULT 7;             -- Por defecto 7 días

IF UPPER(COALESCE(NULLIF(TRIM(t3_pais), ''), 'PE')) = 'PE' THEN
  SELECT
      'PE' AS pais,
      Division,
      COUNT(DISTINCT sku) AS total_skus,
      ROUND(SUM(Unidades), 0) AS total_unidades,
      ROUND(SUM(Cajas), 0) AS total_cajas,
      ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
      COUNT(DISTINCT tim) AS total_envios_tim
  FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL COALESCE(NULLIF(t3_dias_atras, 0), 7) DAY)
    AND (UPPER(TRIM(t3_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t3_tienda))
  GROUP BY Division
  ORDER BY total_unidades DESC
  LIMIT 500;
ELSEIF UPPER(TRIM(t3_pais)) = 'CL' THEN
  SELECT
      'CL' AS pais,
      Division,
      COUNT(DISTINCT sku) AS total_skus,
      ROUND(SUM(Unidades), 0) AS total_unidades,
      ROUND(SUM(Cajas), 0) AS total_cajas,
      ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
      COUNT(DISTINCT tim) AS total_envios_tim
  FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL COALESCE(NULLIF(t3_dias_atras, 0), 7) DAY)
    AND (UPPER(TRIM(t3_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t3_tienda))
  GROUP BY Division
  ORDER BY total_unidades DESC
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t3_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 4: alertas_vencimiento_transito (Control Preventivo de Perecibles)
-- ==============================================================================
DECLARE t4_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t4_tienda STRING DEFAULT '*';              -- Ej: '123' o '*' para toda la cadena
DECLARE t4_dias_margen INT64 DEFAULT 15;           -- Por defecto 15 días

IF UPPER(COALESCE(NULLIF(TRIM(t4_pais), ''), 'PE')) = 'PE' THEN
  SELECT
      'PE' AS pais,
      Tienda,
      Nombre_Tienda,
      sku,
      Descripcion,
      Division,
      Fecha_Vencimiento,
      DATE_DIFF(Fecha_Vencimiento, CURRENT_DATE("America/Lima"), DAY) AS dias_para_vencer,
      Unidades,
      Cajas,
      tim,
      Placa,
      Fecha_Enviado
  FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL 15 DAY)
    AND (UPPER(TRIM(t4_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t4_tienda))
    AND Fecha_Vencimiento IS NOT NULL
    AND Fecha_Vencimiento <= DATE_ADD(CURRENT_DATE("America/Lima"), INTERVAL COALESCE(NULLIF(t4_dias_margen, 0), 15) DAY)
  ORDER BY Fecha_Vencimiento ASC
  LIMIT 500;
ELSEIF UPPER(TRIM(t4_pais)) = 'CL' THEN
  SELECT
      'CL' AS pais,
      Tienda,
      Nombre_Tienda,
      sku,
      Descripcion,
      Division,
      Fecha_Vencimiento,
      DATE_DIFF(Fecha_Vencimiento, CURRENT_DATE("America/Santiago"), DAY) AS dias_para_vencer,
      Unidades,
      Cajas,
      tim,
      Placa,
      Fecha_Enviado
  FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL 15 DAY)
    AND (UPPER(TRIM(t4_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t4_tienda))
    AND Fecha_Vencimiento IS NOT NULL
    AND Fecha_Vencimiento <= DATE_ADD(CURRENT_DATE("America/Santiago"), INTERVAL COALESCE(NULLIF(t4_dias_margen, 0), 15) DAY)
  ORDER BY Fecha_Vencimiento ASC
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t4_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 5: buscar_por_shipment_o_do (Rastreo por Shipment o Delivery Order)
-- ==============================================================================
DECLARE t5_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t5_shipment STRING DEFAULT '';             -- Ej: '90327449' ('' = todos)
DECLARE t5_trf_do STRING DEFAULT '';               -- Ej: '22796787' ('' = todos)

IF UPPER(COALESCE(NULLIF(TRIM(t5_pais), ''), 'PE')) = 'PE' THEN
  SELECT
      'PE' AS pais,
      tim,
      Shipment,
      Trf_DO,
      Tipo_DO,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
      DATE(Fecha_Enviado) AS fecha_despacho,
      COUNT(DISTINCT sku) AS total_skus,
      ROUND(SUM(Unidades), 0) AS total_unidades,
      ROUND(SUM(Cajas), 0) AS total_cajas,
      ROUND(SUM(Peso_Total), 2) AS peso_total_kg
  FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL 31 DAY)
    AND (TRIM(t5_shipment) = '' OR CAST(Shipment AS STRING) = TRIM(t5_shipment))
    AND (TRIM(t5_trf_do) = '' OR CAST(Trf_DO AS STRING) = TRIM(t5_trf_do))
  GROUP BY tim, Shipment, Trf_DO, Tipo_DO, Placa, Tienda, Nombre_Tienda, Inventario_Whse, DATE(Fecha_Enviado)
  LIMIT 500;
ELSEIF UPPER(TRIM(t5_pais)) = 'CL' THEN
  SELECT
      'CL' AS pais,
      tim,
      Shipment,
      Trf_DO,
      Tipo_DO,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
      DATE(Fecha_Enviado) AS fecha_despacho,
      COUNT(DISTINCT sku) AS total_skus,
      ROUND(SUM(Unidades), 0) AS total_unidades,
      ROUND(SUM(Cajas), 0) AS total_cajas,
      ROUND(SUM(Peso_Total), 2) AS peso_total_kg
  FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL 31 DAY)
    AND (TRIM(t5_shipment) = '' OR CAST(Shipment AS STRING) = TRIM(t5_shipment))
    AND (TRIM(t5_trf_do) = '' OR CAST(Trf_DO AS STRING) = TRIM(t5_trf_do))
  GROUP BY tim, Shipment, Trf_DO, Tipo_DO, Placa, Tienda, Nombre_Tienda, Inventario_Whse, DATE(Fecha_Enviado)
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t5_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 6: buscar_tienda_por_nombre (Catálogo y Validación de Tiendas)
-- ==============================================================================
DECLARE t6_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t6_nombre_parcial STRING DEFAULT 'Angamos';-- Ej: 'Angamos', '451', o '*' para listar todas

IF UPPER(COALESCE(NULLIF(TRIM(t6_pais), ''), 'PE')) = 'PE' THEN
  SELECT
      'PE' AS pais,
      Tienda AS tienda_id,
      Nombre_Tienda,
      COUNT(DISTINCT tim) AS total_despachos_recientes,
      MAX(Fecha_Enviado) AS ultimo_despacho_registrado
  FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL 31 DAY)
    AND (
      UPPER(TRIM(t6_nombre_parcial)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__')
      OR LOWER(Nombre_Tienda) LIKE CONCAT('%', LOWER(TRIM(t6_nombre_parcial)), '%')
      OR CAST(Tienda AS STRING) = TRIM(t6_nombre_parcial)
    )
  GROUP BY Tienda, Nombre_Tienda
  ORDER BY total_despachos_recientes DESC
  LIMIT 500;
ELSEIF UPPER(TRIM(t6_pais)) = 'CL' THEN
  SELECT
      'CL' AS pais,
      Tienda AS tienda_id,
      Nombre_Tienda,
      COUNT(DISTINCT tim) AS total_despachos_recientes,
      MAX(Fecha_Enviado) AS ultimo_despacho_registrado
  FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
  WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL 31 DAY)
    AND (
      UPPER(TRIM(t6_nombre_parcial)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__')
      OR LOWER(Nombre_Tienda) LIKE CONCAT('%', LOWER(TRIM(t6_nombre_parcial)), '%')
      OR CAST(Tienda AS STRING) = TRIM(t6_nombre_parcial)
    )
  GROUP BY Tienda, Nombre_Tienda
  ORDER BY total_despachos_recientes DESC
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t6_pais, '. Valores permitidos: PE o CL') AS error;
END IF;


-- ==============================================================================
-- TEST 7: consultar_cargas_pendientes_despacho (Cargas con Hora_de_Carga en CD)
-- ==============================================================================
DECLARE t7_pais STRING DEFAULT 'PE';               -- 'PE' o 'CL'
DECLARE t7_tienda STRING DEFAULT '*';              -- Ej: '123' o '*' / 'TODAS' para todas
DECLARE t7_placa STRING DEFAULT '';                -- Ej: 'BFX756' ('' = todas)
DECLARE t7_dias_atras INT64 DEFAULT 15;            -- Por defecto 15 días

IF UPPER(COALESCE(NULLIF(TRIM(t7_pais), ''), 'PE')) = 'PE' THEN
  WITH datos AS (
    SELECT
        'PE' AS pais,
        tim,
        Placa,
        Tienda,
        Nombre_Tienda,
        Inventario_Whse,
        FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
        COUNT(DISTINCT Pallet) AS total_pallets,
        COUNT(DISTINCT sku) AS total_skus_distintos,
        ROUND(SUM(Unidades), 0) AS total_unidades,
        ROUND(SUM(Cajas), 0) AS total_cajas,
        ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
        ROUND(SUM(Vol_Enviado), 2) AS volumen_total_m3
    FROM `tot-corp-plo-sbx.tot_bi_logistica_pe.FT_LOG_SALIDAS`
    WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Lima"), INTERVAL COALESCE(NULLIF(t7_dias_atras, 0), 15) DAY)
      AND Hora_de_Carga IS NOT NULL
      AND (UPPER(TRIM(t7_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t7_tienda))
      AND (TRIM(t7_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t7_placa)))
    GROUP BY tim, Placa, Tienda, Nombre_Tienda, Inventario_Whse
  )
  SELECT
      pais,
      tim,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 24 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 48 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 72 HOUR))
        ELSE FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 96 HOUR))
      END AS fecha_estimada_llegada,
      total_pallets,
      total_skus_distintos,
      total_unidades,
      total_cajas,
      peso_total_kg,
      volumen_total_m3
  FROM datos
  ORDER BY hora_carga DESC
  LIMIT 500;
ELSEIF UPPER(TRIM(t7_pais)) = 'CL' THEN
  WITH datos AS (
    SELECT
        'CL' AS pais,
        tim,
        Placa,
        Tienda,
        Nombre_Tienda,
        Inventario_Whse,
        FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(Hora_de_Carga)) AS hora_carga,
        COUNT(DISTINCT Pallet) AS total_pallets,
        COUNT(DISTINCT sku) AS total_skus_distintos,
        ROUND(SUM(Unidades), 0) AS total_unidades,
        ROUND(SUM(Cajas), 0) AS total_cajas,
        ROUND(SUM(Peso_Total), 2) AS peso_total_kg,
        ROUND(SUM(Vol_Enviado), 2) AS volumen_total_m3
    FROM `tot-corp-plo-sbx.tot_bi_logistica_cl.FT_LOG_SALIDAS`
    WHERE Fecha_Enviado >= DATE_SUB(CURRENT_DATE("America/Santiago"), INTERVAL COALESCE(NULLIF(t7_dias_atras, 0), 15) DAY)
      AND Hora_de_Carga IS NOT NULL
      AND (UPPER(TRIM(t7_tienda)) IN ('', '*', 'TODAS', 'ALL', '__ALL_TIENDA__') OR CAST(Tienda AS STRING) = TRIM(t7_tienda))
      AND (TRIM(t7_placa) = '' OR UPPER(Placa) = UPPER(TRIM(t7_placa)))
    GROUP BY tim, Placa, Tienda, Nombre_Tienda, Inventario_Whse
  )
  SELECT
      pais,
      tim,
      Placa,
      Tienda,
      Nombre_Tienda,
      Inventario_Whse,
      hora_carga,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN 24
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN 48
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN 72
        ELSE 96
      END AS lead_time_horas,
      CASE
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '1') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 24 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '3') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 48 HOUR))
        WHEN STARTS_WITH(CAST(Tienda AS STRING), '4') THEN FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 72 HOUR))
        ELSE FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_ADD(TIMESTAMP(hora_carga), INTERVAL 96 HOUR))
      END AS fecha_estimada_llegada,
      total_pallets,
      total_skus_distintos,
      total_unidades,
      total_cajas,
      peso_total_kg,
      volumen_total_m3
  FROM datos
  ORDER BY hora_carga DESC
  LIMIT 500;
ELSE
  SELECT CONCAT('Código de país no reconocido: ', t7_pais, '. Valores permitidos: PE o CL') AS error;
END IF;
