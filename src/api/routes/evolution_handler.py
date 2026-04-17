"""
BarberOS - Evolution API Webhook Handler
=========================================
Recebe mensagens do WhatsApp (Evolution) e conecta ao Motor PRO.
Inclui tratamento de áudio, texto, e proteção contra looping.
"""
from fastapi import APIRouter, Request, Query
from typing import Optional
from src.agent.chatbarber_pro_engine import create_pro_brain, set_pro_context, transcribe_audio
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
    if not remote_jid:
        return {"status": "ignored", "reason": "no_remote_jid"}
    
    message = message_data.get("message", {})
    
    # Extrai o texto da mensagem (suporta texto simples e resposta/extended)
    text = (
        message.get("conversation") or 
        message.get("extendedTextMessage", {}).get("text")
    )
    
    # Tratamento de Áudio
    message_type = message_data.get("messageType", "")
    is_audio = "audio" in message_type.lower() or message.get("audioMessage")
    
    if is_audio:
        # Busca recursiva/exaustiva pelo base64 em diferentes versões da Evolution API
        audio_info = message.get("audioMessage", {})
        base64_audio = (
            data.get("base64") or 
            message_data.get("base64") or 
            audio_info.get("base64") or
            message.get("base64")
        )
        
        if base64_audio:
            logger.info(f"EVOLUTION_IN: Áudio recebido ({len(base64_audio)} chars). Iniciando transcrição...")
            transcribed = await transcribe_audio(base64_audio)
            
            if transcribed and transcribed.strip():
                text = transcribed
                logger.info(f"EVOLUTION_AUDIO_TRANSCRITO: {text[:80]}...")
            else:
                logger.warning("EVOLUTION_IN: Transcrição retornou vazio.")
                text = (
                    "[O cliente enviou um áudio que não foi possível transcrever com clareza. "
                    "Peça gentilmente para ele digitar o que deseja.]"
                )
        else:
            logger.warning("EVOLUTION_IN: Áudio recebido, mas sem base64 habilitado no Webhook.")
            text = (
                "[O cliente enviou um áudio, mas a configuração do webhook não enviou o base64. "
                "Peça desculpas gentilmente e peça para ele digitar o que falou no áudio.]"
            )

    if not text:
        return {"status": "ignored", "reason": "no_text_content"}

    logger.info(f"EVOLUTION_IN: From={remote_jid}, Text={text[:80]}...")

    # Define o contexto PRO para as ferramentas do agente
    set_pro_context(api_token=api_token, owner_id=owner_id)
    
    # Extrai telefone limpo do JID (remove @s.whatsapp.net)
    telefone_limpo = remote_jid.split("@")[0]
    
    # Invoca a IA com recursion_limit para evitar loops infinitos
    config = {
        "configurable": {"thread_id": remote_jid},
        "recursion_limit": 25,
    }
    input_state = {
        "messages": [HumanMessage(content=text)],
        "context_data": {
            "owner_id": owner_id,
            "telefone_cliente": telefone_limpo,
        }
    }

    try:
        final_state = await brain_pro.ainvoke(input_state, config=config)
        last_message = final_state["messages"][-1]
        response_text = last_message.content
        
        # Proteção: não envia resposta vazia
        if not response_text or not response_text.strip():
            logger.warning("EVOLUTION_EMPTY_RESPONSE: IA retornou resposta vazia")
            response_text = "Oi! Como posso te ajudar hoje? 😊"

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
        error_msg = str(e)
        logger.error(f"EVOLUTION_HANDLER_ERROR: {error_msg}", exc_info=True)
        
        # Em caso de erro, tenta enviar mensagem amigável para o cliente
        try:
            settings = get_settings()
            evo_client = EvolutionApiClient(
                base_url=settings.evolution_base_url,
                api_key=settings.evolution_api_key,
                instance_name=settings.evolution_instance_name
            )
            await evo_client.send_text(
                number=remote_jid, 
                text="Puxa, deu uma oscilação aqui. Pode repetir o que deseja? 😊"
            )
        except Exception:
            pass  # Se falhar ao enviar a mensagem de erro, ignora silenciosamente
        
        return {"status": "error", "detail": error_msg}
