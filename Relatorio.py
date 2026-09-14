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
ARQUIVO_CNC = "banco_cnc.csv"
ARQUIVO_FECHAMENTO = "ultimo_fechamento.csv"

# --- FUNÇÕES UTILITÁRIAS ---
def turno_atual_horario():
    agora = datetime.now(FUSO_BR).time()
    if dtime(6, 30) <= agora < dtime(14, 30): return "1° TURNO"
    elif dtime(14, 30) <= agora < dtime(22, 30): return "2° TURNO"
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
        if eh_espera:
            if diff < -720: return int(diff + 1440)
            elif diff < 0: return 0
            return int(diff)
        else:
            if diff < 0: return int(diff + 1440)
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
    if dtime(6, 30) <= t < dtime(14, 30): return d.strftime("%d/%m/%Y"), "1° TURNO"
    elif dtime(14, 30) <= t < dtime(22, 30): return d.strftime("%d/%m/%Y"), "2° TURNO"
    else:
        if t < dtime(6, 30): d -= timedelta(days=1)
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
    def salvar_ciclo(maq_num, h_agenda, h_inicio, h_assumido, h_fim, p1, p2, st_final=""):
        if h_inicio is None: return (h_agenda if h_agenda else '00:00', f"Máquina {maq_num}: Aguardando preparador desde as {h_agenda}.\nPreparador sugerido: AGUARDANDO OPERADOR\n\n")
        
        t_espera_mins = diff_mins(h_agenda, h_inicio, eh_espera=True) if h_agenda else 0
        t_espera = format_tempo(t_espera_mins)
        h_conclusao = h_fim if h_fim else datetime.now(FUSO_BR).strftime("%H:%M")
        txt_maq = f"Máquina {maq_num}: Aguardou {t_espera} até o preparador iniciar.\n"
        
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
        return (h_agenda if h_agenda else h_inicio, txt_maq)

    for maq in maquinas:
        if not maq.startswith(prefixo): continue
        df_hist = df_all[df_all['Maquina'] == maq]
        ciclo_ativo, hora_agenda, hora_inicio, hora_assumido, hora_fim, prep_1, prep_2 = False, None, None, None, None, None, None
        for _, h_row in df_hist.iterrows():
            st_val, h_val = str(h_row['Status']).upper(), str(h_row['Hora'])
            if "ENERGIA RESTAURADA" in st_val: continue
            
            if "PREPARAÇÃO" in st_val or "SEQUÊNCIA" in st_val or "AGUARDANDO" in st_val:
                if not ciclo_ativo:
                    ciclo_ativo, hora_agenda = True, h_val
                    if "[AGENDADO:" in st_val:
                        try: hora_agenda = st_val.split("[AGENDADO:")[1].split("]")[0].strip()
                        except: pass
                    hora_inicio, hora_assumido, hora_fim, prep_1, prep_2 = None, None, None, None, None
            elif "PREPARANDO" in st_val:
                ciclo_ativo = True
                if not hora_agenda: hora_agenda = h_val
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
                texto_saida.append(salvar_ciclo(maq.replace(f"{prefixo} ", ""), hora_agenda, hora_inicio, hora_assumido, hora_fim, prep_1, prep_2, st_val))
                ciclo_ativo = False
        if ciclo_ativo: texto_saida.append(salvar_ciclo(maq.replace(f"{prefixo} ", ""), hora_agenda, hora_inicio, hora_assumido, None, prep_1, prep_2, ""))
    texto_saida.sort(key=lambda x: get_sort_key(x[0]))
    return "".join([i[1] for i in texto_saida])

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
            
            quedas_list = list(quedas)
            retornos_list = list(retornos)
            
            for i, h_q in enumerate(quedas_list):
                h_r = retornos_list[i] if i < len(retornos_list) else "Sem retorno"
                duração = format_tempo(diff_mins(h_q, h_r)) if h_r != "Sem retorno" else "Em andamento"
                turno_queda = obter_turno_por_horario(h_q)
                texto_padrao += f"- Data: {data_alvo} | Turno: {turno_queda} | Queda às {h_q} | Restaurada às {h_r} (Duração: {duração})\n"
            texto_padrao += "\n"
        else: texto_padrao += "Nenhuma queda de energia registrada.\n\n"
    
    texto_padrao += "*MAQUINAS EM MANUTENÇAO*\n\n"
    manutencao_rows = df_ultimo_geral[df_ultimo_geral['Status'].str.contains('MANUTENÇÃO', na=False)]
    if manutencao_rows.empty: texto_padrao += "N/A\n\n"
    else:
        for _, row in manutencao_rows.iterrows():
            num_maq = row['Maquina'].replace("AFC ", "").replace("RTF ", "")
            texto_padrao += f"{num_maq} - MANUTENÇÃO - {row['Hora']}\n"
        texto_padrao += "\n"

    texto_padrao += "*MÁQUINAS PARADAS*\n\n"
    parada_rows = df_ultimo_geral[df_ultimo_geral['Status'].str.contains('PARADA', na=False) & ~df_ultimo_geral['Status'].str.contains('Energia', na=False)]
    if parada_rows.empty: texto_padrao += "N/A\n\n"
    else:
        for _, row in parada_rows.iterrows():
            num_maq = row['Maquina'].replace("AFC ", "").replace("RTF ", "")
            motivo = row['Status'].replace("PARADA - Motivo: ", "")
            texto_padrao += f"{num_maq} - PARADA - {row['Hora']} ({motivo})\n"
        texto_padrao += "\n"

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
    
    if turno_real == "1° TURNO": hora_corte = "06:30"
    elif turno_real == "2° TURNO": hora_corte = "14:30"
    else: hora_corte = "22:30"
    
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
                if turno_real == "1° TURNO" and diff_mins(hora_registro, "06:30") > 0 and diff_mins("06:30", hora_registro) > 12*60: precisa_cortar = True
                elif turno_real == "2° TURNO" and diff_mins(hora_registro, "14:30") > 0 and diff_mins(hora_registro, "14:30") < 8*60: precisa_cortar = True
                elif turno_real == "3° TURNO" and diff_mins(hora_registro, "22:30") > 0 and diff_mins(hora_registro, "22:30") < 8*60: precisa_cortar = True
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

# --- FUNÇÕES DE ARMÁRIOS ---
def inicializar_armarios():
    precisa_criar = False
    
    # Se o arquivo não existe, cria do zero.
    if not os.path.exists(ARQUIVO_ARMARIOS):
        precisa_criar = True
    else:
        # Se existe, verifica se ele está com os nomes antigos.
        try:
            df_temp = pd.read_csv(ARQUIVO_ARMARIOS)
            if "Afiadoras 04 a 28" not in df_temp['Armario'].values:
                precisa_criar = True
        except:
            precisa_criar = True
            
    if precisa_criar:
        dados = []
        # Pega apenas os números das máquinas extraindo o valor antes do traço "-"
        afc_nums = sorted([int(m.split('-')[0]) for m in TODAS_AFC])
        # Pega RTF, mas descarta os números abaixo de 5 (ignora 3 e 4)
        rtf_nums = sorted([int(m.split('-')[0]) for m in TODAS_RTF if int(m.split('-')[0]) >= 5])
        
        # Divide as máquinas nos 4 armários de acordo com a distribuição
        mapa_armarios = {
            "Afiadoras 04 a 28": [m for m in afc_nums if m <= 28],
            "Afiadoras 29 a 41": [m for m in afc_nums if m >= 29],
            "Retíficas 05 a 22": [m for m in rtf_nums if m <= 22],
            "Retíficas 23 a 42": [m for m in rtf_nums if m >= 23]
        }
        
        for arm, maquinas in mapa_armarios.items():
            for maq in maquinas:
                dados.append({"Armario": arm, "Posicao": str(maq), "Ordem": "", "Item": "", "Status": "VAZIO", "Data_Hora": ""})
                
        pd.DataFrame(dados).to_csv(ARQUIVO_ARMARIOS, index=False)

def dar_baixa_armario(ordem_alvo):
    if not ordem_alvo or not str(ordem_alvo).strip() or not os.path.exists(ARQUIVO_ARMARIOS): return
    try:
        ordem_formatada = str(ordem_alvo).strip().upper().replace(".0", "")
        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str})
        if 'Item' not in df_arm.columns: df_arm['Item'] = ""
        df_arm['Ordem_busca'] = df_arm['Ordem'].astype(str).str.strip().str.upper().str.replace(".0", "", regex=False)
        idx_ordem = df_arm[df_arm['Ordem_busca'] == ordem_formatada].index
        if not idx_ordem.empty:
            df_arm.loc[idx_ordem, ['Ordem', 'Item', 'Status', 'Data_Hora']] = ["", "", 'VAZIO', datetime.now(FUSO_BR).strftime("%H:%M")]
            df_arm = df_arm.drop(columns=['Ordem_busca'])
            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
    except: pass

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
    for marcador in ["[Item Atual:", "[Novo Item:", "[Ordem:", "[Item:", "[Pçs/Hora:", "[Obs:"]:
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
            
            if "[AGENDADO:" in st_raw:
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
        if flow_key not in st.session_state: st.session_state[flow_key] = "pergunta"
        st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        
        is_setup_ativo = "PREPARANDO" in status_atual or "SEQUÊNCIA" in status_atual
        
        if "AGUARDANDO PREPARADOR" in status_atual or "AGENDADO" in status_atual or "AGENDADA" in status_atual: st.session_state[flow_key] = "acoes_espera"
        
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
                        dar_baixa_armario(op_ext)
                    
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
                if "[Ordem:" in st_atual:
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                    tags_prod = extrair_tags_producao(st_atual)
                    tags_prod = tags_prod.replace("[Novo Item:", "[Item:")
                    tags_prod = tags_prod.replace("[Item Atual:", "[Item:")
                    st_final = f"PRODUZINDO {tags_prod}".strip()
                    op_ext = st_atual.split("[Ordem:")[1].split("]")[0].strip()
                    dar_baixa_armario(op_ext)
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
                        
                        dar_baixa_armario(ordem_limpa)
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
                        
                    st_final = f"PARADA - Motivo: {mot_final}"
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.success("✅ Máquina registrada como PARADA!")
                    time.sleep(0.5)
                    st.rerun()

        elif st.session_state[flow_key] == "detalhe_prep":
            with st.form(f"form_prep_{maq_id}"):
                st.markdown("⚙️ **Configuração de Preparação / Agendamento**")
                hora_relatorio = st.text_input("⏰ Horário Alvo (Aparecerá no Relatório):", value="", placeholder="Ex: 12:30")
                is_agendado = st.toggle("Marcar como Agendamento Futuro", value=True)
                prep_sugerido = st.text_input("🧑‍🔧 Sugerir Preparador (Opcional):", placeholder="Ex: Lucas")
                
                st.markdown("📦 **Dados do Item**")
                ordem_atual = st.text_input("Ordem Atual (OP):", placeholder="Ex: 987654")
                item_atual = st.text_input("Item Atual (Na Máquina):", placeholder="Ex: 313324")
                
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
                        
                        if ordem_limpa: dar_baixa_armario(ordem_limpa)
                            
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
                novo_item_input = ""
                
                if is_comum:
                    nova_ordem_input = st.text_input("Nova Ordem (OP) Entrando:", placeholder="Ex: 987654")
                    novo_item_input = st.text_input("Novo Item (Entrando):", placeholder="Ex: 313324")
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
                
                c1, c2 = st.columns(2)
                btn_sugerir = c1.form_submit_button("💡 Apenas Sugerir")
                btn_iniciar = c2.form_submit_button("🚀 INICIAR PREPARAÇÃO", type="primary")
                
                if btn_adiar:
                    if novo_horario_adiar.strip():
                        info_atual = obter_info_maquina(maq_id, setor)
                        if info_atual:
                            raw_st = str(info_atual['Status'])
                            if "[AGENDADO:" in raw_st: raw_st = re.sub(r'\[AGENDADO:.*?\]', f"[AGENDADO:{novo_horario_adiar.strip()}]", raw_st)
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
                            if "[AGENDADO:" in raw_st: raw_st = raw_st.replace(" [AGENDADO:", f" [Prep. Sugerido: {nome_input.strip().upper()}] [AGENDADO:")
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
                    if is_comum and (not nova_ordem_input.strip() or not novo_item_input.strip()):
                        st.error("⚠️ Para INICIAR a preparação, informe a Nova Ordem e o Item!")
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
                        novo_item_limpo = novo_item_input.strip().upper().replace(".0", "")

                        if is_comum:
                            st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                            st_andamento += f" [Novo Item: {novo_item_limpo}]"
                            dar_baixa_armario(nova_ordem_limpa)
                        elif is_seq:
                            st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                            dar_baixa_armario(nova_ordem_limpa)
                            
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
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": f"MANUTENÇÃO - Motivo: {motivo}", "Hora": hora_br_str}, ARQUIVO_DADOS)
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
        if st.button("🔍 INCIDÊNCIAS GERAL", use_container_width=True): mudar_tela('checkup')
        if st.button("👥 CONTROLE DE EQUIPE", use_container_width=True): mudar_tela('equipe')
        if st.button("📋 RELATÓRIO GERAL CONSOLIDADO", use_container_width=True): mudar_tela('relatorio')
        if st.button("📊 HISTÓRICOS E EXPORTAÇÕES", use_container_width=True): mudar_tela('historico')
        if st.button("✏️ GERENCIAR BANCO DE DADOS", use_container_width=True): mudar_tela('editar')
    elif perfil == 'preset':
        if st.button("🗄️ GERENCIAR ARMÁRIOS", use_container_width=True, type="primary"): mudar_tela('armarios')
        if st.button("🔍 VER INCIDÊNCIAS DO SETOR", use_container_width=True): mudar_tela('checkup')
    elif perfil == 'preparador':
        if st.session_state['setor_usuario'] in ['AFC', 'TECNICO']:
            if st.button("⚙️ ACESSAR MÓDULO AFIAÇÃO", use_container_width=True, type="primary"): mudar_tela('afc')
        if st.session_state['setor_usuario'] in ['RTF', 'TECNICO']:
            if st.button("⚙️ ACESSAR MÓDULO RETÍFICA", use_container_width=True, type="primary"): mudar_tela('rtf')
        if st.button("🗄️ VISÃO DOS ARMÁRIOS", use_container_width=True): mudar_tela('armarios')
        if st.button("🔍 INCIDÊNCIAS DO SETOR", use_container_width=True): mudar_tela('checkup')
        if st.button("⚡ MINHAS INCIDÊNCIAS", use_container_width=True, type="primary"): mudar_tela('minhas_incidencias')
        if st.button("👥 CONTROLE DE EQUIPE", use_container_width=True): mudar_tela('equipe')
        if st.button("📋 RELATÓRIO DE TURNO", use_container_width=True): mudar_tela('relatorio')
        if st.button("✏️ CORREÇÃO DE APONTAMENTOS", use_container_width=True): mudar_tela('editar')
    else:
        if st.button("🔍 INCIDÊNCIAS DO SETOR", use_container_width=True): mudar_tela('checkup')
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
    st.markdown("#### 🔍 Incidências no Setor")
    st.divider()
    status_dict = ler_status_atual()
    perfil = st.session_state['perfil']
    setor_atual = st.session_state['setor_usuario']
    
    if setor_atual in ['TECNICO', 'GERAL', 'GERÊNCIA', 'PRESET'] or perfil == 'adm': setores_alvo = [("AFC", TODAS_AFC), ("RTF", TODAS_RTF)]
    else: setores_alvo = [(setor_atual, TODAS_AFC if setor_atual == "AFC" else TODAS_RTF)]
        
    maquinas_com_problema = []
    for s_nome, lista in setores_alvo:
        for m in lista:
            st_val = status_dict.get(f"{s_nome} {m}", "PRODUZINDO")
            if "PRODUZINDO" not in st_val or "AGENDADO" in st_val or "AGENDADA" in st_val or "AGUARDANDO" in st_val:
                maquinas_com_problema.append((s_nome, m, st_val))
            
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo']:
        painel_controle_maquina(st.session_state['maq_ativa'], st.session_state['setor_ativo'])
        st.divider()

    if not maquinas_com_problema: st.success("✨ Ótimo! Nenhuma incidência registrada no momento.")
    else:
        for setor_m, maq_m, st_m in maquinas_com_problema:
            icone = get_status_icon(st_m)
            if st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"chk_{setor_m}_{maq_m}", use_container_width=True):
                st.session_state['maq_ativa'] = maq_m
                st.session_state['setor_ativo'] = setor_m
                st.rerun()

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
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("#### 🗄️ Gestão de Armários (Pré-Set)")
    
    inicializar_armarios()
    df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str})
    if 'Item' not in df_arm.columns: df_arm['Item'] = ""

    gaveta = st.session_state.get('gaveta_selecionada', None)

    # --- MODAL / PAINEL DE AÇÃO NO TOPO ---
    if gaveta:
        arm_sel = gaveta['armario']
        pos_sel = gaveta['posicao']
        status_sel = gaveta['status']
        op_sel = gaveta['ordem']
        item_sel = gaveta['item']
        
        st.markdown(f"""
        <div style='background: #18181B; padding: 15px; border-radius: 10px; border-left: 4px solid #14B8A6; margin-bottom: 20px;'>
            <h4 style='margin:0; color: #2DD4BF;'>⚙️ Gerenciar: {arm_sel} - MÁQUINA {pos_sel}</h4>
        </div>
        """, unsafe_allow_html=True)
        
        if status_sel == 'VAZIO':
            with st.form("form_alimentar"):
                st.info("⬛ Esta gaveta está VAZIA. Insira os dados para guardar o setup.")
                c_op, c_it = st.columns(2)
                ordem_in = c_op.text_input("Ordem de Produção (OP):", placeholder="Ex: 987654")
                item_in = c_it.text_input("Item / Peça:", placeholder="Ex: 313324")
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("📥 GUARDAR SETUP", type="primary", use_container_width=True):
                    if not ordem_in.strip() or not item_in.strip():
                        st.error("⚠️ OP e Item são obrigatórios!")
                    else:
                        ordem_limpa = ordem_in.strip().upper().replace(".0", "")
                        item_limpo = item_in.strip().upper().replace(".0", "")
                        
                        idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora']] = [ordem_limpa, item_limpo, "AGUARDANDO MÁQUINA", datetime.now(FUSO_BR).strftime("%H:%M")]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.session_state['gaveta_selecionada'] = None
                            st.success(f"✅ Setup guardado na gaveta da MÁQUINA {pos_sel}!")
                            time.sleep(1)
                            st.rerun()
                if c2.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        else:
            with st.form("form_excluir"):
                st.warning(f"🟩 Gaveta OCUPADA - OP: {op_sel} | Item: {item_sel}")
                st.write("Deseja remover este setup do armário e liberar a gaveta?")
                c1, c2 = st.columns(2)
                if c1.form_submit_button("🗑️ EXCLUIR SETUP", type="primary", use_container_width=True):
                    idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                    if not idx.empty:
                        df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora']] = ["", "", "VAZIO", datetime.now(FUSO_BR).strftime("%H:%M")]
                        df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                        st.session_state['gaveta_selecionada'] = None
                        st.success("✅ Gaveta liberada com sucesso!")
                        time.sleep(1)
                        st.rerun()
                if c2.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        
        st.divider()

    # --- RENDENRIZAÇÃO DOS ARMÁRIOS (GRID) ---
    st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Visão estrutural. <b>Clique diretamente na gaveta</b> para alimentar (guardar) ou excluir a OP.</p>", unsafe_allow_html=True)
    
    armarios_lista = ["Afiadoras 04 a 28", "Afiadoras 29 a 41", "Retíficas 05 a 22", "Retíficas 23 a 42"]
    
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
                                    btn_label = f"⬛ MAQ {num}\nVAZIO"
                                else:
                                    op_f = str(gav['Ordem']).replace('.0', '').replace('nan', '')
                                    btn_label = f"🟩 MAQ {num}\nOP: {op_f}"
                                    
                                if cols_gaveta[c].button(btn_label, key=f"btn_gav_{arm}_{num}", use_container_width=True):
                                    if st.session_state['perfil'] in ['preset', 'adm']:
                                        st.session_state['gaveta_selecionada'] = {
                                            'armario': arm, 'posicao': num, 'status': status, 'ordem': gav['Ordem'], 'item': gav['Item']
                                        }
                                        st.rerun()
                                    else:
                                        st.error("⚠️ Apenas Pré-Set e ADM podem gerenciar gavetas!")

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