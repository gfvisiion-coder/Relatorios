import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta, time as dtime
import os
import time
import re
import extra_streamlit_components as stx

# --- CONFIGURAÇÃO BASE DO APP ---
st.set_page_config(page_title="Relatorio - Setor Afiação", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

FUSO_BR = timezone(timedelta(hours=-3))

# --- LISTA GLOBAL DE MÁQUINAS ---
TODAS_AFC = ["6-868", "9-088", "7-743", "11-365", "13-964", "15-973", "17-140", "19-760", "21-206", "23-165", "25-209", "27-431", 
             "8-247", "4-427", "10-812", "12-367", "14-967", "16-975", "18-957", "20-774", "22-813", "24-761", "26-635", "28-432",
             "29-078", "31-969", "33-160", "35-131", "37-892", "39-905", "41-141",
             "30-161", "32-081", "34-132", "36-084", "38-596", "40-142"]

TODAS_RTF = ["5-903", "8-086", "10-817", "12-962", "14-971", "16-183", "19-926", "21-270", "23-753", "25-258", "27-917",
             "7-267", "9-815", "11-363", "13-969", "15-977", "18-925", "20-927", "22-916", "24-259", "26-260", "28-954",
             "29-785", "31-806", "33-807", "35-885", "37-857", "39-856",
             "30-786", "32-918", "34-842", "36-854", "38-881", "40-912", "42-885", "4-425", "6-6J1", "17-6J1", "3-426"]

# --- DESIGN SYSTEM ---
CSS_APP = """
<style>
    .stApp { background-color: #09090B !important; }
    h1, h2, h3, h4, h5, p, div[data-testid="stMarkdownContainer"] > p { 
        color: #F4F4F5 !important; 
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important; 
    }
    label { color: #E4E4E7 !important; font-size: 12px !important; font-weight: 700 !important; text-transform: uppercase; letter-spacing: 0.5px; }
    .block-container { padding: 0.6rem 0.5rem !important; max-width: 100% !important; }
    
    button[kind="secondary"] { 
        background-color: #18181B !important; color: #2DD4BF !important; 
        border: 1px solid #3F3F46 !important; border-radius: 8px !important; 
        font-weight: 600 !important; height: 46px !important; font-size: 13px !important;
        width: 100% !important; margin-bottom: 6px !important; transition: all 0.2s ease-in-out;
    }
    button[kind="secondary"]:hover { border-color: #14B8A6 !important; background-color: #27272A !important; color: #5EEAD4 !important; }
    
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { 
        background: linear-gradient(135deg, #0D9488 0%, #0F766E 100%) !important; 
        color: white !important; border: none !important; border-radius: 8px !important; 
        height: 46px !important; font-size: 13px !important; font-weight: 700 !important; 
        width: 100% !important; box-shadow: 0 4px 12px rgba(13, 148, 136, 0.3);
    }
    div[data-testid="stFormSubmitButton"] > button:hover { background: linear-gradient(135deg, #0F766E 100%, #115E59 100%) !important; }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { 
        background-color: #27272A !important; border: 1px solid #52525B !important; 
        border-radius: 8px !important; min-height: 42px !important; 
    }
    
    input, select, textarea { color: #FF4444 !important; font-size: 15px !important; font-weight: 600 !important; }
    
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background-color: #121214; border: 1px solid #27272A; border-radius: 12px;
        padding: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }
    
    /* CSS para os botões das Gavetas */
    div[data-testid="stButton"] > button {
        height: 60px !important;
        padding: 5px !important;
        border-radius: 8px !important;
        font-size: 12px !important;
        line-height: 1.2 !important;
        white-space: pre-wrap !important;
    }
    
    /* Estilo para os TOASTS (Pop-ups laterais) */
    div[data-testid="stToast"] {
        background-color: #450a0a !important;
        border: 1px solid #ef4444 !important;
        border-radius: 8px !important;
        padding: 15px !important;
    }
    div[data-testid="stToast"] div[data-testid="stMarkdownContainer"] > p {
        color: #ff6b6b !important;
        font-weight: 800 !important;
        font-size: 16px !important;
    }
    
    /* Animação de Alerta Urgente (Pisca-Pisca) */
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
        70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
        100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    .alerta-pisca {
        animation: pulse-red 2s infinite;
        background-color: #450a0a !important;
        border: 2px solid #ef4444 !important;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
    }
    
    header { visibility: hidden; }
</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)

# --- GERENCIADOR DE COOKIES E ARQUIVOS ---
cookie_manager = stx.CookieManager()
cookies_salvos = cookie_manager.get_all()

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"
ARQUIVO_HISTORICO = "historico_relatorios.csv"
ARQUIVO_HISTORICO_EVENTOS = "historico_eventos.csv"
ARQUIVO_ARMARIOS = "banco_armarios.csv"
ARQUIVO_ALERTAS = "alertas_preset.csv"
ARQUIVO_CNC = "banco_cnc.csv"
ARQUIVO_FECHAMENTO = "ultimo_fechamento.csv"
ARQUIVO_REBOLOS = "banco_rebolos.xlsx" # ATUALIZADO PARA .XLSX

# --- FUNÇÕES UTILITÁRIAS ---
def turno_atual_horario():
    agora = datetime.now(FUSO_BR).time()
    if dtime(6, 20) <= agora < dtime(14, 20): return "1° TURNO"
    elif dtime(14, 20) <= agora < dtime(22, 20): return "2° TURNO"
    else: return "3° TURNO"

def obter_turno_por_horario(hora_str):
    try:
        t = datetime.strptime(hora_str, "%H:%M").time()
        if dtime(6, 30) <= t < dtime(14, 30): return "1° TURNO"
        elif dtime(14, 30) <= t < dtime(22, 30): return "2° TURNO"
        else: return "3° TURNO"
    except: return "DESCONHECIDO"

def pode_logar(turno_val):
    agora = datetime.now(FUSO_BR).time()
    if turno_val == "1° TURNO": return dtime(6, 20) <= agora <= dtime(14, 50)
    if turno_val == "2° TURNO": return dtime(14, 20) <= agora <= dtime(22, 50)
    if turno_val == "3° TURNO": return agora >= dtime(22, 20) or agora <= dtime(7, 0)
    return True

def diff_mins(h_inicio, h_fim, eh_espera=False):
    try:
        t1 = datetime.strptime(h_inicio, "%H:%M")
        t2 = datetime.strptime(h_fim, "%H:%M")
        diff = (t2 - t1).total_seconds() / 60
        
        if diff < -720: diff += 1440
        elif diff > 720: diff -= 1440
            
        if diff < 0: return 0
        return int(diff)
    except: return 0

def format_tempo(mins):
    if mins <= 0: return "0 minutos"
    h = mins // 60
    m = mins % 60
    if h > 0: return f"{h} hora(s) e {m} minuto(s)"
    return f"{m} minuto(s)"

def get_sort_key(time_str):
    if not time_str or time_str == '--' or time_str == '00:00': return "99:99"
    try:
        h = int(time_str.split(':')[0])
        m = int(time_str.split(':')[1])
        if h < 6: h += 24
        return f"{h:02d}:{m:02d}"
    except: return str(time_str)

# --- GERENCIAMENTO DE TIPO CNC (RTF) ---
def ler_tipos_cnc():
    tipos = {}
    for m in TODAS_RTF:
        if m in ["6-6J1", "17-6J1"]: tipos[m] = "RTF_CNC1"
        elif m in ["3-426", "4-425"]: tipos[m] = "RTF_CNC2"
        else: tipos[m] = "RTF_CNC3"
        
    if os.path.exists(ARQUIVO_CNC):
        try:
            df = pd.read_csv(ARQUIVO_CNC)
            for _, row in df.iterrows():
                tipos[str(row['Maquina'])] = str(row['Tipo'])
        except: pass
    return tipos

def get_tipo_cnc(maq_id):
    return ler_tipos_cnc().get(maq_id, "RTF_CNC3")

def set_tipo_cnc(maq_id, tipo):
    if os.path.exists(ARQUIVO_CNC):
        df = pd.read_csv(ARQUIVO_CNC)
        df = df[df['Maquina'] != maq_id]
        df = pd.concat([df, pd.DataFrame([{"Maquina": maq_id, "Tipo": tipo}])], ignore_index=True)
        df.to_csv(ARQUIVO_CNC, index=False)
    else:
        pd.DataFrame([{"Maquina": maq_id, "Tipo": tipo}]).to_csv(ARQUIVO_CNC, index=False)

# --- FUNÇÕES DE RELATÓRIO E FECHAMENTO AUTOMÁTICO ---
def get_turno_logico(dt=None):
    if dt is None: dt = datetime.now(FUSO_BR)
    t = dt.time()
    d = dt.date()
    if dtime(6, 20) <= t < dtime(14, 20): return d.strftime("%d/%m/%Y"), "1° TURNO"
    elif dtime(14, 20) <= t < dtime(22, 20): return d.strftime("%d/%m/%Y"), "2° TURNO"
    else:
        if t < dtime(6, 20): d -= timedelta(days=1)
        return d.strftime("%d/%m/%Y"), "3° TURNO"

def processar_padrao(df_all, maquinas, prefixo_setor):
    linhas = []
    for maq in maquinas:
        if not maq.startswith(prefixo_setor): continue
        df_maq = df_all[df_all['Maquina'] == maq]
        ciclo_ativo, status_limpo, hora_prep, preparador = False, "", "", ""
        for _, row in df_maq.iterrows():
            st_val, h_val = str(row['Status']), str(row['Hora'])
            if "Energia Restaurada" in st_val: continue
            
            prep_atual = ""
            if "[Prep:" in st_val: prep_atual = st_val.split("[Prep:")[1].split("]")[0].strip()
            elif "[Prep. Sugerido:" in st_val: prep_atual = st_val.split("[Prep. Sugerido:")[1].split("]")[0].strip()
            elif "[PREP:" in st_val.upper(): prep_atual = st_val.upper().split("[PREP:")[1].split("]")[0].strip()
            if prep_atual: preparador = prep_atual

            if "PREPARAÇÃO" in st_val or "SEQUÊNCIA" in st_val or "AGUARDANDO" in st_val:
                if not ciclo_ativo:
                    ciclo_ativo, hora_prep = True, h_val
                    if "[AGENDADO:" in st_val:
                        try: hora_prep = st_val.split("[AGENDADO:")[1].split("]")[0].strip()
                        except: pass
                    s_limpo = st_val.split("[")[0].strip().upper().replace("PREPARAÇÃO - ", "")
                    status_limpo = s_limpo if s_limpo else "SETUP"
            elif "PREPARANDO" in st_val:
                if not ciclo_ativo: ciclo_ativo, hora_prep = True, h_val
                status_limpo = "PREPARANDO"
            elif ("PRODUZINDO" in st_val or "PARADA" in st_val or "MANUTENÇÃO" in st_val) and ciclo_ativo:
                if "Queda de Energia" in st_val: continue
                num_maq, str_prep = maq.replace(f"{prefixo_setor} ", ""), f" - {preparador}" if preparador else ""
                if "PRODUZINDO" in st_val:
                    status_final = "MÁQUINA LIBERADA"
                    if "[Obs:" in st_val:
                        try: str_prep += f" (Obs: {st_val.split('[Obs:')[1].split(']')[0].strip()})"
                        except: pass
                elif "MANUTENÇÃO" in st_val: status_final = "SETUP INTERROMPIDO (MANUTENÇÃO)"
                else: status_final = "SETUP INTERROMPIDO (PARADA)"
                tags_prod = extrair_tags_producao(st_val)
                linhas.append((hora_prep if hora_prep != '--' else '00:00', f"{num_maq} - {hora_prep} - {status_final}{str_prep} {tags_prod}\n\n"))
                ciclo_ativo, preparador = False, ""
                
        if ciclo_ativo:
            num_maq, str_prep = maq.replace(f"{prefixo_setor} ", ""), f" - {preparador}" if preparador else ""
            tags_prod = extrair_tags_producao(df_maq.iloc[-1]['Status'])
            linhas.append((hora_prep if hora_prep != '--' else '00:00', f"{num_maq} - {hora_prep} - {status_limpo}{str_prep} {tags_prod}\n\n"))
    linhas.sort(key=lambda x: get_sort_key(x[0]))
    return "".join([item[1] for item in linhas])

def gerar_relatorio_tempos(df_all, maquinas, prefixo):
    texto_saida = []
    def salvar_ciclo(maq_num, h_agenda_orig, adiamentos, h_inicio, h_assumido, h_fim, p1, p2, st_final=""):
        h_agenda_str = h_agenda_orig if h_agenda_orig else '00:00'
        
        if h_inicio is None: 
            txt = f"Máquina {maq_num}: Aguardando preparador desde as {h_agenda_str}.\n"
            if adiamentos: txt += f"Adiado para: {', '.join(adiamentos)}.\n"
            txt += "Preparador sugerido: AGUARDANDO OPERADOR\n\n"
            return (h_agenda_str, txt)
        
        h_agenda_final = adiamentos[-1] if adiamentos else h_agenda_orig
        
        t_espera_mins = diff_mins(h_agenda_final, h_inicio, eh_espera=True) if h_agenda_final else 0
        t_espera = format_tempo(t_espera_mins)
        h_conclusao = h_fim if h_fim else datetime.now(FUSO_BR).strftime("%H:%M")
        
        txt_maq = f"Máquina {maq_num}: "
        if h_agenda_orig:
            txt_maq += f"Agendado inicialmente para {h_agenda_orig}. "
            if adiamentos: txt_maq += f"Adiado para {', '.join(adiamentos)}. "
            txt_maq += f"Aguardou {t_espera} (após última previsão) até o início.\n"
        else:
            txt_maq += "Iniciado diretamente, sem tempo de espera agendado prévio.\n"
        
        is_finished, is_interrompido = "PRODUZINDO" in st_final, "PARADA" in st_final or "MANUTENÇÃO" in st_final
        obs_texto = ""
        if "[Obs:" in st_final:
            try: obs_texto = f" | Obs: {st_final.split('[Obs:')[1].split(']')[0].strip()}"
            except: pass
        
        if is_finished: txt_estado = "finalizado"
        elif is_interrompido: txt_estado = "interrompido"
        else: txt_estado = "EM ANDAMENTO"
        
        if p2 is not None:
            t1, t2 = format_tempo(diff_mins(h_inicio, h_assumido)), format_tempo(diff_mins(h_assumido, h_conclusao))
            if h_fim: txt_maq += f"Setup {txt_estado}! Iniciado por {p1} e assumido por {p2}.\nO 1º levou {t1} e o 2º {t2}.{obs_texto}\n\n"
            else: txt_maq += f"Setup {txt_estado}! Iniciado por {p1} e assumido por {p2}.\nO 1º levou {t1} e o 2º está preparando há {t2}.\n\n"
        else:
            t_tot = format_tempo(diff_mins(h_inicio, h_conclusao))
            if h_fim: txt_maq += f"Setup {txt_estado}! Levou {t_tot}. Preparador responsável: {p1}.{obs_texto}\n\n"
            else: txt_maq += f"Setup {txt_estado} há {t_tot} até o momento. Preparador responsável: {p1}.\n\n"
        return (h_agenda_str, txt_maq)

    for maq in maquinas:
        if not maq.startswith(prefixo): continue
        df_hist = df_all[df_all['Maquina'] == maq]
        ciclo_ativo = False
        hora_agenda_orig, adiamentos = None, []
        hora_inicio, hora_assumido, hora_fim = None, None, None
        prep_1, prep_2 = None, None
        
        for _, h_row in df_hist.iterrows():
            st_val, h_val = str(h_row['Status']).upper(), str(h_row['Hora'])
            if "ENERGIA RESTAURADA" in st_val: continue
            
            if "PREPARAÇÃO" in st_val or "SEQUÊNCIA" in st_val or "AGUARDANDO" in st_val:
                if not ciclo_ativo:
                    ciclo_ativo = True
                    hora_agenda_orig = h_val
                    adiamentos = []
                    hora_inicio, hora_assumido, hora_fim, prep_1, prep_2 = None, None, None, None, None
                    
                if "AGENDADA PARA" in st_val:
                    try: 
                        h_novo = st_val.split("AGENDADA PARA")[1].strip()
                        if not hora_agenda_orig: hora_agenda_orig = h_novo
                        elif h_novo != hora_agenda_orig and h_novo not in adiamentos: adiamentos.append(h_novo)
                    except: pass
                elif "[AGENDADO:" in st_val:
                    try: 
                        h_novo = st_val.split("[AGENDADO:")[1].split("]")[0].strip()
                        if not hora_agenda_orig: hora_agenda_orig = h_novo
                        elif h_novo != hora_agenda_orig and h_novo not in adiamentos: adiamentos.append(h_novo)
                    except: pass
                    
            elif "PREPARANDO" in st_val:
                ciclo_ativo = True
                if not hora_agenda_orig: hora_agenda_orig = h_val
                if "[ASSUMIDO]" in st_val:
                    hora_assumido = h_val
                    try: prep_2 = st_val.split("[PREP:")[1].split("]")[0].strip()
                    except: pass
                else:
                    if hora_inicio is None: hora_inicio = h_val
                    try: prep_1 = st_val.split("[PREP:")[1].split("]")[0].strip()
                    except: pass
            elif ("PRODUZINDO" in st_val or "PARADA" in st_val or "MANUTENÇÃO" in st_val) and ciclo_ativo:
                if "QUEDA DE ENERGIA" in st_val: continue
                hora_fim = h_val
                texto_saida.append(salvar_ciclo(maq.replace(f"{prefixo} ", ""), hora_agenda_orig, adiamentos, hora_inicio, hora_assumido, hora_fim, prep_1, prep_2, st_val))
                ciclo_ativo = False
        if ciclo_ativo: 
            texto_saida.append(salvar_ciclo(maq.replace(f"{prefixo} ", ""), hora_agenda_orig, adiamentos, hora_inicio, hora_assumido, None, prep_1, prep_2, ""))
            
    texto_saida.sort(key=lambda x: get_sort_key(x[0]))
    return "".join([i[1] for i in texto_saida])

def calcular_tempos_interrupcoes(df_all, palavra_chave):
    texto = ""
    for maq in df_all['Maquina'].unique():
        df_maq = df_all[df_all['Maquina'] == maq]
        in_status = False
        h_in = ""
        motivo = ""
        for _, row in df_maq.iterrows():
            st_val, h_val = str(row['Status']), str(row['Hora'])
            if "Energia Restaurada" in st_val or "Queda de Energia" in st_val: continue
            
            is_target = palavra_chave in st_val.upper()
            if is_target and not in_status:
                in_status = True
                h_in = h_val
                try: motivo = st_val.split("[")[0].replace(f"{palavra_chave.upper()} - Motivo:", "").replace(f"{palavra_chave.upper()} - ", "").strip()
                except: motivo = "N/A"
            elif not is_target and in_status:
                dur = format_tempo(diff_mins(h_in, h_val))
                num_maq = maq.replace("AFC ", "").replace("RTF ", "")
                texto += f"{num_maq} - {h_in} às {h_val} ({dur}) - Motivo: {motivo}\n"
                in_status = False
        if in_status:
            dur = format_tempo(diff_mins(h_in, datetime.now(FUSO_BR).strftime("%H:%M")))
            num_maq = maq.replace("AFC ", "").replace("RTF ", "")
            texto += f"{num_maq} - Desde {h_in} (Em andamento: {dur}) - Motivo: {motivo}\n"
    return texto if texto else "N/A\n\n"

def gerar_textos_fechamento(data_alvo, df_completo):
    df_ultimo_geral = df_completo.drop_duplicates(subset=['Maquina'], keep='last') if not df_completo.empty else df_completo
    setup_mask = df_completo['Status'].str.contains('PREPARAÇÃO|SEQUÊNCIA|AGUARDANDO|PREPARANDO', na=False)
    maquinas_com_setup = df_completo[setup_mask]['Maquina'].unique() if not df_completo.empty else []

    texto_padrao = f"*PLANTA AFIACAO E RETIFICA {data_alvo}*\n\n"
    texto_padrao += "*OCORRÊNCIAS DE QUEDA DE ENERGIA*\n\n"
    if not df_completo.empty:
        df_energia = df_completo[df_completo['Status'].str.contains('Energia', na=False, case=False)]
        if not df_energia.empty:
            quedas = df_energia[df_energia['Status'].str.contains("PARADA")]['Hora'].unique()
            retornos = df_energia[df_energia['Status'].str.contains("Restaurada")]['Hora'].unique()
            for i, h_q in enumerate(list(quedas)):
                h_r = list(retornos)[i] if i < len(list(retornos)) else "Sem retorno"
                duração = format_tempo(diff_mins(h_q, h_r)) if h_r != "Sem retorno" else "Em andamento"
                turno_queda = obter_turno_por_horario(h_q)
                texto_padrao += f"- Data: {data_alvo} | Turno: {turno_queda} | Queda às {h_q} | Restaurada às {h_r} (Duração: {duração})\n"
            texto_padrao += "\n"
        else: texto_padrao += "Nenhuma queda de energia registrada.\n\n"
    
    texto_padrao += "*MAQUINAS EM MANUTENÇÃO E PARADAS (DURAÇÃO)*\n\n"
    texto_padrao += "*MANUTENÇÃO*\n"
    texto_padrao += calcular_tempos_interrupcoes(df_completo, "MANUTENÇÃO") + "\n"
    texto_padrao += "*PARADAS*\n"
    texto_padrao += calcular_tempos_interrupcoes(df_completo, "PARADA") + "\n"

    texto_padrao += "*PREPARAÇÕES/AJUSTES*\n\n"
    str_rtf = processar_padrao(df_completo, maquinas_com_setup, "RTF")
    texto_padrao += str_rtf if str_rtf else "N/A\n\n"
    texto_padrao += "*AFIADORAS*\n\n"
    str_afc = processar_padrao(df_completo, maquinas_com_setup, "AFC")
    texto_padrao += str_afc if str_afc else "N/A\n\n"
    
    texto_padrao += "*EQUIPE / AUSÊNCIAS*\n\n"
    if os.path.exists(ARQUIVO_EQUIPE):
        df_eq = pd.read_csv(ARQUIVO_EQUIPE)
        if df_eq.empty: texto_padrao += "N/A\n\n"
        else:
            for _, row in df_eq.iterrows(): texto_padrao += f"{row['Nome']} - {row['Tipo'].upper()}\n"
            texto_padrao += "\n"
    else: texto_padrao += "N/A\n\n"

    texto_tempos = f"*RELATÓRIO DE DESEMPENHO E TEMPOS - {data_alvo}*\n\n"
    texto_tempos += "*RETIFICAS*\n\n"
    str_t_rtf = gerar_relatorio_tempos(df_completo, maquinas_com_setup, "RTF")
    texto_tempos += str_t_rtf if str_t_rtf else "Nenhuma preparação registrada.\n\n"
    texto_tempos += "*AFIADORAS*\n\n"
    str_t_afc = gerar_relatorio_tempos(df_completo, maquinas_com_setup, "AFC")
    texto_tempos += str_t_afc if str_t_afc else "Nenhuma preparação registrada.\n\n"

    return texto_padrao, texto_tempos

def executar_fechamento_silencioso(data_alvo, turno_alvo):
    df_completo = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
    
    texto_padrao, texto_tempos = gerar_textos_fechamento(data_alvo, df_completo)
    
    novo_hist = pd.DataFrame([{"Data": data_alvo, "Turno": turno_alvo, "Relatorio_Padrao": texto_padrao, "Relatorio_Tempos": texto_tempos}])
    if os.path.exists(ARQUIVO_HISTORICO): pd.concat([pd.read_csv(ARQUIVO_HISTORICO), novo_hist], ignore_index=True).to_csv(ARQUIVO_HISTORICO, index=False)
    else: novo_hist.to_csv(ARQUIVO_HISTORICO, index=False)
    
    if not df_completo.empty:
        df_eventos = df_completo.copy()
        df_eventos['Data_Registro'] = data_alvo
        df_eventos['Turno_Registro'] = turno_alvo
        if os.path.exists(ARQUIVO_HISTORICO_EVENTOS): pd.concat([pd.read_csv(ARQUIVO_HISTORICO_EVENTOS), df_eventos], ignore_index=True).to_csv(ARQUIVO_HISTORICO_EVENTOS, index=False)
        else: df_eventos.to_csv(ARQUIVO_HISTORICO_EVENTOS, index=False)
    
    df_novo = []
    for maq in df_completo['Maquina'].unique():
        df_maq = df_completo[df_completo['Maquina'] == maq]
        
        is_power_down = "Queda de Energia" in str(df_maq.iloc[-1]['Status'])
        
        last_prod_idx = -1
        for idx in df_maq.index:
            if "PRODUZINDO" in str(df_maq.loc[idx, 'Status']).upper(): last_prod_idx = idx
        
        if last_prod_idx != -1:
            df_recorte = df_maq.loc[last_prod_idx+1:].copy()
            if df_recorte.empty: df_recorte = df_maq.iloc[-1:].copy()
        else: 
            df_recorte = df_maq.copy()
        
        if not is_power_down:
            df_recorte = df_recorte[~df_recorte['Status'].str.contains("Queda de Energia", case=False, na=False)]
            df_recorte['Status'] = df_recorte['Status'].astype(str).str.replace(" [Energia Restaurada]", "", regex=False)
            
            if df_recorte.empty:
                last_row = df_maq.iloc[-1:].copy()
                last_row['Status'] = last_row['Status'].astype(str).str.replace(" [Energia Restaurada]", "", regex=False)
                df_recorte = pd.DataFrame([last_row])
                
        df_novo.append(df_recorte)
    
    if df_novo: pd.concat(df_novo).to_csv(ARQUIVO_DADOS, index=False)
    else: pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"]).to_csv(ARQUIVO_DADOS, index=False)
    
    if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)

def checar_e_auto_encerrar():
    curr_d, curr_t = get_turno_logico()
    
    if not os.path.exists(ARQUIVO_FECHAMENTO):
        pd.DataFrame([{"Data": curr_d, "Turno": curr_t}]).to_csv(ARQUIVO_FECHAMENTO, index=False)
        return
        
    try:
        df_fechamento = pd.read_csv(ARQUIVO_FECHAMENTO)
        last_d = str(df_fechamento.iloc[0]['Data'])
        last_t = str(df_fechamento.iloc[0]['Turno'])
    except:
        pd.DataFrame([{"Data": curr_d, "Turno": curr_t}]).to_csv(ARQUIVO_FECHAMENTO, index=False)
        return
        
    if last_d != curr_d or last_t != curr_t:
        executar_fechamento_silencioso(last_d, last_t)
        pd.DataFrame([{"Data": curr_d, "Turno": curr_t}]).to_csv(ARQUIVO_FECHAMENTO, index=False)

# --- FUNÇÕES DE AUTO-CORREÇÃO DE TURNOS E QUEDA DE ENERGIA ---
def verificar_virada_turno():
    if not os.path.exists(ARQUIVO_DADOS): return
    df = pd.read_csv(ARQUIVO_DADOS)
    if df.empty: return
    
    agora = datetime.now(FUSO_BR).time()
    turno_real = turno_atual_horario()
    
    if turno_real == "1° TURNO": hora_corte = "06:20"
    elif turno_real == "2° TURNO": hora_corte = "14:20"
    else: hora_corte = "22:20"
    
    novas_linhas = []
    maquinas = df['Maquina'].unique()
    
    for maq in maquinas:
        df_maq = df[df['Maquina'] == maq]
        ultimo_registro = df_maq.iloc[-1]
        st_atual = str(ultimo_registro['Status'])
        hora_registro = str(ultimo_registro['Hora'])
        
        if ("PREPARAÇÃO" in st_atual or "PREPARANDO" in st_atual or "SEQUÊNCIA" in st_atual) and ("[AGENDADO:" not in st_atual):
            mins_passados = diff_mins(hora_registro, datetime.now(FUSO_BR).strftime("%H:%M"))
            
            if mins_passados > 0: 
                if turno_real == "1° TURNO" and diff_mins(hora_registro, "06:20") > 0 and diff_mins("06:20", hora_registro) > 12*60: precisa_cortar = True
                elif turno_real == "2° TURNO" and diff_mins(hora_registro, "14:20") > 0 and diff_mins(hora_registro, "14:20") < 8*60: precisa_cortar = True
                elif turno_real == "3° TURNO" and diff_mins(hora_registro, "22:20") > 0 and diff_mins(hora_registro, "22:20") < 8*60: precisa_cortar = True
                else: precisa_cortar = False
                
                if precisa_cortar:
                    tags = extrair_tags_producao(st_atual)
                    novo_st = f"AGUARDANDO PREPARADOR [Corte de Turno] {tags}".strip()
                    novas_linhas.append({"Setor": ultimo_registro['Setor'], "Maquina": maq, "Operador": "SISTEMA", "Status": novo_st, "Hora": hora_corte})
                    
    if novas_linhas:
        df = pd.concat([df, pd.DataFrame(novas_linhas)], ignore_index=True)
        df.to_csv(ARQUIVO_DADOS, index=False)

def registrar_queda_energia(setor):
    lista_maquinas = TODAS_AFC if setor == "AFC" else TODAS_RTF
    df = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
    
    novas_linhas = []
    for maq_id in lista_maquinas:
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        st_atual = str(df_maq.iloc[-1]['Status']) if not df_maq.empty else "PRODUZINDO"
        
        if "Queda de Energia" not in st_atual:
            novas_linhas.append({"Setor": setor, "Maquina": maq_full, "Operador": st.session_state.get('operador', 'SISTEMA'), "Status": "PARADA - Motivo: Queda de Energia", "Hora": hora_br_str})
            
    if novas_linhas:
        df = pd.concat([df, pd.DataFrame(novas_linhas)], ignore_index=True)
        df.to_csv(ARQUIVO_DADOS, index=False)

def restaurar_queda_energia(setor):
    lista_maquinas = TODAS_AFC if setor == "AFC" else TODAS_RTF
    if not os.path.exists(ARQUIVO_DADOS): return
    df = pd.read_csv(ARQUIVO_DADOS)
    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
    
    novas_linhas = []
    for maq_id in lista_maquinas:
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        if not df_maq.empty:
            st_atual = str(df_maq.iloc[-1]['Status'])
            if "Queda de Energia" in st_atual:
                df_maq_valido = df_maq[~df_maq['Status'].str.contains("Queda de Energia", na=False)]
                st_recuperado = str(df_maq_valido.iloc[-1]['Status']) if not df_maq_valido.empty else "PRODUZINDO"
                st_restaurado = f"{st_recuperado} [Energia Restaurada]"
                novas_linhas.append({"Setor": setor, "Maquina": maq_full, "Operador": st.session_state.get('operador', 'SISTEMA'), "Status": st_restaurado, "Hora": hora_br_str})
                
    if novas_linhas:
        df = pd.concat([df, pd.DataFrame(novas_linhas)], ignore_index=True)
        df.to_csv(ARQUIVO_DADOS, index=False)

# --- FUNÇÕES DE ARMÁRIOS E ALERTAS GLOBAIS ---
def inicializar_armarios():
    precisa_criar = False
    dados_antigos = []
    
    if not os.path.exists(ARQUIVO_ARMARIOS):
        precisa_criar = True
    else:
        try:
            df_temp = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str)
            if "Retíficas 05 a 28" not in df_temp['Armario'].values or "Afiadoras 04 a 28" not in df_temp['Armario'].values:
                precisa_criar = True
                ocupadas = df_temp[df_temp['Status'] != 'VAZIO']
                dados_antigos = ocupadas.to_dict('records')
        except:
            precisa_criar = True
            
    if precisa_criar:
        dados = []
        afc_nums = sorted([int(m.split('-')[0]) for m in TODAS_AFC])
        rtf_nums_raw = sorted([int(m.split('-')[0]) for m in TODAS_RTF])
        
        rtf_nums = [m for m in rtf_nums_raw if m >= 5 and m not in [6, 17]]
        
        mapa_armarios = {
            "Afiadoras 04 a 28": [m for m in afc_nums if m <= 28],
            "Afiadoras 29 a 41": [m for m in afc_nums if m >= 29],
            "Retíficas 05 a 28": [m for m in rtf_nums if m <= 28],
            "Retíficas 29 a 42": [m for m in rtf_nums if m >= 29]
        }
        
        for arm, maquinas in mapa_armarios.items():
            for maq in maquinas:
                dados.append({"Armario": arm, "Posicao": str(maq), "Ordem": "", "Item": "", "Status": "VAZIO", "Data_Hora": "", "Observacao": ""})
                
        df_novo = pd.DataFrame(dados)
        
        for row in dados_antigos:
            pos = str(row.get('Posicao', ''))
            arm_antigo = str(row.get('Armario', ''))
            
            idx_exato = df_novo[df_novo['Posicao'] == pos].index
            if not idx_exato.empty:
                df_novo.loc[idx_exato[0], 'Ordem'] = str(row.get('Ordem', ''))
                df_novo.loc[idx_exato[0], 'Item'] = str(row.get('Item', ''))
                df_novo.loc[idx_exato[0], 'Status'] = str(row.get('Status', 'VAZIO'))
                df_novo.loc[idx_exato[0], 'Data_Hora'] = str(row.get('Data_Hora', ''))
                df_novo.loc[idx_exato[0], 'Observacao'] = str(row.get('Observacao', ''))
            else:
                tipo_maq = "Afiadoras" if "AFC" in arm_antigo else "Retíficas"
                idx_vazio = df_novo[(df_novo['Armario'].str.contains(tipo_maq)) & (df_novo['Status'] == 'VAZIO')].index
                if not idx_vazio.empty:
                    df_novo.loc[idx_vazio[0], 'Ordem'] = str(row.get('Ordem', ''))
                    df_novo.loc[idx_vazio[0], 'Item'] = str(row.get('Item', ''))
                    df_novo.loc[idx_vazio[0], 'Status'] = str(row.get('Status', 'VAZIO'))
                    df_novo.loc[idx_vazio[0], 'Data_Hora'] = str(row.get('Data_Hora', ''))
                    df_novo.loc[idx_vazio[0], 'Observacao'] = str(row.get('Observacao', ''))
        
        df_novo.to_csv(ARQUIVO_ARMARIOS, index=False)

def exibir_alertas_preset():
    if st.session_state.get('perfil') not in ['preset', 'adm']: return
    
    if os.path.exists(ARQUIVO_ALERTAS):
        df_alertas_toast = pd.read_csv(ARQUIVO_ALERTAS)
        if not df_alertas_toast.empty:
            ultimo_alerta = df_alertas_toast.iloc[-1]
            if 'ultimo_alerta_visto' not in st.session_state or st.session_state['ultimo_alerta_visto'] != str(ultimo_alerta.to_dict()):
                st.session_state['ultimo_alerta_visto'] = str(ultimo_alerta.to_dict())
                nome_prep = ultimo_alerta.get('Preparador', 'SISTEMA')
                st.toast(f"Retirada! {nome_prep} pegou a OP {ultimo_alerta['Ordem_Retirada']} da MAQ {ultimo_alerta['Maquina']}!", icon="🔔")

    agora_dt = datetime.now(FUSO_BR)
    alertas_urgentes = []
    if os.path.exists(ARQUIVO_DADOS) and os.path.exists(ARQUIVO_ARMARIOS):
        try:
            df_dados = pd.read_csv(ARQUIVO_DADOS).drop_duplicates(subset=['Maquina'], keep='last')
            df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Posicao': str, 'Status': str})
            
            for _, row in df_dados.iterrows():
                st_raw = str(row['Status'])
                maq_id_full = str(row['Maquina']) 
                
                if "[AGENDADO:" in st_raw or "AGENDADA PARA" in st_raw:
                    hora_alvo = ""
                    if "AGENDADA PARA" in st_raw:
                        try: hora_alvo = st_raw.split("AGENDADA PARA")[1].strip()
                        except: pass
                    elif "[AGENDADO:" in st_raw:
                        try: hora_alvo = st_raw.split("[AGENDADO:")[1].split("]")[0].strip()
                        except: pass
                        
                    if hora_alvo:
                        h_alvo_dt = datetime.strptime(hora_alvo, "%H:%M").replace(year=agora_dt.year, month=agora_dt.month, day=agora_dt.day, tzinfo=FUSO_BR)
                        
                        if h_alvo_dt < agora_dt and (agora_dt - h_alvo_dt).total_seconds() > 12 * 3600:
                            h_alvo_dt += timedelta(days=1)
                        elif h_alvo_dt > agora_dt and (h_alvo_dt - agora_dt).total_seconds() > 12 * 3600:
                            h_alvo_dt -= timedelta(days=1)
                        
                        delta_mins = (h_alvo_dt - agora_dt).total_seconds() / 60
                        
                        if -60 <= delta_mins <= 90:
                            maq_num_only = maq_id_full.split(" ")[1] 
                            gaveta_num = maq_num_only.split("-")[0] 
                            
                            gaveta_row = df_arm[df_arm['Posicao'] == gaveta_num]
                            if not gaveta_row.empty and gaveta_row.iloc[0]['Status'] == 'VAZIO':
                                alertas_urgentes.append({'maquina': maq_id_full, 'gaveta': gaveta_num, 'hora': hora_alvo, 'delta': int(delta_mins)})
        except: pass
        
    if alertas_urgentes:
        html_alertas = "<div class='alerta-pisca'>"
        html_alertas += "<h4 style='margin-top:0; color:#fca5a5;'>🚨 ALERTA DE PREPARAÇÃO IMINENTE</h4>"
        for alerta in sorted(alertas_urgentes, key=lambda x: x['delta']):
            tempo_txt = f"em {alerta['delta']} min" if alerta['delta'] >= 0 else f"atrasado há {abs(alerta['delta'])} min"
            html_alertas += f"<p style='color:#fee2e2; margin-bottom:5px; font-size:15px;'>• <b>{alerta['maquina']}</b> agendada para <b>{alerta['hora']}</b> ({tempo_txt}) -> <b>GAVETA {alerta['gaveta']} VAZIA!</b></p>"
        html_alertas += "</div>"
        st.markdown(html_alertas, unsafe_allow_html=True)

def dar_baixa_armario(ordem_alvo, operador_nome="SISTEMA"):
    if not ordem_alvo or not str(ordem_alvo).strip() or not os.path.exists(ARQUIVO_ARMARIOS): return
    try:
        ordem_formatada = str(ordem_alvo).strip().upper().replace(".0", "")
        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str, 'Armario': str, 'Observacao': str})
        if 'Item' not in df_arm.columns: df_arm['Item'] = ""
        if 'Observacao' not in df_arm.columns: df_arm['Observacao'] = ""
        
        df_arm['Ordem_busca'] = df_arm['Ordem'].astype(str).str.strip().str.upper().str.replace(".0", "", regex=False)
        idx_ordem = df_arm[df_arm['Ordem_busca'] == ordem_formatada].index
        if not idx_ordem.empty:
            
            item_removido = str(df_arm.loc[idx_ordem[0], 'Item'])
            maq_removida = str(df_arm.loc[idx_ordem[0], 'Posicao'])
            armario_removido = str(df_arm.loc[idx_ordem[0], 'Armario'])
            
            hora_br_str = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")
            novo_alerta = {
                "Data_Hora": hora_br_str, 
                "Armario": armario_removido, 
                "Maquina": maq_removida, 
                "Ordem_Retirada": ordem_formatada, 
                "Item": item_removido,
                "Preparador": operador_nome
            }
            
            if os.path.exists(ARQUIVO_ALERTAS):
                df_alerta = pd.read_csv(ARQUIVO_ALERTAS)
                df_alerta = pd.concat([df_alerta, pd.DataFrame([novo_alerta])], ignore_index=True)
                df_alerta.tail(100).to_csv(ARQUIVO_ALERTAS, index=False)
            else:
                pd.DataFrame([novo_alerta]).to_csv(ARQUIVO_ALERTAS, index=False)
            
            df_arm.loc[idx_ordem, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao']] = ["", "", 'VAZIO', datetime.now(FUSO_BR).strftime("%H:%M"), ""]
            df_arm = df_arm.drop(columns=['Ordem_busca'])
            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
    except: pass

def buscar_item_por_ordem(ordem_alvo):
    if not ordem_alvo or not os.path.exists(ARQUIVO_ARMARIOS): return "SEM CADASTRO"
    try:
        ordem_formatada = str(ordem_alvo).strip().upper().replace(".0", "")
        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str)
        df_arm['Ordem_busca'] = df_arm['Ordem'].astype(str).str.strip().str.upper().str.replace(".0", "", regex=False)
        match = df_arm[df_arm['Ordem_busca'] == ordem_formatada]
        if not match.empty:
            return str(match.iloc[0]['Item']).strip().replace(".0", "")
    except: pass
    return "SEM CADASTRO"

def get_status_icon(status_str):
    if "AGUARDANDO PREPARADOR" in status_str: return "🟠"
    elif "AGENDADO" in status_str or "AGENDADA" in status_str: return "🔵"
    elif "SEQUÊNCIA" in status_str: return "🟣"
    elif "PREPARAÇÃO" in status_str or "PREPARANDO" in status_str: return "🟡"
    elif "MANUTENÇÃO" in status_str: return "🛠️"
    elif "PARADA" in status_str: return "🔴"
    else: return "🟢"

def extrair_tags_producao(status_str):
    tags = ""
    for marcador in ["[Item Atual:", "[Novo Item:", "[Ordem:", "[Item:", "[Pçs/Hora:", "[Obs:", "[Fim Previsto:"]:
        if marcador in status_str:
            try: tags += f" {marcador} {status_str.split(marcador)[1].split(']')[0].strip()}]"
            except: pass
    return tags.strip()

# --- INICIALIZAÇÃO DO SESSION STATE ---
if 'tela_atual' not in st.session_state: st.session_state['tela_atual'] = 'login'
if 'operador' not in st.session_state: st.session_state['operador'] = ''
if 'turno' not in st.session_state: st.session_state['turno'] = ''
if 'setor_usuario' not in st.session_state: st.session_state['setor_usuario'] = ''
if 'perfil' not in st.session_state: st.session_state['perfil'] = '' 
if 'celula_selecionada' not in st.session_state: st.session_state['celula_selecionada'] = None
if 'maq_ativa' not in st.session_state: st.session_state['maq_ativa'] = None
if 'gaveta_selecionada' not in st.session_state: st.session_state['gaveta_selecionada'] = None
if 'logout_realizado' not in st.session_state: st.session_state['logout_realizado'] = False
if 'fila_prev_sel' not in st.session_state: st.session_state['fila_prev_sel'] = None
if 'setor_prev_sel' not in st.session_state: st.session_state['setor_prev_sel'] = None

# --- RESTAURAÇÃO DE LOGIN POR COOKIE ---
if not st.session_state['operador'] and not st.session_state['logout_realizado']:
    if cookies_salvos and "user_logado" in cookies_salvos:
        st.session_state['operador'] = cookies_salvos["user_logado"]
        st.session_state['turno'] = cookies_salvos.get("user_turno", "")
        st.session_state['setor_usuario'] = cookies_salvos.get("user_setor", "")
        st.session_state['perfil'] = cookies_salvos.get("user_perfil", "")
        st.session_state['tela_atual'] = 'menu'
        st.rerun() 

def mudar_tela(nome_tela):
    st.session_state['tela_atual'] = nome_tela
    st.session_state['celula_selecionada'] = None
    st.session_state['maq_ativa'] = None
    st.session_state['gaveta_selecionada'] = None
    st.session_state['fila_prev_sel'] = None
    st.session_state['setor_prev_sel'] = None
    st.rerun()

def ler_status_atual():
    checar_e_auto_encerrar()
    verificar_virada_turno()
    if not os.path.exists(ARQUIVO_DADOS): return {}
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        status_calculado = {}
        agora_br = datetime.now(FUSO_BR)
        agora_str = agora_br.strftime("%H:%M")
        
        df_ultimo = df.drop_duplicates(subset=['Maquina'], keep='last')
        for _, row in df_ultimo.iterrows():
            maq = row['Maquina']
            st_raw = str(row['Status']).replace(" [Energia Restaurada]", "") 
            
            if "AGENDADA PARA" in st_raw:
                try:
                    hora_alvo = st_raw.split("AGENDADA PARA")[1].strip()
                    tipo_agendado = st_raw.split(" AGENDADA PARA")[0]
                    h_agora = datetime.strptime(agora_str, "%H:%M")
                    h_alvo_dt = datetime.strptime(hora_alvo, "%H:%M")
                    if h_alvo_dt < h_agora and (h_agora - h_alvo_dt).total_seconds() > 12 * 3600: h_alvo_dt += timedelta(days=1)
                        
                    if h_agora < h_alvo_dt: status_calculado[maq] = f"{tipo_agendado} AGENDADA PARA {hora_alvo}"
                    else: 
                        sug = f" [Prep. Sugerido: {st_raw.split('[Prep. Sugerido:')[1].split(']')[0].strip()}]" if "[Prep. Sugerido:" in st_raw else ""
                        tags = extrair_tags_producao(st_raw)
                        status_calculado[maq] = f"AGUARDANDO PREPARADOR{sug} {tags}".strip()
                except: status_calculado[maq] = st_raw
            elif "[AGENDADO:" in st_raw:
                try:
                    hora_alvo = st_raw.split("[AGENDADO:")[1].split("]")[0].strip()
                    tipo_agendado = st_raw.split(" [AGENDADO:")[0]
                    h_agora = datetime.strptime(agora_str, "%H:%M")
                    h_alvo_dt = datetime.strptime(hora_alvo, "%H:%M")
                    if h_alvo_dt < h_agora and (h_agora - h_alvo_dt).total_seconds() > 12 * 3600: h_alvo_dt += timedelta(days=1)
                        
                    if h_agora < h_alvo_dt: status_calculado[maq] = f"{tipo_agendado} AGENDADA PARA {hora_alvo}"
                    else: 
                        sug = f" [Prep. Sugerido: {st_raw.split('[Prep. Sugerido:')[1].split(']')[0].strip()}]" if "[Prep. Sugerido:" in st_raw else ""
                        tags = extrair_tags_producao(st_raw)
                        status_calculado[maq] = f"AGUARDANDO PREPARADOR{sug} {tags}".strip()
                except: status_calculado[maq] = st_raw
            else: status_calculado[maq] = st_raw
        return status_calculado
    except: return {}

def obter_info_maquina(maq_id, setor):
    if not os.path.exists(ARQUIVO_DADOS): return None
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        if not df_maq.empty: return df_maq.iloc[-1].to_dict()
    except: pass
    return None

def salvar_csv(dados, arquivo):
    df_novo = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df_existente = pd.read_csv(arquivo)
        df_existente = pd.concat([df_existente, df_novo], ignore_index=True)
        df_existente.to_csv(arquivo, index=False)
    else: df_novo.to_csv(arquivo, index=False)

def ordenar_maquinas(lista_maquinas):
    def natural_sort_key(s): return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
    return sorted(lista_maquinas, key=natural_sort_key)

def painel_controle_maquina(maq_id, setor):
    st.markdown("<script>window.scrollTo({ top: 0, behavior: 'smooth' });</script>", unsafe_allow_html=True)
    
    with st.container():
        col_t, col_f = st.columns([8, 1])
        
        if setor == 'RTF':
            tipo_atual = get_tipo_cnc(maq_id)
            col_t.markdown(f"<h4 style='color: #2DD4BF !important; margin:0;'>⚙️ MÁQUINA: {maq_id} <span style='font-size:13px; color:#A1A1AA; font-weight:normal;'>({tipo_atual})</span></h4>", unsafe_allow_html=True)
        else:
            col_t.markdown(f"<h4 style='color: #2DD4BF !important; margin:0;'>⚙️ MÁQUINA: {maq_id}</h4>", unsafe_allow_html=True)
            
        if col_f.button("✕", key=f"fechar_{maq_id}"):
            st.session_state['maq_ativa'] = None
            st.rerun()

        if setor == 'RTF':
            with st.expander("🔄 Alterar Tipo CNC desta Máquina"):
                c_tipo1, c_tipo2 = st.columns([3, 2])
                novo_tipo = c_tipo1.selectbox("Definir como:", ["RTF_CNC3 (Normal)", "RTF_CNC2 (Facetadora)", "RTF_CNC1 (Centerless)"], index=0)
                
                if c_tipo2.button("💾 Salvar Tipo", use_container_width=True):
                    tipo_limpo = novo_tipo.split(" ")[0]
                    set_tipo_cnc(maq_id, tipo_limpo)
                    st.success(f"✅ Máquina alterada para {tipo_limpo}!")
                    time.sleep(0.5)
                    st.rerun()
            
        status_dict = ler_status_atual()
        status_atual = status_dict.get(f"{setor} {maq_id}", "PRODUZINDO")
        info = obter_info_maquina(maq_id, setor)
        hora_atual = info.get('Hora', '--:--') if info else ''
        
        timer_str = ""
        if ("MANUTENÇÃO" in status_atual or "PREPARAÇÃO" in status_atual or "SEQUÊNCIA" in status_atual or "PREPARANDO" in status_atual) and info:
            try:
                dt_reg = datetime.strptime(f"{datetime.now(FUSO_BR).strftime('%Y-%m-%d')} {hora_atual}", "%Y-%m-%d %H:%M")
                tempo_decorrido = datetime.now(FUSO_BR) - dt_reg.replace(tzinfo=FUSO_BR)
                minutos = int(tempo_decorrido.total_seconds() // 60)
                if "MANUTENÇÃO" in status_atual: timer_str = f" (Em manutenção há {minutos} min)"
                else: timer_str = f" (Em preparação há {minutos} min)"
            except: pass

        st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
        if "AGUARDANDO PREPARADOR" in status_atual: st.warning(f"🟠 Status Atual: {status_atual}")
        elif "AGENDADO" in status_atual or "AGENDADA" in status_atual: st.info(f"🔵 Status: {status_atual}")
        elif "PREPARANDO" in status_atual: st.info(f"🟡 Status Atual: {status_atual} desde {hora_atual}{timer_str}")
        elif "SEQUÊNCIA" in status_atual: st.info(f"🟣 Status Atual: {status_atual} desde {hora_atual}{timer_str}")
        elif "PRODUZINDO" in status_atual: st.success(f"🟢 Status Atual: {status_atual}")
        elif "PARADA" in status_atual: st.error(f"🔴 Status Atual: Paralisada desde {hora_atual}")
        elif "MANUTENÇÃO" in status_atual: st.warning(f"🛠️ Status Atual: Em Manutenção desde {hora_atual}{timer_str}")
        else: st.warning(f"🟡 Status Atual: {status_atual} desde {hora_atual}{timer_str}")
            
        flow_key = f"flow_{maq_id}"
        is_setup_ativo = "PREPARANDO" in status_atual or "SEQUÊNCIA" in status_atual
        is_espera = "AGUARDANDO PREPARADOR" in status_atual or "AGENDADO" in status_atual or "AGENDADA" in status_atual
        
        if flow_key not in st.session_state:
            if is_espera: st.session_state[flow_key] = "acoes_espera"
            else: st.session_state[flow_key] = "pergunta"
                
        st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        
        if is_setup_ativo and st.session_state[flow_key] == "pergunta":
            with st.form(f"form_fast_track_{maq_id}"):
                st.markdown(f"<p style='text-align: center; font-weight: 600;'>O setup desta máquina foi finalizado?</p>", unsafe_allow_html=True)
                obs_fast = st.text_input("Observação / Justificativa (Opcional):", placeholder="Ex: Demora por falta de ferramenta...")
                
                c1, c2, c3 = st.columns(3)
                btn_sim = c1.form_submit_button("✅ Sim (Produzir)")
                btn_assumir = c2.form_submit_button("🔄 Assumir")
                btn_alt = c3.form_submit_button("⚠️ Alterar")
                
                if btn_sim:
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                    info_atual = obter_info_maquina(maq_id, setor)
                    st_atual = str(info_atual['Status']) if info_atual else ""
                    
                    tags_prod = extrair_tags_producao(st_atual)
                    tags_prod = tags_prod.replace("[Novo Item:", "[Item:")
                    tags_prod = tags_prod.replace("[Item Atual:", "[Item:")
                    
                    st_final = f"PRODUZINDO {tags_prod}".strip()
                    if obs_fast.strip(): st_final += f" [Obs: {obs_fast.strip()}]"
                    
                    if "[Ordem:" in st_atual:
                        op_ext = st_atual.split("[Ordem:")[1].split("]")[0].strip()
                        dar_baixa_armario(op_ext, st.session_state.get('operador', 'SISTEMA'))
                    
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.rerun()
                    
                if btn_assumir: st.session_state[flow_key] = "assumir_prep"; st.rerun()
                if btn_alt: st.session_state[flow_key] = "mudanca_status"; st.rerun()

        elif st.session_state[flow_key] == "assumir_prep":
            with st.form(f"form_assumir_{maq_id}"):
                st.markdown("🧑‍🔧 **Assumir Setup de Outro Operador**")
                novo_nome = st.text_input("Seu Nome para Assumir:", value=st.session_state['operador'])
                if st.form_submit_button("🚀 ASSUMIR PREPARAÇÃO", type="primary"):
                    if novo_nome.strip():
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        info_atual = obter_info_maquina(maq_id, setor)
                        tags_prod = extrair_tags_producao(str(info_atual['Status'])) if info_atual else ""
                        
                        st_andamento = f"PREPARANDO [Prep: {novo_nome.strip().upper()}] [Assumido] {tags_prod}".strip()
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_andamento, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Setup assumido com sucesso!")
                        time.sleep(0.5)
                        st.rerun()

        elif st.session_state[flow_key] == "pergunta" and not is_setup_ativo:
            st.markdown(f"<p style='text-align: center; font-weight: 600;'>Esta máquina ainda está com o status atual?</p>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("✅ Sim, continuar", key=f"s_{maq_id}", use_container_width=True):
                st.session_state['maq_ativa'] = None
                if flow_key in st.session_state: del st.session_state[flow_key]
                st.rerun()
            if c2.button("❌ Não, alterar", key=f"n_{maq_id}", use_container_width=True):
                st.session_state[flow_key] = "mudanca_status"
                st.rerun()
                
        elif st.session_state[flow_key] == "mudanca_status":
            st.markdown("<p style='font-size: 12px; font-weight: bold; color: #14B8A6;'>SELECIONE O NOVO STATUS:</p>", unsafe_allow_html=True)
            if st.button("🟢 PRODUZINDO", key=f"st_prod_{maq_id}", use_container_width=True):
                info_atual = obter_info_maquina(maq_id, setor)
                st_atual = str(info_atual['Status']) if info_atual else ""
                
                # Permite voltar de Manutenção ou Parada mantendo a OP sem dar baixa nova
                if "[Ordem:" in st_atual:
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                    tags_prod = extrair_tags_producao(st_atual)
                    tags_prod = tags_prod.replace("[Novo Item:", "[Item:")
                    tags_prod = tags_prod.replace("[Item Atual:", "[Item:")
                    tags_prod = re.sub(r' \[Fim Previsto:.*?\]', '', tags_prod)
                    
                    st_final = f"PRODUZINDO {tags_prod}".strip()
                    
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.rerun()
                else:
                    st.session_state[flow_key] = "detalhe_prod"
                    st.rerun()
                    
            if st.button("🟡 PREPARAÇÃO / SEQUÊNCIA", key=f"st_prep_{maq_id}", use_container_width=True): st.session_state[flow_key] = "detalhe_prep"; st.rerun()
            if st.button("🛠️ MANUTENÇÃO", key=f"st_man_{maq_id}", use_container_width=True): st.session_state[flow_key] = "detalhe_man"; st.rerun()
            if st.button("🔴 PARADA", key=f"st_par_{maq_id}", use_container_width=True): st.session_state[flow_key] = "detalhe_parada"; st.rerun()

        elif st.session_state[flow_key] == "detalhe_prod":
            with st.form(f"form_prod_{maq_id}"):
                st.markdown("🟢 **Apontamento de Produção**")
                info_atual = obter_info_maquina(maq_id, setor)
                st_atual = str(info_atual['Status']) if info_atual else ""
                op_pre, item_pre = "", ""
                
                if "[Ordem:" in st_atual: op_pre = st_atual.split("[Ordem:")[1].split("]")[0].strip()
                if "[Novo Item:" in st_atual: item_pre = st_atual.split("[Novo Item:")[1].split("]")[0].strip()
                elif "[Item:" in st_atual: item_pre = st_atual.split("[Item:")[1].split("]")[0].strip()
                elif "[Item Atual:" in st_atual: item_pre = st_atual.split("[Item Atual:")[1].split("]")[0].strip()
                
                ordem = st.text_input("Ordem de Produção (OP):", value=op_pre, placeholder="Ex: 987654")
                item = st.text_input("Item:", value=item_pre, placeholder="Ex: 313324")
                pcs_hora = st.text_input("Produção (Pçs/Hora) - Opcional:", placeholder="Ex: 150")
                obs = st.text_input("Observação / Justificativa (Opcional):", placeholder="Ex: Ajuste fino demorado...")
                
                if st.form_submit_button("🚀 INICIAR PRODUÇÃO", type="primary"):
                    if not ordem.strip() or not item.strip():
                        st.error("⚠️ A Ordem e o Item são obrigatórios!")
                    else:
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        
                        item_limpo = item.strip().upper().replace(".0", "")
                        ordem_limpa = ordem.strip().upper().replace(".0", "")
                        
                        st_final = f"PRODUZINDO [Ordem: {ordem_limpa}] [Item: {item_limpo}]"
                        if pcs_hora.strip(): st_final += f" [Pçs/Hora: {pcs_hora.strip()}]"
                        if obs.strip(): st_final += f" [Obs: {obs.strip()}]"
                        
                        dar_baixa_armario(ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Apontamento registrado! Máquina em Produção.")
                        time.sleep(0.5)
                        st.rerun()

        elif st.session_state[flow_key] == "detalhe_parada":
            with st.form(f"form_par_{maq_id}"):
                st.markdown("🔴 **Registro de Máquina Parada**")
                motivo = st.selectbox("Motivo da Parada:", ["Falta de Operador", "Falta de Material", "Ajuste de Processo", "Manutenção Corretiva", "Outros"])
                op_faltante = st.text_input("Nome do Operador Faltante (Se aplicável):", placeholder="Ex: João Silva")
                detalhe = st.text_input("Outros Detalhes (Opcional):")
                
                if st.form_submit_button("💾 Registrar Parada", type="primary"):
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                    mot_final = motivo
                    if detalhe.strip(): mot_final += f" - {detalhe.strip()}"
                    if op_faltante.strip() and motivo == "Falta de Operador": mot_final += f" [Op. Faltante: {op_faltante.strip().upper()}]"
                        
                    info_atual = obter_info_maquina(maq_id, setor)
                    st_atual = str(info_atual['Status']) if info_atual else ""
                    tags_prod = extrair_tags_producao(st_atual)
                        
                    st_final = f"PARADA - Motivo: {mot_final} {tags_prod}".strip()
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.success("✅ Máquina registrada como PARADA!")
                    time.sleep(0.5)
                    st.rerun()

        elif st.session_state[flow_key] == "detalhe_prep":
            with st.form(f"form_prep_{maq_id}"):
                st.markdown("⚙️ **Configuração de Preparação / Agendamento**")
                
                info_atual = obter_info_maquina(maq_id, setor)
                st_atual = str(info_atual['Status']) if info_atual else ""
                
                hora_pre_fill = ""
                if "AGENDADA PARA" in st_atual:
                    try: hora_pre_fill = st_atual.split("AGENDADA PARA")[1].strip()
                    except: pass
                elif "[AGENDADO:" in st_atual:
                    try: hora_pre_fill = st_atual.split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "[Fim Previsto:" in st_atual:
                    try: hora_pre_fill = st_atual.split("[Fim Previsto:")[1].split("]")[0].strip()
                    except: pass
                    
                hora_relatorio = st.text_input("⏰ Horário Alvo (Aparecerá no Relatório):", value=hora_pre_fill, placeholder="Ex: 12:30")
                is_agendado = st.toggle("Marcar como Agendamento Futuro", value=True)
                prep_sugerido = st.text_input("🧑‍🔧 Sugerir Preparador (Opcional):", placeholder="Ex: Lucas")
                
                op_pre, item_pre = "", ""
                if "[Ordem:" in st_atual: op_pre = st_atual.split("[Ordem:")[1].split("]")[0].strip()
                if "[Item Atual:" in st_atual: item_pre = st_atual.split("[Item Atual:")[1].split("]")[0].strip()
                elif "[Novo Item:" in st_atual: item_pre = st_atual.split("[Novo Item:")[1].split("]")[0].strip()
                elif "[Item:" in st_atual: item_pre = st_atual.split("[Item:")[1].split("]")[0].strip()
                
                st.markdown("📦 **Dados do Item**")
                ordem_atual = st.text_input("Ordem Atual (OP):", value=op_pre, placeholder="Ex: 987654")
                item_atual = st.text_input("Item Atual (Na Máquina):", value=item_pre, placeholder="Ex: 313324")
                
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                
                if setor == "AFC":
                    tipo_afc = st.radio("Selecione o Status:", ["PREPARAÇÃO", "SEQUÊNCIA"], horizontal=True)
                    troca_rebolo = st.toggle("Troca de Rebolo")
                else:
                    tipo_prep = st.radio("Setup:", ["HASTE", "GUIA"], horizontal=True)
                    troca_diametro = False
                    if tipo_prep == "HASTE": troca_diametro = st.toggle("Troca de Diâmetro")
                    troca_rebolo = st.toggle("Troca de Rebolo")
                
                if st.form_submit_button("💾 Salvar Registro", type="primary"):
                    if not hora_relatorio.strip():
                        st.error("⚠️ O campo de horário é obrigatório!")
                    else:
                        if setor == "AFC":
                            st_final = tipo_afc
                            if troca_rebolo: st_final += " (C/ Rebolo)"
                        else:
                            st_final = f"PREPARAÇÃO - {tipo_prep}"
                            if tipo_prep == "HASTE" and troca_diametro: st_final += " (C/ Diâmetro)"
                            if troca_rebolo: st_final += " (C/ Rebolo)"
                            
                        if prep_sugerido.strip(): st_final += f" [Prep. Sugerido: {prep_sugerido.strip().upper()}]"

                        if is_agendado and hora_relatorio.strip(): st_final += f" [AGENDADO:{hora_relatorio.strip()}]"
                        else: st_final = f"AGUARDANDO PREPARADOR - {st_final}"
                        
                        ordem_limpa = ordem_atual.strip().upper().replace(".0", "")
                        item_limpo = item_atual.strip().upper().replace(".0", "")

                        if ordem_limpa: st_final += f" [Ordem: {ordem_limpa}]"
                        if item_limpo: st_final += f" [Item Atual: {item_limpo}]"
                        
                        if ordem_limpa: dar_baixa_armario(ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                            
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_relatorio.strip()}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Registro salvo com sucesso!")
                        time.sleep(0.5)
                        st.rerun()

        elif st.session_state[flow_key] == "acoes_espera":
            with st.form(f"form_espera_{maq_id}"):
                st.markdown("🧑‍🔧 **Assumir ou Sugerir Preparador**")
                
                sug_nome = ""
                if "[Prep. Sugerido:" in status_atual:
                    try: sug_nome = status_atual.split("[Prep. Sugerido:")[1].split("]")[0].strip()
                    except: pass
                    
                nome_input = st.text_input("Nome do Preparador:", value=sug_nome if sug_nome else "")
                
                is_guia = "GUIA" in status_atual
                is_seq = "SEQUÊNCIA" in status_atual
                is_comum = not is_guia and not is_seq
                
                st.markdown("📦 **Dados da Preparação**")
                nova_ordem_input = ""
                
                if is_comum:
                    nova_ordem_input = st.text_input("Nova Ordem (OP) Entrando:", placeholder="Ex: 987654")
                    st.info("ℹ️ O Item da peça será puxado automaticamente do armário baseado nesta OP.")
                elif is_seq:
                    nova_ordem_input = st.text_input("Nova Ordem (OP) Entrando:", placeholder="Ex: 987654")
                    st.info("ℹ️ Sequência: O Item atual será mantido. Informe apenas a nova OP.")
                elif is_guia:
                    st.info("ℹ️ Preparação de Guia: A Ordem e o Item atuais serão mantidos. Nenhuma nova OP é necessária.")
                
                st.markdown("⏰ **Adiar Agendamento (Opcional)**")
                col_adiar1, col_adiar2 = st.columns([3, 2])
                novo_horario_adiar = col_adiar1.text_input("Novo Horário:", placeholder="Ex: 14:30")
                btn_adiar = col_adiar2.form_submit_button("⏳ Adiar Agendamento")
                
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                
                bloquear_inicio = False
                msg_bloqueio = ""
                if "[AGENDADO:" in status_atual or "AGENDADA PARA" in status_atual:
                    try:
                        if "AGENDADA PARA" in status_atual:
                            hora_agend = status_atual.split("AGENDADA PARA")[1].strip()
                        else:
                            hora_agend = status_atual.split("[AGENDADO:")[1].split("]")[0].strip()
                        turno_agend = obter_turno_por_horario(hora_agend)
                        if turno_agend != st.session_state.get('turno') and st.session_state.get('perfil') != 'adm':
                            bloquear_inicio = True
                            msg_bloqueio = f"⚠️ Setup programado para o {turno_agend}. Apenas operadores daquele turno podem iniciar."
                    except: pass

                if bloquear_inicio:
                    st.warning(msg_bloqueio)
                
                c1, c2, c3 = st.columns(3)
                btn_sugerir = c1.form_submit_button("💡 Apenas Sugerir")
                btn_iniciar = c2.form_submit_button("🚀 INICIAR", type="primary", disabled=bloquear_inicio)
                btn_alterar = c3.form_submit_button("⚠️ Alterar Status")
                
                if btn_alterar:
                    st.session_state[flow_key] = "mudanca_status"
                    st.rerun()
                
                if btn_adiar:
                    if novo_horario_adiar.strip():
                        info_atual = obter_info_maquina(maq_id, setor)
                        if info_atual:
                            raw_st = str(info_atual['Status'])
                            if "AGENDADA PARA" in raw_st:
                                raw_st = re.sub(r'AGENDADA PARA \d{2}:\d{2}', f"AGENDADA PARA {novo_horario_adiar.strip()}", raw_st)
                            elif "[AGENDADO:" in raw_st: 
                                raw_st = re.sub(r'\[AGENDADO:.*?\]', f"[AGENDADO:{novo_horario_adiar.strip()}]", raw_st)
                            else: raw_st += f" [AGENDADO:{novo_horario_adiar.strip()}]"
                            
                            salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": novo_horario_adiar.strip()}, ARQUIVO_DADOS)
                            st.session_state['maq_ativa'] = None
                            del st.session_state[flow_key]
                            st.success(f"✅ Agendamento adiado para {novo_horario_adiar.strip()}!")
                            time.sleep(0.5)
                            st.rerun()
                    else: st.error("⚠️ Informe o novo horário para adiar!")
                    
                if btn_sugerir:
                    if nome_input.strip():
                        info_atual = obter_info_maquina(maq_id, setor)
                        if info_atual:
                            raw_st = str(info_atual['Status'])
                            raw_st = re.sub(r' \[Prep\. Sugerido:.*?\]', '', raw_st)
                            if "AGENDADA PARA" in raw_st:
                                hora_agend = raw_st.split("AGENDADA PARA")[1].strip()
                                st_base = raw_st.split(" AGENDADA PARA")[0]
                                raw_st = f"{st_base} [Prep. Sugerido: {nome_input.strip().upper()}] [AGENDADO:{hora_agend}]"
                            elif "[AGENDADO:" in raw_st: 
                                raw_st = raw_st.replace(" [AGENDADO:", f" [Prep. Sugerido: {nome_input.strip().upper()}] [AGENDADO:")
                            else: raw_st += f" [Prep. Sugerido: {nome_input.strip().upper()}]"
                            
                            hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                            salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": hora_br_str}, ARQUIVO_DADOS)
                            st.session_state['maq_ativa'] = None
                            del st.session_state[flow_key]
                            st.success("✅ Sugestão de preparador atualizada!")
                            time.sleep(0.5)
                            st.rerun()
                    else: st.error("⚠️ Informe um nome para sugerir!")
                        
                if btn_iniciar:
                    if is_comum and not nova_ordem_input.strip():
                        st.error("⚠️ Para INICIAR a preparação, informe a Nova Ordem (OP)!")
                    elif is_seq and not nova_ordem_input.strip():
                        st.error("⚠️ Para INICIAR a Sequência, informe a Nova Ordem (OP)!")
                    else:
                        nome_final = nome_input if nome_input.strip() else st.session_state['operador']
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        
                        info_atual = obter_info_maquina(maq_id, setor)
                        tags_prod = extrair_tags_producao(str(info_atual['Status'])) if info_atual else ""
                        
                        if is_comum:
                            tags_prod = re.sub(r' \[Ordem:.*?\]', '', tags_prod) 
                            tags_prod = re.sub(r' \[Novo Item:.*?\]', '', tags_prod) 
                            tags_prod = re.sub(r' \[Item:.*?\]', '', tags_prod) 
                            tags_prod = re.sub(r' \[Item Atual:.*?\]', '', tags_prod) 
                        elif is_seq:
                            tags_prod = re.sub(r' \[Ordem:.*?\]', '', tags_prod)
                        
                        st_andamento = f"PREPARANDO [Prep: {nome_final.strip().upper()}] {tags_prod}".strip()
                        
                        nova_ordem_limpa = nova_ordem_input.strip().upper().replace(".0", "")

                        if is_comum:
                            item_buscado = buscar_item_por_ordem(nova_ordem_limpa)
                            st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                            st_andamento += f" [Novo Item: {item_buscado}]"
                            dar_baixa_armario(nova_ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                        elif is_seq:
                            st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                            dar_baixa_armario(nova_ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                            
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_andamento, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        
                        if is_guia: st.success("✅ Preparação iniciada! Setup mantido sem alterar OP ou Item.")
                        elif is_seq: st.success("✅ Sequência iniciada! OP atualizada e Item mantido.")
                        else: st.success("✅ Preparação iniciada! OP e Item liberados do armário.")
                        time.sleep(0.5)
                        st.rerun()

        elif st.session_state[flow_key] == "detalhe_man":
            with st.form(f"form_man_{maq_id}"):
                st.markdown("🛠️ **Registro de Manutenção**")
                motivo = st.text_input("Motivo da Manutenção (Obrigatório):", placeholder="Descreva o problema...")
                if st.form_submit_button("💾 Registrar Manutenção", type="primary"):
                    if not motivo.strip(): st.error("⚠️ O motivo é obrigatório!")
                    else:
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        info_atual = obter_info_maquina(maq_id, setor)
                        st_atual = str(info_atual['Status']) if info_atual else ""
                        tags_prod = extrair_tags_producao(st_atual)
                        
                        st_final = f"MANUTENÇÃO - Motivo: {motivo} {tags_prod}".strip()
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Registrado!")
                        time.sleep(0.5)
                        st.rerun()

def tela_login():
    st.markdown("<h2 style='text-align: center; color: #14B8A6 !important; margin-top: 30px;'>🏭 RELATORIO AFIAÇÃO</h2>", unsafe_allow_html=True)
    with st.container():
        cod = st.text_input("Digite seu codigo de Acesso:", type="password", placeholder="Digite aqui...")
        nome = st.text_input("Nome do Colaborador / RE:", placeholder="Digite seu nome...")
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        if st.button("ACESSAR SISTEMA", use_container_width=True, type="primary"):
            codigos_validos = {
                "9999": ("GERAL", "GERÊNCIA", "adm"),
                "1010": ("1° TURNO", "TECNICO", "preparador"), "2020": ("2° TURNO", "TECNICO", "preparador"), "3030": ("3° TURNO", "TECNICO", "preparador"),
                "1123": ("1° TURNO", "AFC", "preparador"), "2123": ("2° TURNO", "AFC", "preparador"), "3123": ("3° TURNO", "AFC", "preparador"),
                "1234": ("1° TURNO", "RTF", "preparador"), "2234": ("2° TURNO", "RTF", "preparador"), "3234": ("3° TURNO", "RTF", "preparador"),
                "1001": ("1° TURNO", "AFC", "operador"), "2001": ("2° TURNO", "AFC", "operador"), "3001": ("3° TURNO", "AFC", "operador"),
                "1002": ("1° TURNO", "RTF", "operador"), "2002": ("2° TURNO", "RTF", "operador"), "3002": ("3° TURNO", "RTF", "operador"),
                "4040": ("1° TURNO", "PRESET", "preset"), "5050": ("2° TURNO", "PRESET", "preset"), "6060": ("3° TURNO", "PRESET", "preset")
            }
            if cod in codigos_validos and nome:
                turno_val, setor_val, perfil_val = codigos_validos[cod]
                if perfil_val != "adm":
                    if not pode_logar(turno_val):
                        st.error(f"🚫 Acesso Negado: Fora do horário permitido para o {turno_val}.")
                        return
                
                nome_formatado = nome.upper()
                st.session_state['logout_realizado'] = False
                st.session_state['turno'] = turno_val
                st.session_state['setor_usuario'] = setor_val
                st.session_state['perfil'] = perfil_val
                st.session_state['operador'] = nome_formatado
                
                cookie_manager.set("user_logado", nome_formatado, key="set_logado")
                cookie_manager.set("user_turno", turno_val, key="set_turno")
                cookie_manager.set("user_setor", setor_val, key="set_setor")
                cookie_manager.set("user_perfil", perfil_val, key="set_perfil")
                time.sleep(0.5)
                mudar_tela('menu')
            else: st.error("⚠️ Credenciais inválidas.")

def tela_menu():
    exibir_alertas_preset()
    
    perfil = st.session_state['perfil']
    if perfil == 'adm': setor_txt = "Gerência"
    elif st.session_state['setor_usuario'] == 'TECNICO': setor_txt = "Técnico (Geral)"
    elif perfil == 'preset': setor_txt = "Pré-Set"
    else: setor_txt = 'Afiação' if st.session_state['setor_usuario']=='AFC' else 'Retífica'
    
    st.markdown(f"""
    <div style='background: #18181B; padding: 12px; border-radius: 10px; border-left: 4px solid #14B8A6; margin-bottom: 15px;'>
        <p style='margin:0; font-size: 13px; color: #A1A1AA;'>Usuário Logado</p>
        <p style='margin:0; font-size: 16px; font-weight: bold; color: #F4F4F5;'>{st.session_state['operador']}</p>
        <p style='margin:0; font-size: 12px; color: #2DD4BF;'>{st.session_state['turno']} • {setor_txt}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if perfil == 'adm':
        if st.button("⚙️ ACESSAR MÓDULO AFIAÇÃO", use_container_width=True, type="primary"): mudar_tela('afc')
        if st.button("⚙️ ACESSAR MÓDULO RETÍFICA", use_container_width=True, type="primary"): mudar_tela('rtf')
        if st.button("🗄️ GERENCIAR ARMÁRIOS", use_container_width=True): mudar_tela('armarios')
        if st.button("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", use_container_width=True): mudar_tela('checkup')
        if st.button("👥 CONTROLE DE EQUIPE", use_container_width=True): mudar_tela('equipe')
        if st.button("📋 RELATÓRIO GERAL CONSOLIDADO", use_container_width=True): mudar_tela('relatorio')
        if st.button("📊 HISTÓRICOS E EXPORTAÇÕES", use_container_width=True): mudar_tela('historico')
        if st.button("✏️ GERENCIAR BANCO DE DADOS", use_container_width=True): mudar_tela('editar')
    elif perfil == 'preset':
        if st.button("🗄️ GERENCIAR ARMÁRIOS", use_container_width=True, type="primary"): mudar_tela('armarios')
        if st.button("🔍 PROGRAMAÇÃO DO SETOR", use_container_width=True): mudar_tela('checkup')
    elif perfil == 'preparador':
        if st.session_state['setor_usuario'] in ['AFC', 'TECNICO']:
            if st.button("⚙️ ACESSAR MÓDULO AFIAÇÃO", use_container_width=True, type="primary"): mudar_tela('afc')
        if st.session_state['setor_usuario'] in ['RTF', 'TECNICO']:
            if st.button("⚙️ ACESSAR MÓDULO RETÍFICA", use_container_width=True, type="primary"): mudar_tela('rtf')
        if st.button("🗄️ VISÃO DOS ARMÁRIOS", use_container_width=True): mudar_tela('armarios')
        if st.button("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", use_container_width=True): mudar_tela('checkup')
        if st.button("⚡ MINHAS INCIDÊNCIAS", use_container_width=True, type="primary"): mudar_tela('minhas_incidencias')
        if st.button("👥 CONTROLE DE EQUIPE", use_container_width=True): mudar_tela('equipe')
        if st.button("📋 RELATÓRIO DE TURNO", use_container_width=True): mudar_tela('relatorio')
        if st.button("✏️ CORREÇÃO DE APONTAMENTOS", use_container_width=True): mudar_tela('editar')
    else:
        if st.button("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", use_container_width=True): mudar_tela('checkup')
        if st.button("📋 FECHAMENTO DE TURNO", use_container_width=True): mudar_tela('relatorio')
        if st.button("✏️ CORREÇÃO DE APONTAMENTOS", use_container_width=True): mudar_tela('editar')
    
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    if st.button("🚪 Encerramento de Sessão (Logout)", use_container_width=True):
        st.session_state['logout_realizado'] = True
        st.session_state['operador'], st.session_state['turno'], st.session_state['setor_usuario'], st.session_state['perfil'] = '', '', '', ''
        try:
            if cookie_manager.get("user_logado"): cookie_manager.delete("user_logado", key="del_logado")
            if cookie_manager.get("user_turno"): cookie_manager.delete("user_turno", key="del_turno")
            if cookie_manager.get("user_setor"): cookie_manager.delete("user_setor", key="del_setor")
            if cookie_manager.get("user_perfil"): cookie_manager.delete("user_perfil", key="del_perfil")
        except: pass 
        time.sleep(0.5); mudar_tela('login')

def render_grid_vertical(lista_maquinas, setor, status_dict):
    for maq in ordenar_maquinas(lista_maquinas):
        if maq != "":
            chave_busca = f"{setor} {maq}"
            status_atual = status_dict.get(chave_busca, "PRODUZINDO")
            icone = get_status_icon(status_atual)
            label_botao = f"{icone} Máquina {maq} — {status_atual}"
            if st.button(label_botao, key=f"btn_vert_{setor}_{maq}", use_container_width=True):
                st.session_state['maq_ativa'] = maq
                st.session_state['setor_ativo'] = setor
                st.rerun()

def tela_checkup():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### 🔍 Programação e Incidências")
    st.divider()
    
    status_dict = ler_status_atual()
    perfil = st.session_state['perfil']
    setor_atual = st.session_state['setor_usuario']
    
    turno_vigente_real = turno_atual_horario()
    
    if setor_atual in ['TECNICO', 'GERAL', 'GERÊNCIA', 'PRESET'] or perfil == 'adm': 
        setores_alvo = [("AFC", TODAS_AFC), ("RTF", TODAS_RTF)]
    else: 
        setores_alvo = [(setor_atual, TODAS_AFC if setor_atual == "AFC" else TODAS_RTF)]
        
    incidencias_turno_atual = []
    preparacoes_futuras = {"1° TURNO": [], "2° TURNO": [], "3° TURNO": []}
    
    for s_nome, lista in setores_alvo:
        for m in lista:
            st_val = status_dict.get(f"{s_nome} {m}", "PRODUZINDO")
            
            # Entra na lista se tiver problema, agendamento ou PREVISÃO de parada
            if "PRODUZINDO" not in st_val or "AGENDADO" in st_val or "AGENDADA" in st_val or "AGUARDANDO" in st_val or "[Fim Previsto:" in st_val:
                
                turno_pendencia = turno_vigente_real 
                h_alvo = ""
                
                if "AGENDADA PARA" in st_val:
                    try: h_alvo = st_val.split("AGENDADA PARA")[1].strip()
                    except: pass
                elif "[AGENDADO:" in st_val:
                    try: h_alvo = st_val.split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "[Fim Previsto:" in st_val:
                    try: h_alvo = st_val.split("[Fim Previsto:")[1].split("]")[0].strip()
                    except: pass
                    
                if h_alvo:
                    turno_pendencia = obter_turno_por_horario(h_alvo)
                
                item_lista = (s_nome, m, st_val)
                
                is_agendamento_ou_prev = "AGENDADA PARA" in st_val or "[AGENDADO:" in st_val or "[Fim Previsto:" in st_val
                
                is_futuro_real = False
                if is_agendamento_ou_prev and h_alvo:
                    try:
                        agora_dt = datetime.now(FUSO_BR)
                        h_alvo_dt = datetime.strptime(h_alvo, "%H:%M").replace(year=agora_dt.year, month=agora_dt.month, day=agora_dt.day, tzinfo=FUSO_BR)
                        
                        # Tratamento para virada de meia noite
                        if h_alvo_dt < agora_dt and (agora_dt - h_alvo_dt).total_seconds() > 12 * 3600:
                            h_alvo_dt += timedelta(days=1)
                        elif h_alvo_dt > agora_dt and (h_alvo_dt - agora_dt).total_seconds() > 12 * 3600:
                            h_alvo_dt -= timedelta(days=1)
                            
                        delta_mins = (h_alvo_dt - agora_dt).total_seconds() / 60
                        
                        # Se a hora alvo já passou (delta negativo considerável, digamos -10 min), a máquina vira pendência IMEDIATA para o Turno Vigente
                        if delta_mins > -10 and turno_pendencia != turno_vigente_real:
                            is_futuro_real = True
                    except: pass
                
                if is_futuro_real:
                    if turno_pendencia in preparacoes_futuras:
                        preparacoes_futuras[turno_pendencia].append(item_lista)
                else:
                    if "PRODUZINDO" not in st_val or "[Fim Previsto:" in st_val:
                        incidencias_turno_atual.append(item_lista)
                    
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo']:
        painel_controle_maquina(st.session_state['maq_ativa'], st.session_state['setor_ativo'])
        st.divider()

    aba_atual, aba_futuro, aba_previsao = st.tabs(["🚨 Turno Vigente", "🔮 Preparações Futuras", "⏱️ Lançar Previsões"])

    with aba_atual:
        st.markdown(f"**Exibindo incidências e paradas previstas para o {turno_vigente_real}**")
        if not incidencias_turno_atual: 
            st.success("✨ Ótimo! Nenhuma incidência ou parada prevista para o momento.")
        else:
            for setor_m, maq_m, st_m in incidencias_turno_atual:
                icone = get_status_icon(st_m)
                if st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"chk_at_{setor_m}_{maq_m}", use_container_width=True):
                    st.session_state['maq_ativa'] = maq_m
                    st.session_state['setor_ativo'] = setor_m
                    st.rerun()

    with aba_futuro:
        st.markdown("**Programação de Setups e Paradas por Turno**")
        filtro_turno = st.radio("Selecione o Turno para visualizar:", ["1° TURNO", "2° TURNO", "3° TURNO"], horizontal=True)
        
        lista_futura = preparacoes_futuras[filtro_turno]
        if not lista_futura:
            st.info(f"Nenhum setup ou parada programada futuramente para o {filtro_turno}.")
        else:
            for setor_m, maq_m, st_m in lista_futura:
                icone = get_status_icon(st_m)
                if st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"chk_fut_{setor_m}_{maq_m}", use_container_width=True):
                    st.session_state['maq_ativa'] = maq_m
                    st.session_state['setor_ativo'] = setor_m
                    st.rerun()

    with aba_previsao:
        st.markdown("#### ⏱️ Lançar Previsão de Parada por Fila")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Selecione a fila e digite o horário (HH:MM) previsto para as máquinas pararem.</p>", unsafe_allow_html=True)

        if setor_atual in ['TECNICO', 'GERAL', 'GERÊNCIA', 'PRESET'] or perfil == 'adm':
            c_s1, c_s2 = st.columns(2)
            if c_s1.button("Setor: AFIAÇÃO", use_container_width=True): st.session_state['setor_prev_sel'] = 'AFC'; st.session_state['fila_prev_sel'] = None; st.rerun()
            if c_s2.button("Setor: RETÍFICA", use_container_width=True): st.session_state['setor_prev_sel'] = 'RTF'; st.session_state['fila_prev_sel'] = None; st.rerun()
            setor_foco = st.session_state.get('setor_prev_sel', 'AFC')
        else:
            setor_foco = "AFC" if setor_atual == "AFC" else "RTF"
            
        st.markdown(f"**Lançando previsões para: {setor_foco}**")
        st.markdown("<hr style='margin: 5px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        
        if st.session_state.get('fila_prev_sel') is None:
            if st.button("📍 Fila 1", use_container_width=True): st.session_state['fila_prev_sel'] = 'fila_1'; st.rerun()
            if st.button("📍 Fila 2", use_container_width=True): st.session_state['fila_prev_sel'] = 'fila_2'; st.rerun()
            if st.button("📍 Fila 3", use_container_width=True): st.session_state['fila_prev_sel'] = 'fila_3'; st.rerun()
            if st.button("📍 Fila 4", use_container_width=True): st.session_state['fila_prev_sel'] = 'fila_4'; st.rerun()
            
            if setor_foco == 'RTF':
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                if st.button("⚫ Centerless (CNC1)", use_container_width=True): st.session_state['fila_prev_sel'] = 'centerless'; st.rerun()
                if st.button("🟤 Facetadoras (CNC2)", use_container_width=True): st.session_state['fila_prev_sel'] = 'facetadoras'; st.rerun()
        else:
            if st.button("⬅️ Voltar para seleção de Fila", key="voltar_fila_prev"): st.session_state['fila_prev_sel'] = None; st.rerun()
            
            maquinas_foco = []
            if setor_foco == 'AFC':
                if st.session_state['fila_prev_sel'] == 'fila_1': maquinas_foco = ["6-868", "9-088", "7-743", "11-365", "13-964", "15-973", "17-140", "19-760", "21-206", "23-165", "25-209", "27-431"]
                elif st.session_state['fila_prev_sel'] == 'fila_2': maquinas_foco = ["8-247", "4-427", "10-812", "12-367", "14-967", "16-975", "18-957", "20-774", "22-813", "24-761", "26-635", "28-432"]
                elif st.session_state['fila_prev_sel'] == 'fila_3': maquinas_foco = ["29-078", "31-969", "33-160", "35-131", "37-892", "39-905", "41-141"]
                elif st.session_state['fila_prev_sel'] == 'fila_4': maquinas_foco = ["30-161", "32-081", "34-132", "36-084", "38-596", "40-142"]
            else:
                tipos_dict = ler_tipos_cnc()
                base_f1 = ["5-903", "8-086", "10-817", "12-962", "14-971", "16-183", "19-926", "21-270", "23-753", "25-258", "27-917"]
                base_f2 = ["7-267", "9-815", "11-363", "13-969", "15-977", "18-925", "20-927", "22-916", "24-259", "26-260", "28-954"]
                base_f3 = ["29-785", "31-806", "33-807", "35-885", "37-857", "39-856"]
                base_f4 = ["30-786", "32-918", "34-842", "36-854", "38-881", "40-912", "42-885"]
                todas_cnc1 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC1"]
                todas_cnc2 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC2"]
                todas_cnc3 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC3"]
                
                if st.session_state['fila_prev_sel'] == 'fila_1': maquinas_foco = [m for m in base_f1 if m in todas_cnc3]
                elif st.session_state['fila_prev_sel'] == 'fila_2': maquinas_foco = [m for m in base_f2 if m in todas_cnc3]
                elif st.session_state['fila_prev_sel'] == 'fila_3': maquinas_foco = [m for m in base_f3 if m in todas_cnc3]
                elif st.session_state['fila_prev_sel'] == 'fila_4': 
                    nativos = set(base_f1 + base_f2 + base_f3 + base_f4)
                    extraviados = [m for m in todas_cnc3 if m not in nativos]
                    maquinas_foco = [m for m in base_f4 if m in todas_cnc3] + extraviados
                elif st.session_state['fila_prev_sel'] == 'centerless': maquinas_foco = todas_cnc1
                elif st.session_state['fila_prev_sel'] == 'facetadoras': maquinas_foco = todas_cnc2

            maquinas_produzindo = []
            for m in ordenar_maquinas(maquinas_foco):
                st_val = status_dict.get(f"{setor_foco} {m}", "PRODUZINDO")
                if "PRODUZINDO" in st_val:
                    hora_prevista = ""
                    if "[Fim Previsto:" in st_val:
                        try: hora_prevista = st_val.split("[Fim Previsto:")[1].split("]")[0].strip()
                        except: pass
                    
                    op_atual = ""
                    if "[Ordem:" in st_val:
                        try: op_atual = st_val.split("[Ordem:")[1].split("]")[0].strip()
                        except: pass
                        
                    maquinas_produzindo.append({
                        "Setor": setor_foco,
                        "Maquina": m,
                        "OP": op_atual,
                        "HoraAntiga": hora_prevista,
                        "StatusRaw": st_val
                    })

            if not maquinas_produzindo:
                st.info(f"Nenhuma máquina em produção nesta fila no momento.")
            else:
                with st.form(f"form_previsoes_linhas_{setor_foco}_{st.session_state['fila_prev_sel']}"):
                    col1, col2, col3 = st.columns([2, 3, 2])
                    col1.markdown("**Máquina**")
                    col2.markdown("**Ordem (OP)**")
                    col3.markdown("**Hora Parada**")
                    
                    st.markdown("<hr style='margin: 5px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                    
                    inputs_previsao = {}
                    for obj in maquinas_produzindo:
                        c1, c2, c3 = st.columns([2, 3, 2])
                        c1.markdown(f"<p style='margin-top: 10px;'>{obj['Setor']} <b>{obj['Maquina']}</b></p>", unsafe_allow_html=True)
                        c2.markdown(f"<p style='margin-top: 10px;'>{obj['OP'] if obj['OP'] else '-'}</p>", unsafe_allow_html=True)
                        nova_hora = c3.text_input("Hora", value=obj['HoraAntiga'], key=f"prev_{obj['Setor']}_{obj['Maquina']}", label_visibility="collapsed", placeholder="HH:MM")
                        
                        inputs_previsao[f"{obj['Setor']} {obj['Maquina']}"] = {
                            "nova": nova_hora,
                            "antiga": obj['HoraAntiga'],
                            "setor": obj['Setor'],
                            "maq": obj['Maquina'],
                            "st_raw": obj['StatusRaw']
                        }
                        
                    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
                    submit_prev = st.form_submit_button("💾 Salvar Previsões", type="primary", use_container_width=True)
                    
                    if submit_prev:
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        novas_linhas = []
                        
                        for key_maq, dados in inputs_previsao.items():
                            hora_nova = str(dados['nova']).strip()
                            hora_antiga = str(dados['antiga']).strip()
                            
                            if hora_nova != hora_antiga:
                                st_val = dados['st_raw']
                                if "[Fim Previsto:" in st_val:
                                    st_val = re.sub(r' \[Fim Previsto:.*?\]', '', st_val)
                                    
                                if hora_nova:
                                    st_final = f"{st_val} [Fim Previsto: {hora_nova}]".strip()
                                else:
                                    st_final = st_val.strip()
                                    
                                novas_linhas.append({"Setor": dados['setor'], "Maquina": key_maq, "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str})
                                
                        if novas_linhas:
                            df_dados = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
                            df_dados = pd.concat([df_dados, pd.DataFrame(novas_linhas)], ignore_index=True)
                            df_dados.to_csv(ARQUIVO_DADOS, index=False)
                            st.success("✅ Previsões atualizadas com sucesso!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.info("Nenhuma alteração de horário detectada.")

def tela_minhas_incidencias():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown(f"#### ⚡ Minhas Incidências — {st.session_state['operador']}")
    st.divider()
    status_dict = ler_status_atual()
    setor_atual = st.session_state['setor_usuario']
    nome_usuario = st.session_state['operador'].upper()
    lista_setor = TODAS_AFC if setor_atual == "AFC" else TODAS_RTF
    minhas_maquinas = []
    
    for m in lista_setor:
        chave = f"{setor_atual} {m}"
        st_val = status_dict.get(chave, "PRODUZINDO")
        info = obter_info_maquina(m, setor_atual)
        if info and (f"[Prep: {nome_usuario}]" in st_val or f"[Prep. Sugerido: {nome_usuario}]" in st_val or f"[PREP: {nome_usuario}]" in st_val.upper()):
            minhas_maquinas.append((setor_atual, m, st_val))

    if st.session_state['maq_ativa'] and st.session_state['setor_ativo']:
        painel_controle_maquina(st.session_state['maq_ativa'], st.session_state['setor_ativo'])
        st.divider()

    if not minhas_maquinas: st.info("ℹ️ Você não possui nenhuma máquina em preparação no momento.")
    else:
        for setor_m, maq_m, st_m in minhas_maquinas:
            icone = get_status_icon(st_m)
            if st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"min_{setor_m}_{maq_m}", use_container_width=True):
                st.session_state['maq_ativa'] = maq_m
                st.session_state['setor_ativo'] = setor_m
                st.rerun()

def tela_afc():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### ⚙️ Setor Afiação — Filas")
    
    st.markdown("""
    <div style='background-color: #3f0000; padding: 12px; border-radius: 8px; border-left: 5px solid #ff4444; margin-bottom: 15px;'>
        <h5 style='margin:0; color: #ff9999 !important;'>⚡ EMERGÊNCIA: QUEDA DE ENERGIA</h5>
        <p style='margin:0; font-size: 13px; color: #e0e0e0;'>Registre a parada ou restaure o status de TODAS as máquinas do setor simultaneamente.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col_em1, col_em2 = st.columns(2)
    if col_em1.button("🔴 Parar todas (AFC)", use_container_width=True):
        registrar_queda_energia("AFC")
        st.success("✅ Todas as afiadoras registradas como PARADAS!")
        time.sleep(1); st.rerun()
    if col_em2.button("🔄 Restaurar Status", use_container_width=True):
        restaurar_queda_energia("AFC")
        st.success("✅ Status das afiadoras restaurado!")
        time.sleep(1); st.rerun()
        
    status_dict = ler_status_atual()
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'AFC': painel_controle_maquina(st.session_state['maq_ativa'], 'AFC')
    
    if st.session_state['celula_selecionada'] is None:
        if st.button("📍 Fila 1", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_1'; st.rerun()
        if st.button("📍 Fila 2", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_2'; st.rerun()
        if st.button("📍 Fila 3", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_3'; st.rerun()
        if st.button("📍 Fila 4", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_4'; st.rerun()
    else:
        if st.button("⬅️ Trocar de Fila"): st.session_state['celula_selecionada'] = None; st.session_state['maq_ativa'] = None; st.rerun()
        st.divider()
        if st.session_state['celula_selecionada'] == 'fila_1': render_grid_vertical(["6-868", "9-088", "7-743", "11-365", "13-964", "15-973", "17-140", "19-760", "21-206", "23-165", "25-209", "27-431"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_2': render_grid_vertical(["8-247", "4-427", "10-812", "12-367", "14-967", "16-975", "18-957", "20-774", "22-813", "24-761", "26-635", "28-432"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_3': render_grid_vertical(["29-078", "31-969", "33-160", "35-131", "37-892", "39-905", "41-141"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_4': render_grid_vertical(["30-161", "32-081", "34-132", "36-084", "38-596", "40-142"], "AFC", status_dict)

def tela_rtf():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### ⚙️ Setor Retífica — Filas")
    
    st.markdown("""
    <div style='background-color: #3f0000; padding: 12px; border-radius: 8px; border-left: 5px solid #ff4444; margin-bottom: 15px;'>
        <h5 style='margin:0; color: #ff9999 !important;'>⚡ EMERGÊNCIA: QUEDA DE ENERGIA</h5>
        <p style='margin:0; font-size: 13px; color: #e0e0e0;'>Registre a parada ou restaure o status de TODAS as máquinas do setor simultaneamente.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col_em1, col_em2 = st.columns(2)
    if col_em1.button("🔴 Parar todas (RTF)", use_container_width=True):
        registrar_queda_energia("RTF")
        st.success("✅ Todas as retíficas registradas como PARADAS!")
        time.sleep(1); st.rerun()
    if col_em2.button("🔄 Restaurar Status", use_container_width=True):
        restaurar_queda_energia("RTF")
        st.success("✅ Status das retíficas restaurado!")
        time.sleep(1); st.rerun()

    status_dict = ler_status_atual()
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'RTF': painel_controle_maquina(st.session_state['maq_ativa'], 'RTF')
    
    # --- DISTRIBUIÇÃO DINÂMICA DE FILAS ---
    tipos_dict = ler_tipos_cnc()
    
    base_fila_1 = ["5-903", "8-086", "10-817", "12-962", "14-971", "16-183", "19-926", "21-270", "23-753", "25-258", "27-917"]
    base_fila_2 = ["7-267", "9-815", "11-363", "13-969", "15-977", "18-925", "20-927", "22-916", "24-259", "26-260", "28-954"]
    base_fila_3 = ["29-785", "31-806", "33-807", "35-885", "37-857", "39-856"]
    base_fila_4 = ["30-786", "32-918", "34-842", "36-854", "38-881", "40-912", "42-885"]
    
    todas_cnc1 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC1"]
    todas_cnc2 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC2"]
    todas_cnc3 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC3"]
    
    f1_atual = [m for m in base_fila_1 if m in todas_cnc3]
    f2_atual = [m for m in base_fila_2 if m in todas_cnc3]
    f3_atual = [m for m in base_fila_3 if m in todas_cnc3]
    
    nativos_normais = set(base_fila_1 + base_fila_2 + base_fila_3 + base_fila_4)
    extraviados_cnc3 = [m for m in todas_cnc3 if m not in nativos_normais]
    f4_atual = [m for m in base_fila_4 if m in todas_cnc3] + extraviados_cnc3

    if st.session_state['celula_selecionada'] is None:
        if st.button("📍 Fila 1", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_1'; st.rerun()
        if st.button("📍 Fila 2", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_2'; st.rerun()
        if st.button("📍 Fila 3", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_3'; st.rerun()
        if st.button("📍 Fila 4", use_container_width=True): st.session_state['celula_selecionada'] = 'fila_4'; st.rerun()
        
        st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        if st.button("⚫ Centerless (CNC1)", use_container_width=True): st.session_state['celula_selecionada'] = 'centerless'; st.rerun()
        if st.button("🟤 Facetadoras (CNC2)", use_container_width=True): st.session_state['celula_selecionada'] = 'facetadoras'; st.rerun()
    else:
        if st.button("⬅️ Trocar de Fila / Setor"): st.session_state['celula_selecionada'] = None; st.session_state['maq_ativa'] = None; st.rerun()
        st.divider()
        
        if st.session_state['celula_selecionada'] == 'fila_1': render_grid_vertical(f1_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_2': render_grid_vertical(f2_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_3': render_grid_vertical(f3_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_4': render_grid_vertical(f4_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'centerless': render_grid_vertical(todas_cnc1, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'facetadoras': render_grid_vertical(todas_cnc2, "RTF", status_dict)

def tela_equipe():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### 👥 Gestão de Equipe")
    with st.container():
        with st.form("form_equipe", clear_on_submit=True):
            tipo = st.radio("Selecione o Motivo:", ["Ausência / Falta", "Treinamento", "Férias / Atestado"], horizontal=True)
            nome = st.text_input("Nome do Colaborador:")
            if st.form_submit_button("💾 REGISTRAR COLABORADOR", type="primary"):
                if nome:
                    salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                    st.success(f"✅ {nome.upper()} registrado como {tipo}!")
                    time.sleep(0.5); st.rerun()
    st.divider()
    if os.path.exists(ARQUIVO_EQUIPE):
        df_eq = pd.read_csv(ARQUIVO_EQUIPE)
        if not df_eq.empty: st.dataframe(df_eq, use_container_width=True, hide_index=True)

def tela_editar():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### ✏️ Correção de Apontamentos")
    
    perfil = st.session_state['perfil']
    setor_usuario = st.session_state['setor_usuario']
    
    if perfil == 'adm':
        col_salvar, col_apagar = st.columns([2, 1])
        if col_apagar.button("🗑️ ZERAR DADOS DO TURNO", use_container_width=True):
            if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            st.success("✅ Banco de dados apagado com sucesso!")
            time.sleep(0.5); st.rerun()
    else: col_salvar = st.container()
        
    if os.path.exists(ARQUIVO_DADOS):
        df_maq = pd.read_csv(ARQUIVO_DADOS)
        idx_ultimos = df_maq.drop_duplicates(subset=['Maquina'], keep='last').index
        df_editar = df_maq.loc[idx_ultimos].copy()
        
        if setor_usuario == 'AFC': df_editar = df_editar[df_editar['Setor'] == 'AFC']
        elif setor_usuario == 'RTF': df_editar = df_editar[df_editar['Setor'] == 'RTF']
            
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Altere o Horário ou o Status se houver algum erro de digitação. Somente o <b>último apontamento</b> de cada máquina está sendo exibido.</p>", unsafe_allow_html=True)
        
        busca_maq = st.text_input("🔍 Pesquisar Máquina:", placeholder="Digite o número (ex: 6-868, 30-161...)")
        if busca_maq.strip(): df_editar = df_editar[df_editar['Maquina'].str.contains(busca_maq.strip(), case=False, na=False)]
        
        df_editado = st.data_editor(df_editar, num_rows="dynamic", use_container_width=True)
        
        if col_salvar.button("💾 Salvar Alterações", use_container_width=True, type="primary"):
            indices_originais = df_editar.index.tolist()
            indices_mantidos = df_editado.index.tolist()
            indices_apagados = [i for i in indices_originais if i not in indices_mantidos]
            
            if indices_apagados: df_maq = df_maq.drop(index=indices_apagados)
            
            for idx, row in df_editado.iterrows():
                if idx in df_maq.index:
                    df_maq.at[idx, 'Status'] = str(row['Status'])
                    df_maq.at[idx, 'Hora'] = str(row['Hora']).strip()
                else:
                    nova_linha = pd.DataFrame([{"Setor": row.get('Setor', ''), "Maquina": row.get('Maquina', ''), "Operador": row.get('Operador', ''), "Status": str(row.get('Status', '')), "Hora": str(row.get('Hora', '')).strip()}])
                    df_maq = pd.concat([df_maq, nova_linha], ignore_index=True)
                    
            df_maq.to_csv(ARQUIVO_DADOS, index=False)
            st.success("✨ Banco de dados atualizado com sucesso!")
            time.sleep(0.5); st.rerun()
    else: st.info("Nenhum apontamento encontrado no sistema.")

def tela_historico():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### 📊 Histórico e Exportações")
    aba1, aba2 = st.tabs(["📝 Relatórios Textuais", "📥 Banco de Eventos (Planilha)"])
    with aba1:
        if st.session_state['perfil'] == 'adm' and os.path.exists(ARQUIVO_HISTORICO):
            if st.button("🗑️ APAGAR HISTÓRICO DE RELATÓRIOS", type="secondary"):
                os.remove(ARQUIVO_HISTORICO); st.rerun()
        if os.path.exists(ARQUIVO_HISTORICO):
            df_hist = pd.read_csv(ARQUIVO_HISTORICO)
            for idx in reversed(df_hist.index):
                row = df_hist.loc[idx]
                with st.expander(f"📅 {row['Data']} - {row['Turno']}"):
                    st.markdown("##### Relatório Padrão")
                    st.code(row['Relatorio_Padrao'], language="text")
                    st.markdown("##### Relatório de Tempos")
                    st.code(row['Relatorio_Tempos'], language="text")
    with aba2:
        if os.path.exists(ARQUIVO_HISTORICO_EVENTOS):
            df_ev = pd.read_csv(ARQUIVO_HISTORICO_EVENTOS)
            if not df_ev.empty:
                st.dataframe(df_ev, use_container_width=True, hide_index=True)
                if st.session_state['perfil'] == 'adm':
                    csv = df_ev.to_csv(index=False, sep=';').encode('utf-8-sig')
                    st.download_button("📥 Baixar Planilha", data=csv, file_name="eventos.csv", mime="text/csv", type="primary")

def tela_relatorio():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("#### 📋 Fechamento e Relatório de Turno")
    col1, col2 = st.columns(2)
    gerar = col1.button("👁️ Visualizar", use_container_width=True)
    encerrar = col2.button("🛑 ENCERRAR TURNO MANUALMENTE", type="primary", use_container_width=True)
        
    if gerar or encerrar:
        curr_d, curr_t = get_turno_logico()
        df_completo = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
        
        texto_padrao, texto_tempos = gerar_textos_fechamento(curr_d, df_completo)

        st.markdown("##### 📄 Relatório 1 (Padrão e Limpo)")
        st.code(texto_padrao, language="text")
        st.markdown("##### ⏱️ Relatório 2 (Tempos e Repasses)")
        st.code(texto_tempos, language="text")
        
        if encerrar:
            executar_fechamento_silencioso(curr_d, curr_t)
            st.success("✨ Turno encerrado manualmente! O banco de dados foi limpo e está pronto para continuar.")
            time.sleep(2); st.rerun()

def tela_armarios():
    exibir_alertas_preset()
    
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### 🗄️ Gestão de Armários (Pré-Set)")
    
    inicializar_armarios()
    df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str, 'Armario': str, 'Observacao': str})
    if 'Item' not in df_arm.columns: df_arm['Item'] = ""
    if 'Observacao' not in df_arm.columns: df_arm['Observacao'] = ""

    gaveta = st.session_state.get('gaveta_selecionada', None)

    if gaveta:
        arm_sel = gaveta['armario']
        pos_sel = gaveta['posicao']
        status_sel = gaveta['status']
        op_sel = gaveta['ordem']
        item_sel = gaveta['item']
        obs_sel = gaveta.get('observacao', '')
        
        st.markdown(f"""
        <div style='background: #18181B; padding: 15px; border-radius: 10px; border-left: 4px solid #14B8A6; margin-bottom: 20px;'>
            <h4 style='margin:0; color: #2DD4BF;'>⚙️ Gerenciar: {arm_sel} - MÁQUINA {pos_sel}</h4>
        </div>
        """, unsafe_allow_html=True)
        
        if status_sel == 'VAZIO':
            with st.form("form_alimentar"):
                st.info("🟥 Esta gaveta está VAZIA. Insira os dados para guardar o setup.")
                c_op, c_it = st.columns(2)
                ordem_in = c_op.text_input("Ordem de Produção (OP):", placeholder="Ex: 987654")
                item_in = c_it.text_input("Item / Peça:", placeholder="Ex: 313324")
                obs_in = st.text_input("Observação / Justificativa (Obrigatório se não houver OP):", placeholder="Se não possuir OP, digite o motivo...")
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("📥 GUARDAR SETUP", type="primary", use_container_width=True):
                    if not ordem_in.strip() and not obs_in.strip():
                        st.error("⚠️ Se não houver Ordem (OP), a Observação/Justificativa é obrigatória!")
                    else:
                        ordem_limpa = ordem_in.strip().upper().replace(".0", "")
                        item_limpo = item_in.strip().upper().replace(".0", "")
                        obs_limpa = obs_in.strip()
                        
                        idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao']] = [ordem_limpa, item_limpo, "AGUARDANDO MÁQUINA", datetime.now(FUSO_BR).strftime("%H:%M"), obs_limpa]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.session_state['gaveta_selecionada'] = None
                            st.success(f"✅ Setup guardado na gaveta da MÁQUINA {pos_sel}!")
                            time.sleep(1)
                            st.rerun()
                if c2.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        else:
            with st.form("form_editar_excluir"):
                st.warning("🟩 Gaveta OCUPADA - Altere os dados abaixo para corrigir ou exclua o registro.")
                c_op, c_it = st.columns(2)
                nova_op = c_op.text_input("Ordem de Produção (OP):", value=op_sel)
                novo_item = c_it.text_input("Item / Peça:", value=item_sel)
                nova_obs = st.text_input("Observação / Justificativa:", value=str(obs_sel).replace('nan', ''))
                
                c1, c2, c3 = st.columns(3)
                if c1.form_submit_button("💾 Atualizar", type="primary", use_container_width=True):
                    if not nova_op.strip() and not nova_obs.strip():
                        st.error("⚠️ É obrigatório possuir uma Ordem (OP) ou uma Observação justificando!")
                    else:
                        idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Observacao']] = [nova_op.strip().upper().replace(".0", ""), novo_item.strip().upper().replace(".0", ""), nova_obs.strip()]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.session_state['gaveta_selecionada'] = None
                            st.success("✅ Gaveta atualizada com sucesso!")
                            time.sleep(1)
                            st.rerun()
                            
                if c2.form_submit_button("🗑️ Excluir", use_container_width=True):
                    idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                    if not idx.empty:
                        df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao']] = ["", "", "VAZIO", datetime.now(FUSO_BR).strftime("%H:%M"), ""]
                        df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                        st.session_state['gaveta_selecionada'] = None
                        st.success("✅ Gaveta liberada com sucesso!")
                        time.sleep(1)
                        st.rerun()
                        
                if c3.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        
        st.divider()

    aba1, aba2, aba3, aba4 = st.tabs(["👁️ Visão Física (Gavetas)", "➕ Alimentar (Lista Clássica)", "🔔 Alertas e Histórico", "🔄 Troca de Rebolo"])

    # --- ABA 1: VISUALIZAÇÃO FÍSICA DOS ARMÁRIOS ---
    with aba1:
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Visão estrutural. <b>Clique diretamente na gaveta</b> para alimentar (guardar) ou corrigir a OP.</p>", unsafe_allow_html=True)
        
        armarios_lista = ["Afiadoras 04 a 28", "Afiadoras 29 a 41", "Retíficas 05 a 28", "Retíficas 29 a 42"]
        
        for row_idx in range(0, len(armarios_lista), 2):
            c1, c2 = st.columns(2)
            colunas_ui = [c1, c2]
            
            for col_i in range(2):
                if row_idx + col_i < len(armarios_lista):
                    arm = armarios_lista[row_idx + col_i]
                    col_ui = colunas_ui[col_i]
                    
                    df_filtrado = df_arm[df_arm['Armario'] == arm].copy()
                    df_filtrado['Posicao_Int'] = pd.to_numeric(df_filtrado['Posicao'], errors='coerce')
                    df_filtrado = df_filtrado.sort_values(by='Posicao_Int')
                    
                    ocupados = len(df_filtrado[df_filtrado['Status'] != 'VAZIO'])
                    total_gavetas = len(df_filtrado)
                    
                    with col_ui.container(border=True):
                        st.markdown(f"<h5 style='text-align: center; color: #2DD4BF; margin-bottom: 15px;'>📦 {arm} <br><span style='font-size: 12px; color: #A1A1AA;'>({ocupados}/{total_gavetas} ocupados)</span></h5>", unsafe_allow_html=True)
                        
                        gavetas = df_filtrado.to_dict('records')
                        
                        for linha in range(0, total_gavetas, 4):
                            cols_gaveta = st.columns(4)
                            for c in range(4):
                                if linha + c < total_gavetas:
                                    gav = gavetas[linha + c]
                                    num = gav['Posicao']
                                    status = gav['Status']
                                    
                                    if status == 'VAZIO':
                                        btn_label = f"🟥 MAQ {num}\nVAZIO"
                                    else:
                                        op_f = str(gav.get('Ordem', '')).replace('.0', '').replace('nan', '')
                                        obs_f = str(gav.get('Observacao', '')).replace('nan', '').strip()
                                        
                                        if op_f:
                                            btn_label = f"🟩 MAQ {num}\nOP: {op_f}"
                                        elif obs_f:
                                            btn_label = f"🟩 MAQ {num}\nOBS: {obs_f[:8]}..."
                                        else:
                                            btn_label = f"🟩 MAQ {num}\nOCUPADO"
                                    
                                    if cols_gaveta[c].button(btn_label, key=f"btn_gav_{arm}_{num}", use_container_width=True):
                                        if st.session_state['perfil'] in ['preset', 'adm']:
                                            st.session_state['gaveta_selecionada'] = {
                                                'armario': arm, 'posicao': num, 'status': status, 'ordem': gav.get('Ordem', ''), 'item': gav.get('Item', ''), 'observacao': gav.get('Observacao', '')
                                            }
                                            st.rerun()
                                        else:
                                            st.error("⚠️ Apenas Pré-Set e ADM podem gerenciar gavetas!")

    # --- ABA 2: ALIMENTAR E EXCLUIR ORDEM (MODO CLÁSSICO LISTA) ---
    with aba2:
        if st.session_state['perfil'] in ['preset', 'adm']:
            with st.form("form_alimentar_lista", clear_on_submit=True):
                st.markdown("📥 **Guardar Ferramental / Setup**")
                c1, c2 = st.columns(2)
                armario_sel = c1.selectbox("Selecione o Armário:", ["Afiadoras 04 a 28", "Afiadoras 29 a 41", "Retíficas 05 a 28", "Retíficas 29 a 42"])
                
                pos_vazias = df_arm[(df_arm['Armario'] == armario_sel) & (df_arm['Status'] == 'VAZIO')]
                pos_vazias_lista = pos_vazias['Posicao'].tolist()
                
                if not pos_vazias_lista:
                    st.warning(f"O {armario_sel} está cheio!")
                    pos_sel = None
                else:
                    pos_vazias_sorted = sorted([int(x) for x in pos_vazias_lista])
                    pos_sel = c2.selectbox("Máquina Alvo:", [str(x) for x in pos_vazias_sorted])

                c_op, c_it = st.columns(2)
                ordem_in = c_op.text_input("Ordem de Produção (OP):", placeholder="Ex: 987654")
                item_in = c_it.text_input("Item / Peça:", placeholder="Ex: 313324")
                obs_in = st.text_input("Observação / Justificativa (Obrigatório se não houver OP):", placeholder="Justificativa...")

                if st.form_submit_button("📥 GUARDAR NO ARMÁRIO", type="primary"):
                    if not ordem_in.strip() and not obs_in.strip():
                        st.error("⚠️ A Ordem (OP) ou uma Observação justificando são obrigatórias!")
                    elif pos_sel is None:
                        st.error("⚠️ Não há posições disponíveis selecionadas!")
                    else:
                        ordem_limpa = ordem_in.strip().upper().replace(".0", "")
                        item_limpo = item_in.strip().upper().replace(".0", "")
                        obs_limpa = obs_in.strip()
                        
                        idx = df_arm[(df_arm['Armario'] == armario_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao']] = [
                                ordem_limpa, 
                                item_limpo, 
                                "AGUARDANDO MÁQUINA", 
                                datetime.now(FUSO_BR).strftime("%H:%M"),
                                obs_limpa
                            ]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.success(f"✅ Ferramental guardado para a MAQ {pos_sel} do {armario_sel}!")
                            time.sleep(1.5)
                            st.rerun()
        else:
            st.info("ℹ️ Apenas o perfil do Pré-Set e Administração pode inserir ou remover itens nos armários. Seu acesso permite apenas visualização.")

    # --- ABA 3: ALERTAS DE RETIRADA ---
    with aba3:
        st.markdown("#### 🔔 Histórico de Setups Retirados para a Produção")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Acompanhe em tempo real as OPs que os preparadores retiraram das gavetas e assumiram na máquina.</p>", unsafe_allow_html=True)
        if os.path.exists(ARQUIVO_ALERTAS):
            df_alertas = pd.read_csv(ARQUIVO_ALERTAS)
            if not df_alertas.empty:
                st.dataframe(df_alertas.sort_values(by="Data_Hora", ascending=False), use_container_width=True, hide_index=True)
                if st.session_state['perfil'] in ['preset', 'adm']:
                    if st.button("🗑️ Limpar Histórico de Alertas", type="secondary"):
                        os.remove(ARQUIVO_ALERTAS)
                        st.rerun()
            else:
                st.info("Nenhum alerta registrado ainda.")
        else:
            st.info("Nenhum alerta registrado ainda.")
            
    # --- ABA 4: AVISOS DE TROCA DE REBOLO COM DETALHES ---
    with aba4:
        st.markdown("#### 🔄 Alertas e Detalhamento de Rebolos")
        if st.session_state.get('perfil') in ['preset', 'adm']:
            st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Máquinas agendadas ou em andamento que necessitam de troca de rebolo. O sistema busca o Item automaticamente no Armário correspondente à máquina.</p>", unsafe_allow_html=True)
            
            df_rebolos = pd.DataFrame()
            if os.path.exists(ARQUIVO_REBOLOS):
                try:
                    import unicodedata
                    # Deixamos o Pandas adivinhar o tipo automaticamente para evitar o bug do ".0"
                    df_rebolos = pd.read_excel(ARQUIVO_REBOLOS)
                    
                    # 1. SUPER BLINDAGEM DE COLUNAS: Tira acentos, espaços e padroniza para maiúsculo
                    novas_colunas = []
                    for col in df_rebolos.columns:
                        col_str = str(col).upper()
                        col_str = unicodedata.normalize('NFKD', col_str).encode('ASCII', 'ignore').decode('ASCII')
                        col_str = col_str.replace(" ", "").replace("\n", "").strip()
                        novas_colunas.append(col_str)
                    df_rebolos.columns = novas_colunas
                    
                    if 'ITEM' in df_rebolos.columns:
                        # 2. SUPER BLINDAGEM DO ITEM: Converte pra string e arranca o ".0" e espaços
                        df_rebolos['ITEM_BUSCA'] = df_rebolos['ITEM'].astype(str).str.upper()
                        df_rebolos['ITEM_BUSCA'] = df_rebolos['ITEM_BUSCA'].apply(lambda x: re.sub(r'\.0$', '', x.strip()))
                except Exception as e:
                    st.error(f"⚠️ Erro ao ler a planilha '{ARQUIVO_REBOLOS}': {e}")

            status_dict = ler_status_atual()
            alertas_rebolo = []
            
            for maq, st_val in status_dict.items():
                if "(C/ REBOLO)" in st_val.upper() and "PRODUZINDO" not in st_val.upper():
                    hora_alvo = ""
                    if "AGENDADA PARA" in st_val.upper():
                        try: hora_alvo = st_val.upper().split("AGENDADA PARA")[1].strip()
                        except: pass
                    elif "[AGENDADO:" in st_val.upper():
                        try: hora_alvo = st_val.upper().split("[AGENDADO:")[1].split("]")[0].strip()
                        except: pass
                    
                    st_limpo = st_val.split("[")[0].strip()
                    item_alvo = ""
                    
                    try:
                        setor_maq, maq_num = maq.split(" ", 1)
                        gaveta_num = maq_num.split("-")[0]
                        filtro_armario = "Afiadoras" if setor_maq == "AFC" else "Retíficas"
                        
                        gaveta_row = df_arm[(df_arm['Posicao'] == gaveta_num) & (df_arm['Armario'].str.contains(filtro_armario))]
                        if not gaveta_row.empty:
                            item_alvo = str(gaveta_row.iloc[0]['Item']).strip().replace('.0', '').replace('nan', '')
                    except: pass
                        
                    if not item_alvo:
                        if "[Novo Item:" in st_val: item_alvo = st_val.split("[Novo Item:")[1].split("]")[0].strip()
                        elif "[Item Atual:" in st_val: item_alvo = st_val.split("[Item Atual:")[1].split("]")[0].strip()
                        elif "[Item:" in st_val: item_alvo = st_val.split("[Item:")[1].split("]")[0].strip()
                    
                    rebolo1, rebolo2, tipo_reb, desc = "Não cadastrado", "-", "Não cadastrado", ""
                    
                    if item_alvo and not df_rebolos.empty and 'ITEM_BUSCA' in df_rebolos.columns:
                        # Limpa o item alvo exatamente da mesma forma que a coluna
                        item_busca = str(item_alvo).strip().upper()
                        item_busca = re.sub(r'\.0$', '', item_busca)
                        
                        # Tenta match exato primeiro
                        match = df_rebolos[df_rebolos['ITEM_BUSCA'] == item_busca]
                        
                        # Se não achar exato (espaços invisíveis extras, etc), tenta achar se "contém" o número
                        if match.empty:
                            match = df_rebolos[df_rebolos['ITEM_BUSCA'].str.contains(item_busca, regex=False, na=False)]
                            
                        if not match.empty:
                            row_reb = match.iloc[0]
                            desc = str(row_reb.get('DESCRICAO', '')).strip()
                            rebolo1 = str(row_reb.get('REBOLO', row_reb.get('REBOLO1', ''))).strip()
                            rebolo2 = str(row_reb.get('REBOLO2', '')).strip()
                            tipo_reb = str(row_reb.get('TIPO', '')).strip()
                            
                            # Tratamento de dados nulos/vazios
                            if rebolo1.lower() in ['nan', 'none', '']: rebolo1 = "Não cadastrado"
                            if rebolo2.lower() in ['nan', 'none', '']: rebolo2 = "-"
                            if tipo_reb.lower() in ['nan', 'none', '']: tipo_reb = "-"
                            if desc.lower() in ['nan', 'none', '']: desc = ""

                    alertas_rebolo.append((maq, hora_alvo, st_limpo, item_alvo, desc, rebolo1, rebolo2, tipo_reb))
                    
            if alertas_rebolo:
                for maq, hora, st_limpo, item_alvo, desc, reb1, reb2, tipo_reb in alertas_rebolo:
                    h_txt = f"⏰ Agendado para as {hora}" if hora else "🔴 Em Andamento / Imediato"
                    
                    if item_alvo:
                        desc_str = f"({desc})" if desc else ""
                        reb2_html = f"<p style='margin: 4px 0 0 0; font-size: 13px; color: #A1A1AA;'>🔄 Rebolo 2: <b style='color: #2DD4BF;'>{reb2}</b></p>" if reb2 and reb2 != '-' else ""
                        info_reb = f"""
                        <div style='background-color: #27272A; padding: 10px; border-radius: 6px; margin-top: 10px; border: 1px solid #3F3F46;'>
                            <p style='margin: 0; font-size: 13px; color: #A1A1AA;'>📦 Item no Armário: <b style='color: #F4F4F5;'>{item_alvo}</b> <span style='color:#71717A;'>{desc_str}</span></p>
                            <p style='margin: 4px 0 0 0; font-size: 13px; color: #A1A1AA;'>🔄 Rebolo 1: <b style='color: #2DD4BF;'>{reb1}</b></p>
                            {reb2_html}
                            <p style='margin: 4px 0 0 0; font-size: 13px; color: #A1A1AA;'>🏷️ Tipo: <b style='color: #F4F4F5;'>{tipo_reb}</b></p>
                        </div>
                        """
                    else:
                        info_reb = f"""
                        <div style='background-color: #27272A; padding: 10px; border-radius: 6px; margin-top: 10px; border: 1px solid #3F3F46;'>
                            <p style='margin: 0; font-size: 13px; color: #ef4444;'>⚠️ Gaveta vazia e item não informado no apontamento. Impossível buscar rebolo.</p>
                        </div>
                        """

                    st.markdown(f"""
                    <div style='background-color: #422006; padding: 15px; border-radius: 8px; border-left: 5px solid #f59e0b; margin-bottom: 10px;'>
                        <h5 style='margin-top:0; margin-bottom:5px; color: #fbbf24;'>⚙️ Máquina {maq} irá trocar o rebolo</h5>
                        <p style='color: #fef3c7; margin-bottom:0; font-size:14px;'>{h_txt} <br><span style='font-size:13px; color:#d97706;'>Status Atual: {st_limpo}</span></p>
                        {info_reb}
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.success("✅ Nenhuma máquina com troca de rebolo prevista no momento.")
        else:
            st.info("ℹ️ Aba restrita para os perfis de Pré-Set e Administração.")

# --- ROTEADOR ---
if st.session_state['tela_atual'] == 'login': tela_login()
elif st.session_state['tela_atual'] == 'menu': tela_menu()
elif st.session_state['tela_atual'] == 'checkup': tela_checkup()
elif st.session_state['tela_atual'] == 'historico': tela_historico()
elif st.session_state['tela_atual'] == 'minhas_incidencias': tela_minhas_incidencias()
elif st.session_state['tela_atual'] == 'afc': tela_afc()
elif st.session_state['tela_atual'] == 'rtf': tela_rtf()
elif st.session_state['tela_atual'] == 'equipe': tela_equipe()
elif st.session_state['tela_atual'] == 'editar': tela_editar()
elif st.session_state['tela_atual'] == 'relatorio': tela_relatorio()
elif st.session_state['tela_atual'] == 'armarios': tela_armarios()