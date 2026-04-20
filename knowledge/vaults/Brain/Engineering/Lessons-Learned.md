---
title: Lições Aprendidas e Correções Críticas
tags: ["engineering", "debug", "history"]
---

# 💡 Lições Aprendidas

Registro histórico de problemas complexos resolvidos e decisões de engenharia.

## 🔴 [20/04/2026] Fix: Instabilidade na Confirmação de Agendamento

### O Problema
A IA apresentava "oscilação" (crash capturado no `try/except` do `call_model`) ao tentar confirmar um horário.

### Causa Raiz
1. **Pydantic Validation Fail**: A ferramenta `agendar_horario` exigia estritamente `staff_id` e `store_id`. Se a IA tentasse chamar a ferramenta sem esses campos (ou com campos nulos), o LangGraph falhava antes mesmo da execução da ferramenta.
2. **Tipagem de IDs**: A API do ChatBarber PRO esperava IDs numéricos (int), mas a IA frequentemente passava strings (ex: `"1"`). Isso causava erros 422/400 na API do backend.
3. **Mensagens Órfãs**: O sanitizador de mensagens tinha um bug que removia "ToolMessages" legítimas durante execuções paralelas, causando erro 400 da OpenAI (mensagens fora de ordem).

### Solução Aplicada
- **Tool Robustness**: Parâmetros `staff_id` e `store_id` tornados opcionais na assinatura da ferramenta.
- **Auto-Discovery**: Se os IDs faltarem, a ferramenta tenta descobri-los via `list_stores` e `list_staff`. Se houver apenas uma opção, o sistema preenche automaticamente.
- **Type Casting**: No `ChatBarberProClient`, forcei a conversão de strings numéricas para `int` antes de enviar o payload JSON.
- **Sanitizer Fix**: Ajuste na lógica do Loop de sanitização para preservar ToolMessages ligadas a AIMessages anteriores no histórico.

---

## 🟢 Melhoria: Transcrição de Áudio (Whisper)
- Implementado fallback de transcrição baseada no campo `base64` enviado diretamente pelo webhook da Evolution API, evitando chamadas extras de download de mídia.
