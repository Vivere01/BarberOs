"""
BarberOS API - Brain Node
==========================
Devolve Resposta + Intenções Estruturadas
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any
from src.agent.full_engine import create_full_brain
from langchain_core.messages import HumanMessage

router = APIRouter()
brain = create_full_brain()

class ChatInput(BaseModel):
    message: str
    phone: str
    persona: Optional[str] = None
    barbershop_context: Optional[Any] = None

@router.post("/chat")
async def process_chat(request: ChatInput):
    # Log para diagnóstico de memória
    print(f"DEBUG: Recebendo mensagem de {request.phone}: {request.message}")
    config = {"configurable": {"thread_id": request.phone}}
    
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "context_data": {
            "persona": request.persona, 
            "system_info": request.barbershop_context
        },
        "needs_human": False
    }
    
    # Limite de recurção ultra-baixo para forçar falha rápida em caso de loop
    config["recursion_limit"] = 5
    
    try:
        final_state = await brain.ainvoke(input_state, config=config)
        last_message = final_state["messages"][-1]
        
        return {
            "response": last_message.content,
            "intent": final_state.get("intent"),
            "needs_human": final_state.get("needs_human", False)
        }
    except Exception as e:
        print(f"ERRO CRÍTICO NO AGENTE: {str(e)}")
        return {
            "response": "Desculpe, tive um problema técnico momentâneo. Pode repetir ou aguardar um instante?",
            "intent": "error",
            "needs_human": True
        }
