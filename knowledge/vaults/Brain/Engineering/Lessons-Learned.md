# 🛡️ BarberOS Engineering - Lessons Learned (LOCKDOWN)

Este documento registra as soluções definitivas para erros críticos encontrados. 
**REGRAS DE OURO: Não alterar estas lógicas sem verificar este Wiki.**

## 1. Identificação de Clientes (WhatsApp/Fuzzy)
- **Problema**: WhatsApp envia prefixos (55) que quebram a busca no banco.
- **Solução**: O SDK `client.py` agora limpa o número e compara os últimos 9 dígitos (Fuzzy Matching).
- **Status**: ✅ BLOQUEADO (Funciona 100%)

## 2. Estabilidade do Docker (ImportErrors)
- **Problema**: Remover funções "limpas" que o roteador de webhooks (`evolution_handler.py`) usa.
- **Solução**: Funções `set_pro_context` e `transcribe_audio` são obrigatórias na engine.
- **Status**: ✅ BLOQUEADO (Interface Protegida)

## 3. Erro 400 OpenAI (History Slicing)
- **Problema**: Cortar o histórico e deixar uma "Resposta de Ferramenta" órfã no início.
- **Solução**: Lógica `while window and isinstance(window[0], ToolMessage): window = window[1:]` implementada na `call_model`.
- **Status**: ✅ BLOQUEADO (Resiliência de Memória)

## 4. Agendamento e Timezone (Brasília)
- **Problema**: Horários mostrados em UTC ou chaves de tempo erradas (`startTime` vs `openTime`).
- **Solução**: Uso fixo de `openTime`/`closeTime`. Timezone forçado para `America/Sao_Paulo`.
- **Status**: ✅ BLOQUEADO

## 5. Fluxo de Atendimento (Helena)
- **Cadeado**: A Helena deve SEMPRE usar `buscar_cliente` antes de qualquer outra ação para saudação personalizada.
