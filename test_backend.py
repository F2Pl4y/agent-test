import asyncio
import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en el path de Python
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.agents._shared.loader import mcp_client
from backend.agents.logistica.agent import agente_logistica

async def main():
    print("=" * 80)
    print("🧪 PRUEBA DE CONECTIVIDAD Y FUNCIONAMIENTO DEL BACKEND")
    print("=" * 80)

    # 1. Probar conectividad con Toolbox MCP
    print("\n1️⃣ Verificando conexión con Toolbox MCP (puerto 5001)...")
    is_up = await mcp_client.check_health()
    if is_up:
        print("   ✅ Toolbox MCP está ACTIVO y respondiendo.")
        tools = await mcp_client.list_tools()
        print(f"   📋 Herramientas detectadas ({len(tools)}): {[t.get('name') for t in tools]}")
    else:
        print("   ❌ No se pudo conectar a Toolbox MCP. Verifica que 'toolbox.exe' esté corriendo en la otra terminal.")
        return

    # 2. Probar ejecución del Agente con una consulta logística real
    tim_prueba = 655423616
    pregunta = f"¿Qué productos y mercadería se despacharon en el TIM {tim_prueba}?"
    print(f"\n2️⃣ Enviando consulta al Agente Logístico: '{pregunta}'...")
    
    response = await agente_logistica.run(user_prompt=pregunta)

    print("\n" + "=" * 80)
    print("🤖 RESPUESTA GENERADA POR EL AGENTE:")
    print("=" * 80)
    print(response.answer)
    print("\n" + "-" * 80)
    print(f"📊 Herramientas MCP invocadas: {len(response.tools_executed)}")
    for t in response.tools_executed:
        print(f"   ↳ Herramienta: {t.tool_name} | Argumentos: {t.arguments} | Registros obtenidos: {t.result_count}")
    
    total_filas = len(response.data) if response.data else 0
    print(f"📦 Total de filas de datos estructurados para el Frontend: {total_filas} registros")
    print("=" * 80)
    print("🎉 ¡Prueba de backend completada exitosamente!")

if __name__ == "__main__":
    asyncio.run(main())
