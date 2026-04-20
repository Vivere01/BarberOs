import asyncio
import sys
from src.agent.full_engine import create_full_brain, set_session_context
from langchain_core.messages import HumanMessage
from src.config.logging_config import get_logger

logger = get_logger("tester")

async def test_helena():
    """
    Script de teste para validar a criação e resposta de um Agente IA
    na arquitetura de Fábrica de Agentes BarberOS.
    """
    print("\n" + "="*50)
    print(" BARBEROS - TESTE DE AGENTE IA (HELENA)")
    print("="*50)

    # --- CONFIGURAÇÃO DO AGENTE (MULTI-TENANT) ---
    # Aqui você simula o que o seu sistema enviaria para criar este agente
    PRO_API_KEY = "cmn90566j0000uaj5aouwhwtn" # Token que você me mandou
    INSTANCE_EVO = "dev-owner-1774622040714" # ID que você me mandou
    PERSONA = "Você é a Helena, assistente virtual da barbearia Navalha & Estilo. Seja educada e foque em ajudar com agendamentos."

    brain = create_full_brain()
    
    # 1. Injeta o Contexto da Barbearia (Configura os canais PRO e Evolution)
    set_session_context(
        pro_api_key=PRO_API_KEY,
        instance_name=INSTANCE_EVO,
        metadata={"persona": PERSONA}
    )

    # 2. Simula uma mensagem de um cliente
    msg_cliente = "Oi! Queria ver os preços e horários para hoje."
    print(f"\nCliente: {msg_cliente}")
    print("Helena está processando...")

    input_state = {
        "messages": [HumanMessage(content=msg_cliente)],
        "conversation_id": "test_user_123",
        "barbershop_id": INSTANCE_EVO,
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
        "metadata": {"persona": PERSONA}
    }

    try:
        config = {"configurable": {"thread_id": "test_user_123"}}
        result = await brain.ainvoke(input_state, config=config)
        
        resposta_final = result["messages"][-1].content
        print(f"\n RESPOSTA DA HELENA:\n{resposta_final}")
        print("\n" + "="*50)
        
    except Exception as e:
        print(f"\n❌ ERRO NO TESTE: {str(e)}")
        print("Certifique-se de que configurou as chaves no seu ambiente.")

if __name__ == "__main__":
    asyncio.run(test_helena())
