import urllib.request
import json

URL = "http://localhost:5001/mcp"

def consultar_pagina(tim: int, offset: int = 0):
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "consultar_despachos_logistica",
            "arguments": {
                "tim": tim,
                "offset": int(offset)
            }
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    
    with urllib.request.urlopen(req) as response:
        resultado = json.loads(response.read().decode("utf-8"))
        
        # Validación de errores a nivel de protocolo MCP
        if "error" in resultado:
            print(f"❌ Error devuelto por el servidor: {resultado['error']}")
            return []
            
        contenido = resultado.get("result", {}).get("content", [])
        filas = []
        for item in contenido:
            texto = item.get("text", "{}")
            try:
                filas.append(json.loads(texto))
            except Exception:
                # Si el texto no es JSON, BigQuery envió un mensaje de error
                print(f"⚠️ Mensaje de BigQuery/Toolbox: {texto}")
                return []
                
        return filas

print("\n⏳ Consultando BigQuery a través de Toolbox MCP con Paginación...\n")

todas_las_filas = []
offset_actual = 0
numero_pagina = 1

while True:
    print(f"📥 Descargando Lote #{numero_pagina} (registros desde el {offset_actual})...")
    filas_lote = consultar_pagina(tim=655425244, offset=offset_actual)
    
    if not filas_lote:
        break
        
    todas_las_filas.extend(filas_lote)
    print(f"   ↳ Se recibieron {len(filas_lote)} registros.")
    
    # Si el lote trajo menos de 50 registros, significa que ya es la última página
    if len(filas_lote) < 50:
        break
        
    offset_actual += 50
    numero_pagina += 1

if todas_las_filas:
    print(f"\n🎉 ¡Paginación completada con éxito!")
    print(f"📊 TOTAL ABSOLUTO DE FILAS RECUPERADAS: {len(todas_las_filas)} registros\n")
    print(f"• Primer registro (#1): {todas_las_filas[0].get('sku')} | {todas_las_filas[0].get('Descripcion')}")
    if len(todas_las_filas) > 50:
        print(f"• Registro intermedio (#51): {todas_las_filas[50].get('sku')} | {todas_las_filas[50].get('Descripcion')}")
    print(f"• Último registro (#{len(todas_las_filas)}): {todas_las_filas[-1].get('sku')} | {todas_las_filas[-1].get('Descripcion')}\n")
else:
    print("ℹ️ No se pudieron recuperar registros.")