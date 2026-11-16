import urllib.request
import json

URL = "http://localhost:5001/mcp"


def consultar_despachos_tim(tim: int, pais: str = "PE"):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "consultar_despachos_logistica",
            "arguments": {
                "pais": pais,
                "tim": int(tim),
                "tienda": "__ALL_TIENDA__",
                "sku": "",
                "placa": "",
            },
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})

    with urllib.request.urlopen(req) as response:
        resultado = json.loads(response.read().decode("utf-8"))

        if "error" in resultado:
            print(f"❌ Error devuelto por el servidor: {resultado['error']}")
            return []

        contenido = resultado.get("result", {}).get("content", [])
        filas = []
        for item in contenido:
            texto = item.get("text", "")
            try:
                parsed = json.loads(texto)
                if isinstance(parsed, list):
                    filas.extend(parsed)
                elif isinstance(parsed, dict):
                    filas.append(parsed)
            except Exception:
                print(f"⚠️ Mensaje de BigQuery: {texto}")
                return []

        return filas


print("\n⏳ Consultando BigQuery a través de Toolbox MCP (mcp_transporte, LIMIT 500)...\n")

todas_las_filas = consultar_despachos_tim(tim=655423616, pais="PE")

if todas_las_filas:
    print(f"🎉 ¡Consulta Completa Finalizada!")
    print(f"📊 TOTAL DE FILAS RECUPERADAS: {len(todas_las_filas)} registros\n")
    print("=" * 130)
    print(f"{'#':<4} | {'PAIS':<4} | {'TIM':<10} | {'SHIPMENT':<10} | {'SKU':<10} | {'DESCRIPCIÓN':<36} | {'TRF_DO':<10} | {'TIENDA':<16} | {'FECHA'}")
    print("=" * 130)

    for i, f in enumerate(todas_las_filas, 1):
        desc = (f.get('Descripcion') or '')[:36]
        tienda = f"{f.get('Nombre_Tienda') or ''} ({f.get('Tienda') or ''})"
        print(f"{i:<4} | {f.get('pais', 'PE'):<4} | {f.get('tim', ''):<10} | {f.get('Shipment', ''):<10} | {f.get('sku', ''):<10} | {desc:<36} | {f.get('Trf_DO', ''):<10} | {tienda:<16} | {f.get('Fecha_Enviado', '')}")

    print("=" * 130)
else:
    print("ℹ️ No se pudieron recuperar registros.")
