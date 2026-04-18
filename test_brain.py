
import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.agent.full_engine import create_full_brain, set_session_context
from langchain_core.messages import HumanMessage

async def test_brain():
    brain = create_full_brain()
    config = {"configurable": {"thread_id": "test_phone"}}

    # ★ Simula contexto Chatwoot (valores de teste)
    set_session_context(
        api_token="TEST_TOKEN",
        owner_id="TEST_OWNER",
        inbox="INBOX_TESTE",
        contact_id="CONTATO_TESTE",
        conversation_id="CONVERSA_TESTE",
    )

    input_state = {
        "messages": [HumanMessage(content="Vamos testar")],
        "context_data": {
            "persona": "Você é a Ana, assistente virtual da barbearia.",
            "system_info": {"unidades": [{"id": "1", "nome": "Colorado"}]},
            "inbox_do_cliente": "INBOX_TESTE",
            "contact_id": "CONTATO_TESTE",
            "conversation_id": "CONVERSA_TESTE",
        },
        "needs_human": False
    }

    print("Iniciando invoke...")
    try:
        # Usamos wait_for para não travar o teste se demorar demais
        final_state = await asyncio.wait_for(brain.ainvoke(input_state, config=config), timeout=60)
        print("Resposta recebida!")
        print(f"Content: {final_state['messages'][-1].content}")
        print(f"Intent: {final_state.get('intent')}")
    except asyncio.TimeoutError:
        print("TEMPO ESGOTADO: O cérebro demorou mais de 60 segundos para responder.")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    asyncio.run(test_brain())
