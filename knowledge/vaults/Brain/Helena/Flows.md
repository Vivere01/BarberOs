---
title: Fluxos de Atendimento
tags: ["helena", "flows", "ux"]
---

# 📉 Fluxos de Atendimento

## 1. Fluxo de Agendamento (Cliente Antigo)
1. `buscar_cliente(telefone)` -> Retorna Nome e ID.
2. Saudações: "Olá [Nome]! Que bom te ver de volta. O que vamos agendar hoje?"
3. Identifica Serviço (Corte, Barba, etc).
4. `verificar_disponibilidade(data)` -> Mostra opções.
5. Cliente confirma -> `agendar_horario`.

## 2. Fluxo de Cadastro + Agendamento (Novo Cliente)
1. `buscar_cliente(telefone)` -> "Não cadastrado".
2. Saudações: "Olá! Seja bem-vindo à nossa barbearia. Como é o seu nome completo?"
3. Pede Telefone e Data de Nascimento.
4. `cadastrar_cliente`.
5. Segue para o Fluxo de Agendamento.

## 3. Manejo de Áudio
1. Recebe áudio.
2. `transcribe_audio` processa.
3. IA responde ao conteúdo transcrito como se fosse texto.
4. Se a transcrição falhar: "Poxa, não consegui entender bem o áudio. Poderia digitar para mim? 😊"
