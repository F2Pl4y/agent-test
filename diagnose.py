import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import settings
from backend.agents.logistica.agent import agente_logistica

async def test():
    print(f"DEBUG: GEMINI_API_KEY = {settings.GEMINI_API_KEY[:8]}...{settings.GEMINI_API_KEY[-4:] if settings.GEMINI_API_KEY else 'EMPTY'}")
    print(f"DEBUG: USE_VERTEXAI = {settings.USE_VERTEXAI}")
    print(f"DEBUG: GEMINI_MODEL = {settings.GEMINI_MODEL}")
    
    prompt = "Hola, necesito saber qué camion llevo a la TIM 655423616"
    print(f"\n--- Probando prompt: '{prompt}' ---")
    try:
        client = agente_logistica._get_client()
        from google.genai import types
        tools = agente_logistica._build_tools_declaration()
        config = types.GenerateContentConfig(
            system_instruction="Eres el asistente oficial de logistica.",
            tools=tools,
            temperature=0.0
        )
        print("Llamando a Gemini Turno 1...")
        resp, model = await agente_logistica._generate_content_with_retry(
            client=client,
            contents=prompt,
            config=config,
            primary_model=settings.GEMINI_MODEL
        )
        print(f"Turno 1 exitoso con modelo: {model}")
        print(f"Function calls: {resp.function_calls}")
        if resp.function_calls:
            fc = resp.function_calls[0]
            print(f"Tool llamada: {fc.name} con args: {fc.args}")
            # Ejecutar la tool
            from backend.agents._shared.loader import mcp_client
            rows = await mcp_client.call_tool(fc.name, fc.args)
            print(f"Filas obtenidas: {len(rows)}")
            
            # Probar Turno 2 / 3
            tool_resp = types.Part.from_function_response(
                name=fc.name,
                response={"result": {"total_filas": len(rows), "muestra": rows[:5]}}
            )
            tool_role = "tool" if settings.USE_VERTEXAI else "user"
            contents_t2 = [
                types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
                resp.candidates[0].content,
                types.Content(role=tool_role, parts=[tool_resp])
            ]
            print("Llamando a Gemini Turno 3...")
            resp2, model2 = await agente_logistica._generate_content_with_retry(
                client=client,
                contents=contents_t2,
                config=types.GenerateContentConfig(tools=tools),
                primary_model=model
            )
            print(f"Turno 3 exitoso con modelo: {model2}!")
            print(f"Respuesta final de Gemini:\n{resp2.text}")
        else:
            print(f"Respuesta directa sin tools:\n{resp.text}")
    except Exception as e:
        print("\n❌ EXCEPCIÓN DETECTADA:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
