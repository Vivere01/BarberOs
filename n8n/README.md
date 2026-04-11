# Workflows N8N - BarberOS

## Fluxo Principal: WhatsApp → BarberOS → WhatsApp

```
┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│  UzAPI Webhook   │────▶│  BarberOS    │────▶│  UzAPI Send  │
│  (Recebe msg)    │     │  HTTP POST   │     │  (Envia resp)│
└──────────────────┘     └──────┬───────┘     └──────────────┘
                                │
                         ┌──────▼───────┐
                         │  needs_human │
                         │  == true?    │
                         └──────┬───────┘
                           SIM  │  NÃO
                    ┌───────────┼────────────┐
                    ▼                        ▼
            ┌──────────────┐         ┌──────────────┐
            │  Notifica    │         │  Envia via   │
            │  Atendente   │         │  WhatsApp    │
            └──────────────┘         └──────────────┘
```

## Configuração do N8N

### 1. Trigger (Webhook UzAPI)
- URL: `https://seu-n8n.com/webhook/uzapi-incoming`
- Método: POST

### 2. HTTP Request (BarberOS)
- URL: `http://barberos-api:8000/api/v1/webhook/message`
- Método: POST
- Headers: `X-Webhook-Secret: seu-secret`
- Body:
```json
{
  "phone": "{{ $json.phone }}",
  "message": "{{ $json.message }}",
  "name": "{{ $json.name }}",
  "barbershop_id": "{{ $json.barbershop_id }}",
  "system_type": "cashbarber",
  "system_username": "admin@barbearia.com",
  "system_password": "senha"
}
```

### 3. Conditional (needs_human?)
- Condição: `{{ $json.needs_human }}` == `true`
- True: Notifica atendente
- False: Envia resposta

### 4. UzAPI Send
- Endpoint UzAPI de envio de mensagem
- Corpo: `{{ $json.response }}`
