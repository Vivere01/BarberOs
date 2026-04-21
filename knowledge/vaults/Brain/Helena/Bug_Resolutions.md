# [BUG RESOLVIDO] IA WhatsApp — Loop de indisponibilidade

**Data:** 21/04/2026
**Causa raiz identificada:** 
1. Rigidez no mapeamento de `dayOfWeek` (API retornando índices variados 0-6 vs 1-7 que não batiam com o `day_py`).
2. Ausência de dados ou dados de `isOpen: false` em unidades ativas faziam o sistema retornar "fechado" silenciosamente, sem conferir a agenda real.
3. Prompt da IA sem limites de re-tentativa (Loop infinito).
4. Erro de crash ("oscilação") devido a payloads inesperados da API não tratados.

**Arquivos modificados:**
- `src/agent/chatbarber_pro_engine.py` (Tool reformulada e Prompt corrigido)
- `knowledge/vaults/Brain/Helena/Rules.md` (Regras de escalagem e timezone)

**Solução implementada:**
- **Mapeamento Triplo de Dias:** O sistema agora testa `[0, 1, 2]` para terça-feira, cobrindo todos os padrões possíveis de API.
- **Fallback de Horários:** Se `businessHours` falhar ou estiver fechado, o sistema assume 08:00 às 19:00 como margem de segurança para buscar slots reais.
- **Surgical Logging:** Implementado o padrão `[AGENDAMENTO_DEBUG]` para rastreio total de cada consulta.
- **Escalagem Automática:** IA instruída a parar na 3ª tentativa frustrada e transferir para atendimento humano.

### Regras que devem ser mantidas para sempre:
- **REGRA DE OURO:** A tool `verificar_disponibilidade()` é a fonte de verdade absoluta. O resultado `[FONTE_DE_VERDADE_API]` nunca pode ser ignorado ou contestado pelo raciocínio do modelo.
- **Is_Fallback Ignorado:** `is_fallback=true` não significa fechado. Se houver slots, agende.
- O prompt da IA deve ter limite de 2 tentativas de reagendamento.
- Timezone do servidor deve ser `America/Sao_Paulo`.
- A unidade deve sempre ser resolvida por ID.

### Padrão de log implementado:
Logs JSON via `structlog` com a chave `AGENDAMENTO_DEBUG` contendo `timestamp_requisicao`, `unidade_id_resolvido`, `horario_funcionamento_encontrado` e `slots_disponiveis_encontrados`.

### Sinal de alerta para regressão:
Se a IA começar a dizer "não está aberta" mais de 2 vezes seguidas em uma conversa, o bug voltou — verificar o mapeamento de `days_to_check` em `verificar_disponibilidade`.
