"""
BarberOS API - Brain Node
==========================
Recebe: Mensagem + Contexto (Scraping) do N8N
Retorna: Resposta inteligente validada
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
    barbershop_context: Optional[Any] = None # O N8N manda os dados do scraping aqui

@router.post("/chat")
async def process_chat(request: ChatInput):
    # Usamos o telefone como thread_id para manter a memória da conversa
    config = {"configurable": {"thread_id": request.phone}}
    
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "context_data": request.barbershop_context, # Passa o scraping pro cérebro
        "needs_human": False
    }
    
    # Roda o LangGraph
    final_state = await brain.ainvoke(input_state, config=config)
    last_message = final_state["messages"][-1]
    
    return {
        "response": last_message.content,
        "needs_human": final_state.get("needs_human", False)
    }
