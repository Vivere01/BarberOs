@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str, store_id: str = "") -> str:
    """Verifica horários disponíveis para um dia e unidade específica."""
    client = ChatBarberProClient(**_get_current_ctx())
    try:
        # 1. Pegar Unidade e Horários de funcionamento
        stores = await client.list_stores()
        selected_store = next((s for s in stores if str(s.get("id")) == str(store_id)), None)
        
        if not selected_store:
            # Se não passou StoreID mas só tem uma, usa ela
            if len(stores) == 1:
                selected_store = stores[0]
                store_id = selected_store.get("id")
            else:
                names = [f"{s.get('name')} (ID: {s.get('id')})" for s in stores]
                return f"Por favor, escolha uma unidade primeiro: {', '.join(names)}"

        # Consultar horários da unidade (via store_id selecionado)
        bh_list = await client.list_business_hours()
        # Filtra horários da unidade específica
        unit_bh = [h for h in bh_list if str(h.get("storeId")) == str(store_id)]
        
        # Mapa de dia da semana (API usa 0=Sunday ou similar? Vamos assumir 0-6)
        dt_obj = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        day_of_week = dt_obj.weekday() + 1 # Monday=1 em Python, API weekday?
        if day_of_week == 7: day_of_week = 0 # Ajuste para Sunday=0
        
        day_config = next((h for h in unit_bh if h.get("dayOfWeek") == day_of_week), None)
        
        if not day_config or not day_config.get("isOpen"):
            return f"A unidade {selected_store.get('name')} não abre neste dia."

        s_h, s_m = map(int, day_config.get("startTime", "08:00").split(":"))
        e_h, e_m = map(int, day_config.get("endTime", "19:00").split(":"))

        # 2. Consultar Profissionais e Agendamentos
        staff = await client.list_staff()
        # Filtra staff que pertence a essa unidade
        unit_staff = [s for s in staff if str(s.get("storeId")) == str(store_id)]
        
        if not unit_staff:
            return "Não há profissionais cadastrados para esta unidade."

        appointments_res = await client.list_appointments(date=data_yyyy_mm_dd)
        apps = appointments_res.get("appointments", [])
        
        names = {str(s["id"]): s["name"] for s in unit_staff}
        ocupacao = {str(s["id"]): set() for s in unit_staff}
        
        for app in apps:
            sid = str(app.get("staffId"))
            if sid in ocupacao:
                ocupacao[sid].add(str(app.get("scheduledAt", "")).split("T")[1][:5])

        now = _now_brasilia()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        min_now = now.hour * 60 + now.minute
        rel = [f"Horários em '{selected_store.get('name')}' para {data_yyyy_mm_dd}:"]
        total = 0
        for sid, ocupados in ocupacao.items():
            disp = []
            ch, cm = s_h, s_m
            while (ch * 60 + cm) < (e_h * 60 + e_m):
                h_str = f"{ch:02d}:{cm:02d}"
                if not (is_today and (ch * 60 + cm) <= min_now + 10):
                    if h_str not in ocupados: disp.append(h_str)
                cm += 30
                if cm >= 60: ch += 1; cm = 0
            if disp:
                rel.append(f"- {names[sid]} (ID: {sid}): {', '.join(disp)}")
                total += len(disp)
        
        return "\n".join(rel) if total > 0 else f"Não há horários livres em {selected_store.get('name')} para este dia."
    except Exception as e:
        logger.error(f"TOOL_ERROR: {e}")
        return "Erro ao processar agenda."
