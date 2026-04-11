"""
BarberOS - Query Node
======================
Responde dúvidas sobre serviços, preços e horários.
Totalmente ancorado nos dados reais do scraping.
"""
from typing import Any, Dict
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.agent.state import AgentState
from src.config.settings import get_settings

async def query_info(state: AgentState) -> Dict[str, Any]:
    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, temperature=0.1)
    
    # Pegamos os dados reais injetados pelo N8N através da nossa API
    real_data = state.get("scheduling_data", {})
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Você é a recepção da barbearia.\n"
            "Use APENAS as informações abaixo para responder o cliente.\n"
            "Se o cliente perguntar algo que não está aqui, diga que não sabe e pergunte se ele quer falar com um humano.\n\n"
            "DADOS REAIS DA BARBEARIA:\n"
            "{real_data}\n\n"
            "Seja amigável e use emojis curtos."
        )),
        ("placeholder", "{messages}")
    ])
    
    chain = prompt | llm
    response = await chain.ainvoke({
        "real_data": str(real_data),
        "messages": state["messages"]
    })
    
    return {"agent_response": response.content}
