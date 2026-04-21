---
title: Lições Aprendidas e Correções Críticas
tags: ["engineering", "debug", "history"]
---

# 💡 Lições Aprendidas

Registro histórico de problemas complexos resolvidos e decisões de engenharia.

## 🔴 [21/04/2026] Fix: Identificação de Clientes e Horários de Pico

### O Problema
1. IA não identificava clientes cadastrados (como "Lucas") via WhatsApp.
2. IA dizia que a barbearia fechava às 17:30, mesmo estando aberta até as 20h.
3. IA focava apenas em um profissional (Ferdinando) e ignorava outros.

### Causa Raiz
1. **Filtro Estrito de Banco**: A API usava um filtro SQL `contains` para o telefone. Como o banco de dados formata números como `(22) 99714...` e o WhatsApp envia sem formatação, o banco não encontrava correspondência exata.
2. **Hardcoded Limits**: O motor da IA tinha um loop de geração de grade de horários fixo entre 08:00 e 20:00, sem consultar as `businessHours` reais de cada unidade, o que causava truncamento de horários.
3. **Syntax Error**: Um erro de digitação no `system_prompt` (um `\` antes das aspas triplas) causou um `SyntaxError` que impedia o container de iniciar.

### Solução Aplicada
- **Fuzzy Search em Python**: A API agora retorna a lista de clientes, e o Client SDK da IA aplica a filtragem inteligente (removendo todos os caracteres não numéricos e comparando sufixos). Isso resolve a busca de "2299714..." vs "(22) 99714...".
- **Business Hours Integration**: A IA agora consulta as `businessHours` de cada unidade antes de gerar a grade de horários, permitindo agendamentos até o fechamento real do estabelecimento.
- **Diferenciação por Unidade**: Implementada regra que obriga a IA a perguntar a unidade se houver mais de uma cadastrada, evitando que ela mostre apenas profissionais de uma única unidade.
- **Saneamento de Sintaxe**: Corrigido o prompt do sistema para remover caracteres ilegais que causavam o crash do serviço.

---

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
