"""
BarberOS API - Brain Node
==========================
Recebe: Mensagem + Treinamento (Persona) + Contexto (Scraping)
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
    persona: Optional[str] = None # <-- SEU TREINAMENTO (TOM DE VOZ, REGRAS)
    barbershop_context: Optional[Any] = None # <-- SEU BANCO DE DADOS (PREÇOS, ETC)

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
        "needs_human": final_state.get("needs_human", False)
    }
