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
    config = {"configurable": {"thread_id": request.phone}}
    
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "context_data": {
            "persona": request.persona, 
            "system_info": request.barbershop_context
        },
        "needs_human": False
    }
    
    final_state = await brain.ainvoke(input_state, config=config)
    last_message = final_state["messages"][-1]
    
    return {
        "response": last_message.content,
        "intent": final_state.get("intent"), # Aqui vem o sinal para o N8N disparar o POST
        "needs_human": final_state.get("needs_human", False)
    }
