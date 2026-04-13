import asyncio
import os
import sys

# Adiciona o diretório atual ao path para importar src
sys.path.append(os.getcwd())

from src.agent.full_engine import create_full_brain
from langchain_core.messages import HumanMessage
from src.config.settings import get_settings

async def test_brain():
    settings = get_settings()
    print(f"DEBUG: Usando modelo {settings.openai_model}")
    print(f"DEBUG: API Key presente: {bool(settings.openai_api_key)}")
    
    brain = create_full_brain()
    
    input_state = {
        "messages": [HumanMessage(content="Olá")],
        "context_data": {
            "persona": "Você é a Ana, assistente virtual da barbearia.", 
            "system_info": {}
        },
        "needs_human": False
    }
    
    config = {"configurable": {"thread_id": "test_phone"}}
    config["recursion_limit"] = 5
    
    try:
        print("Invocando brain...")
        final_state = await brain.ainvoke(input_state, config=config)
        print("Resultado:")
        print(final_state["messages"][-1].content)
    except Exception as e:
        print("\n--- ERRO DETECTADO ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_brain())
