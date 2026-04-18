
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

    # ★ Simula contexto Evolution e PRO
    set_session_context(
        pro_api_key="TEST_PRO_KEY",
        instance_name="CONTATO_TESTE",
        evolution_apikey="TEST_EVO_KEY",
        phone="5511999999999"
    )

    input_state = {
        "messages": [HumanMessage(content="Oi! Quais são os preços?")],
        "conversation_id": "5511999999999",
        "barbershop_id": "CONTATO_TESTE",
        "system_type": "pro",
        "client_info": {"phone": "5511999999999"},
        "current_intent": "unknown",
        "intent_confidence": 0.0,
        "previous_intents": [],
        "conversation_stage": "initial",
        "turn_count": 0,
        "appointment_request": {},
        "scheduling_data": {},
        "agent_response": "",
        "response_type": "text",
        "guardrail_result": {},
        "errors": [],
        "last_error": {},
        "retrieved_knowledge": [],
        "metadata": {"persona": "Você é a Ana, assistente virtual da barbearia."}
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
