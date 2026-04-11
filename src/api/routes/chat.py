"""
BarberOS API - Brain Node Entry Point
======================================
Este arquivo conecta o seu N8N ao cérebro LangGraph.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from src.agent.full_engine import create_full_brain
from langchain_core.messages import HumanMessage
import uuid

router = APIRouter()
brain = create_full_brain() # Inicializa o cérebro com memória

class N8NRequest(BaseModel):
    message: str
    phone: str
    barbershop_id: str

@router.post("/chat")
async def process_chat(request: N8NRequest):
    """
    O seu N8N chama este endpoint.
    Ele processa, usa ferramentas, valida e responde.
    """
    # Configuramos o ID da conversa (Memória persistente do LangGraph)
    config = {"configurable": {"thread_id": request.phone}}
    
    # Input para o Grafo
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "customer_phone": request.phone,
        "barbershop_id": request.barbershop_id,
        "needs_human": False
    }
    
    # EXECUÇÃO DO GRAFO (Aqui acontece a mágica: Classificação, Tool Use, Validação)
    # O brain.invoke vai rodar quantos nós forem necessários antes de retornar.
    final_state = await brain.ainvoke(input_state, config=config)
    
    # Pegamos a última mensagem do AI
    last_message = final_state["messages"][-1]
    
    return {
        "response": last_message.content,
        "needs_human": final_state.get("needs_human", False),
        "intent": final_state.get("current_intent", "chat"),
        "debug_trace": "Check LangSmith for details" # Se configurado, o trace vai direto pro LangSmith
    }
