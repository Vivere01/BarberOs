# 🏴 BarberOS — AI Receptionist Infrastructure

> Infraestrutura robusta de IA para recepcionistas virtuais de barbearias no WhatsApp.
> **Zero alucinação. Totalmente rastreável. Integrado com CashBarber e AppBarber.**

---

## 🎯 O que é?

BarberOS é o backend inteligente que alimenta agentes de IA no WhatsApp para barbearias. Ele:

- **Recebe mensagens** do WhatsApp via UzAPI + N8N
- **Classifica intenções** com precisão (LangGraph + OpenAI)
- **Busca dados reais** dos sistemas de agendamento (CashBarber/AppBarber)
- **Responde sem alucinar** — pipeline de validação em 5 etapas
- **Agenda, cancela e consulta** diretamente nos sistemas
- **Registra tudo** para debugging rápido

## 🏗️ Arquitetura

```
WhatsApp ←→ UzAPI ←→ N8N (Webhook) ←→ BarberOS API (FastAPI)
                                              │
                                      ┌───────┴────────┐
                                      │  LangGraph     │
                                      │  State Machine │
                                      └───────┬────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          │                   │                   │
                    ┌─────▼─────┐      ┌─────▼──────┐     ┌─────▼─────┐
                    │  Router   │      │  Handlers  │     │ Validator │
                    │ (temp=0)  │      │            │     │ (anti-AI  │
                    │           │      │ greeting   │     │  halluc.) │
                    │ classific │      │ scheduling │     │           │
                    │ intenção  │      │ query      │     │ PII check │
                    └───────────┘      │ cancel     │     │ biz rules │
                                       │ fallback   │     │ LLM-judge │
                                       └─────┬──────┘     └───────────┘
                                              │
                                      ┌───────┴────────┐
                                      │  Integrations  │
                                      │                │
                                      │ CashBarber ←──── Web Scraping
                                      │ AppBarber  ←──── (login pirata)
                                      │ UzAPI      ←──── WhatsApp
                                      └────────────────┘
```

## 🛡️ Sistema Anti-Alucinação (5 Camadas)

| Camada | O que faz | Como |
|--------|-----------|------|
| **1. Prompt Engineering** | Proíbe invenção | System prompt com regras absolutas |
| **2. Classificação Determinística** | Lista fechada de intenções | Enum + temp=0 + JSON schema |
| **3. Grounding** | Dados reais do sistema | Scraping CashBarber/AppBarber em tempo real |
| **4. Validação LLM-as-Judge** | Detecta alucinação | Segundo LLM verifica contra dados reais |
| **5. Templates Determinísticos** | Respostas seguras | Templates pré-definidos para respostas críticas |

### Quando o agente NÃO sabe a resposta:
- ❌ NÃO inventa
- ✅ Diz "vou verificar" e busca no sistema
- ✅ Se não encontra, transfere para humano

## 📂 Estrutura do Projeto

```
barberOs/
├── src/
│   ├── main.py                    # FastAPI entry point
│   ├── config/
│   │   ├── settings.py            # Todas as configurações (Pydantic)
│   │   └── logging_config.py      # Logs estruturados
│   ├── api/routes/
│   │   ├── webhook.py             # Recebe webhooks do N8N
│   │   └── health.py              # Health checks
│   ├── agent/
│   │   ├── graph.py               # ★ LangGraph state machine
│   │   ├── state.py               # Estado tipado do agente
│   │   ├── prompts/               # Prompts anti-alucinação
│   │   └── nodes/
│   │       ├── router.py          # Classificação de intenção
│   │       ├── greeting.py        # Saudações (template)
│   │       ├── scheduling.py      # Agendamento step-by-step
│   │       ├── query.py           # Consultas (só dados reais)
│   │       ├── cancellation.py    # Cancelamento com confirmação
│   │       ├── validator.py       # ★ Anti-alucinação
│   │       └── fallback.py        # Handoff para humano
│   ├── integrations/
│   │   ├── base_scraper.py        # Base com retry/cache/sessão
│   │   ├── cashbarber/client.py   # Scraper CashBarber
│   │   ├── appbarber/client.py    # Scraper AppBarber
│   │   └── uzapi/client.py        # Client WhatsApp
│   ├── knowledge/                 # Knowledge base (RAG)
│   └── observability/             # Traces e métricas
├── knowledge_base/                # Configs por barbearia (YAML)
├── tests/                         # Testes automatizados
├── docker-compose.yml             # Deploy com Docker
└── n8n/                           # Workflows N8N de referência
```

## 🚀 Quick Start

### 1. Clone e configure

```bash
git clone https://github.com/Vivere01/BarberOs.git
cd BarberOs
cp .env.example .env
# Edite .env com suas credenciais
```

### 2. Instale dependências

```bash
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Execute

```bash
# Desenvolvimento
python -m src.main

# Ou com Docker
docker-compose up -d
```

### 4. Teste

```bash
# Testes unitários
pytest tests/ -v

# Teste manual via curl
curl -X POST http://localhost:8000/api/v1/webhook/message \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "11999999999",
    "message": "Quero agendar um corte",
    "barbershop_id": "minha-barbearia",
    "system_type": "cashbarber"
  }'
```

## 🔧 Integração com N8N

### Webhook de Recebimento (N8N → BarberOS)

Configure no N8N:
1. **Trigger**: Webhook recebe mensagem da UzAPI
2. **HTTP Request**: POST para `http://SEU-SERVER:8000/api/v1/webhook/message`
3. **Resposta**: O N8N recebe o JSON com `response`, `response_type` e `needs_human`
4. **Ação**: Se `needs_human=false`, envia `response` via UzAPI. Se `true`, notifica atendente.

### Payload de Entrada (N8N → BarberOS):
```json
{
  "phone": "5511999999999",
  "message": "Quero cortar cabelo amanhã",
  "name": "João",
  "barbershop_id": "barbearia-costeleta",
  "system_type": "cashbarber",
  "system_username": "admin@barbearia.com",
  "system_password": "senha-do-sistema"
}
```

### Payload de Saída (BarberOS → N8N):
```json
{
  "success": true,
  "response": "Ótimo! Qual serviço você gostaria?\n\n• Corte Social — R$ 45\n• Barba — R$ 30\n• Corte + Barba — R$ 65",
  "response_type": "list",
  "conversation_id": "barbearia-costeleta_5511999999999",
  "intent": "schedule_appointment",
  "confidence": 0.95,
  "needs_human": false,
  "debug": {
    "turn_count": 1,
    "guardrail_valid": true,
    "hallucination_detected": false
  }
}
```

## 📊 Observabilidade

### LangSmith (Recomendado)
Configure `LANGCHAIN_API_KEY` e `LANGCHAIN_TRACING_V2=true` no `.env`.
Todos os traces das conversas aparecem no dashboard do LangSmith.

### Logs Estruturados
Todos os logs são JSON estruturado com:
- `conversation_id` — rastreia toda a conversa
- `component` — qual módulo gerou o log
- `intent`, `confidence` — decisões do agente
- `hallucination_detected` — alertas de alucinação

### Métricas
- Taxa de alucinação
- Taxa de handoff para humano
- Tempo médio de resposta
- Distribuição de intenções
- Erros por tipo

## 📝 Configurando uma Nova Barbearia

1. Copie `knowledge_base/barbershop_template.yaml`
2. Renomeie para o ID da barbearia
3. Preencha: nome, endereço, FAQ, regras
4. Configure credenciais do sistema no `.env` ou no payload do N8N

## ⚠️ Notas Importantes

- **Integração "pirata"**: CashBarber e AppBarber não têm API oficial. Usamos login do cliente.
- **Monitore endpoints**: Os endpoints dos sistemas podem mudar. Monitore os logs de `ScraperError`.
- **Temperature 0.1**: Mantemos temperatura ultra-baixa para minimizar criatividade indesejada.
- **Fallback humano**: Em qualquer dúvida, o agente transfere para humano. Melhor não responder do que alucinar.

## 📄 Licença

Proprietary — Vivere01