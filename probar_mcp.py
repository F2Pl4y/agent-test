import urllib.request
import json

URL = "http://localhost:5001/mcp"

def consultar_pagina(tim: int, pagina: int = 1):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "consultar_despachos_logistica",
            "arguments": {
                "tim": tim,
                "pagina": int(pagina)
            }
        }
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
                filas.append(json.loads(texto))
            except Exception:
                print(f"⚠️ Mensaje de BigQuery: {texto}")
                return []
                
        return filas

print("\n⏳ Consultando BigQuery a través de Toolbox MCP (Paginación por Página)...\n")

todas_las_filas = []
num_pagina = 1

while True:
    print(f"📥 Descargando Página #{num_pagina}...")
    filas_lote = consultar_pagina(tim=655423616, pagina=num_pagina)
    
    if not filas_lote:
        break
        
    todas_las_filas.extend(filas_lote)
    print(f"   ↳ Se recibieron {len(filas_lote)} registros.")
    
    # Si la página trajo menos de 50 registros, significa que ya es la última página
    if len(filas_lote) < 50:
        break
        
    num_pagina += 1

if todas_las_filas:
    print(f"\n🎉 ¡Consulta Completa Finalizada!")
    print(f"📊 TOTAL ABSOLUTO DE FILAS RECUPERADAS: {len(todas_las_filas)} registros\n")
    print("=" * 130)
    print(f"{'#':<4} | {'TIM':<10} | {'SHIPMENT':<10} | {'SKU':<10} | {'DESCRIPCIÓN':<40} | {'TRF_DO':<10} | {'TIPO':<6} | {'WHSE':<6} | {'TIENDA':<16} | {'FECHA'}")
    print("=" * 130)
    
    for i, f in enumerate(todas_las_filas, 1):
        desc = (f.get('Descripcion') or '')
        tienda = f"{f.get('Nombre_Tienda') or ''} ({f.get('Tienda') or ''})"
        print(f"{i:<4} | {f.get('tim', ''):<10} | {f.get('Shipment', ''):<10} | {f.get('sku', ''):<10} | {desc:<40} | {f.get('Trf_DO', ''):<10} | {f.get('Tipo_DO', ''):<6} | {f.get('Inventario_Whse', ''):<6} | {tienda:<16} | {f.get('Fecha_Enviado', '')}")
        
    print("=" * 130)
else:
    print("ℹ️ No se pudieron recuperar registros.")