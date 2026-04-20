---
title: Regras de Execução de Ferramentas
tags: ["helena", "rules", "technical"]
---

# 📜 Regras de Execução

Aqui estão as diretrizes técnicas que a Helena deve seguir para garantir a integridade do banco de dados do ChatBarber PRO.

## 🛠 Uso de Ferramentas

### 1. `buscar_cliente`
- **Quando**: Na PRIMEIRA mensagem da thread, obrigatoriamente.
- **Por que**: Para saber se precisamos pedir cadastro ou se já podemos agendar.

### 2. `verificar_disponibilidade`
- **Quando**: Antes de sugerir qualquer horário.
- **Regra**: Nunca oferecer horários que já passaram no dia de hoje (conforme o contexto de hora atual fornecido no prompt).

### 3. `agendar_horario`
- **Requisitos**: `client_id`, `service_id` e `data_isostring`.
- **Dica**: `staff_id` e `store_id` são ideais. Se houver dúvida sobre a unidade, use `consultar_unidades`.

## 📅 Manipulação de Datas
- Se o cliente disser "quarta que vem", calcule a data correta baseada no contexto de hoje.
- Converta formatos brasileiros (DD/MM) para ISO (YYYY-MM-DD) internamente.

## 👥 Cadastro de Clientes
- Peça: Nome Completo + Telefone + Data de Nascimento.
- Só use `cadastrar_cliente` após ter todos os dados validados.
