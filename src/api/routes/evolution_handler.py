"""
BarberOS - Evolution API Webhook Handler
=========================================
Recebe mensagens do WhatsApp (Evolution) e conecta ao Motor PRO.
"""
from fastapi import APIRouter, Request, Query
from typing import Optional
from src.agent.chatbarber_pro_engine import create_pro_brain, set_pro_context
from src.integrations.evolution_api.client import EvolutionApiClient
from src.config.settings import get_settings
from langchain_core.messages import HumanMessage
from src.config.logging_config import get_logger

logger = get_logger("api.evolution_handler")

router = APIRouter()
brain_pro = create_pro_brain()

@router.post("/evolution/webhook")
async def handle_evolution_webhook(
    request: Request,
    owner_id: str = Query(...),
    api_token: str = Query(...)
):
    """
    Recebe o webhook da Evolution API e processa via IA.
    Configuração no Evolution: http://IP:8000/api/v1/evolution/webhook?owner_id=...&api_token=...
    """
    data = await request.json()
    
    # Validação básica do evento Evolution
    event = data.get("event")
    if event != "messages.upsert":
        return {"status": "ignored", "reason": "not_a_message_event"}
    
    message_data = data.get("data", {})
    key = message_data.get("key", {})
    from_me = key.get("fromMe", False)
    
    # Ignora mensagens enviadas pelo próprio bot para evitar looping
    if from_me:
        return {"status": "ignored", "reason": "message_from_me"}
    
    remote_jid = key.get("remoteJid")
    message = message_data.get("message", {})
    
    # Extrai o texto da mensagem (suporta texto simples e resposta/extended)
    text = (
        message.get("conversation") or 
        message.get("extendedTextMessage", {}).get("text")
    )
    
    # Tratamento de Áudio
    message_type = message_data.get("messageType", "")
    if "audio" in message_type.lower() or message.get("audioMessage"):
        audio_info = message.get("audioMessage", {})
        base64_audio = message_data.get("base64") or audio_info.get("base64")
        
        if base64_audio:
            logger.info("EVOLUTION_IN: Recebido áudio base64. Iniciando transcrição...")
            from src.agent.chatbarber_pro_engine import transcribe_audio
            text = await transcribe_audio(base64_audio)
            logger.info(f"EVOLUTION_AUDIO_TRANSCRITO: {text}")
        else:
            logger.warning("EVOLUTION_IN: Áudio recebido, mas sem base64 habilitado no Webhook da Evolution.")
            # Responde pedindo texto se falhar
            text = "Enviou um áudio, mas meu sistema de transcrição não conseguiu ler. Pode escrever, por favor?"

    if not text:
        return {"status": "ignored", "reason": "no_text_content"}

    logger.info(f"EVOLUTION_IN: From={remote_jid}, Text={text[:50]}...")

    # Define o contexto PRO para as ferramentas do agente
    set_pro_context(api_token=api_token, owner_id=owner_id)
    
    # Invoca a IA
    config = {"configurable": {"thread_id": remote_jid}}
    input_state = {
        "messages": [HumanMessage(content=text)],
        "context_data": {
            "owner_id": owner_id,
            "telefone_cliente": remote_jid.split("@")[0],
        }
    }

    try:
        final_state = await brain_pro.ainvoke(input_state, config=config)
        last_message = final_state["messages"][-1]
        response_text = last_message.content

        # Envia de volta para o WhatsApp
        settings = get_settings()
        evo_client = EvolutionApiClient(
            base_url=settings.evolution_base_url,
            api_key=settings.evolution_api_key,
            instance_name=settings.evolution_instance_name
        )
        
        await evo_client.send_text(number=remote_jid, text=response_text)
        
        return {"status": "success", "response_sent": True}
        
    except Exception as e:
        logger.error(f"EVOLUTION_HANDLER_ERROR: {str(e)}")
        return {"status": "error", "detail": str(e)}
