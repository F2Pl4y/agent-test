import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import settings
from backend.agents.logistica.agent import agente_logistica

async def test():
    for prompt in [
        "¿En qué camión viaja el Shipment 90327449?",
        "quiero saber cuantos camiones se han ido a la tienda de angamos el dia 26.09"
    ]:
        print(f"\n==========================================")
        print(f"PROBANDO: '{prompt}'")
        print(f"==========================================")
        try:
            res = await agente_logistica.run(user_prompt=prompt)
            print(f"ANSWER:\n{res.answer}")
            print(f"TOOLS EXECUTED: {[t.tool_name for t in res.tools_executed]}")
            for t in res.tools_executed:
                print(f"   -> {t.tool_name} args={t.arguments} count={t.result_count}")
        except Exception as e:
            print("ERROR:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
