import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# --- CONFIGURAÇÃO BASE DO APP ---
st.set_page_config(page_title="App MES - Planta", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

# --- CSS COMPACTO PARA MOBILE ---
CSS_APP = """
<style>
    .stApp { background-color: #121214 !important; }
    h1, h2, h3, h4, h5, p, span, div[data-testid="stMarkdownContainer"] { color: #F8FAFC !important; font-family: 'Inter', sans-serif !important; }
    label { color: #A1A1AA !important; font-size: 11px !important; font-weight: 600 !important; }
    
    .block-container { 
        padding-top: 0.4rem !important; 
        padding-bottom: 0.4rem !important; 
        padding-left: 0.4rem !important; 
        padding-right: 0.4rem !important; 
        max-width: 100% !important; 
    }
    
    button[kind="secondary"] { 
        background-color: #202024 !important; 
        color: #E4E4E7 !important; 
        border: 1px solid #323238 !important; 
        border-radius: 6px !important; 
        font-weight: bold !important; 
        height: 42px !important; 
        font-size: 12px !important;
        width: 100% !important;
        margin-bottom: 4px !important;
    }
    button[kind="secondary"]:hover { border-color: #14B8A6 !important; background-color: #27272A !important; }
    
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { 
        background-color: #0D9488 !important; 
        color: white !important; 
        border: none !important; 
        border-radius: 6px !important; 
        height: 42px !important; 
        font-size: 12px !important; 
        font-weight: bold !important; 
        width: 100% !important;
    }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { 
        background-color: #202024 !important; 
        border: 1px solid #323238 !important; 
        border-radius: 6px !important; 
        min-height: 32px !important; 
    }
    input, select, textarea { color: white !important; font-size: 12px !important; }
    header { visibility: hidden; }
</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"

MAPA_STATUS = {
    "PRODUZINDO": "🟢",
    "PREPARAÇÃO": "🟡",
    "SEQUÊNCIA": "🟡",
    "MANUTENÇÃO": "🛠️",
    "PARADA": "🔴"
}

# --- GERENCIAMENTO DE ESTADO ---
if 'tela_atual' not in st.session_state:
    st.session_state['tela_atual'] = 'login'
if 'operador' not in st.session_state:
    st.session_state['operador'] = ''
if 'turno' not in st.session_state:
    st.session_state['turno'] = ''
if 'setor_usuario' not in st.session_state:
    st.session_state['setor_usuario'] = ''
if 'celula_selecionada' not in st.session_state:
    st.session_state['celula_selecionada'] = None
if 'maq_ativa' not in st.session_state:
    st.session_state['maq_ativa'] = None

def mudar_tela(nome_tela):
    st.session_state['tela_atual'] = nome_tela
    st.session_state['celula_selecionada'] = None
    st.session_state['maq_ativa'] = None
    st.rerun()

# --- FUNÇÕES DE DADOS ---
def ler_status_atual():
    if not os.path.exists(ARQUIVO_DADOS):
        return {}
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        df['Status_Base'] = df['Status'].apply(lambda x: str(x).split(" (")[0].split(" - ")[0].replace("🟢 ", "").replace("🟡 ", "").replace("🛠️ ", "").replace("🔴 ", ""))
        df_ultimo = df.drop_duplicates(subset=['Maquina'], keep='last')
        return dict(zip(df_ultimo['Maquina'], df_ultimo['Status_Base']))
    except:
        return {}

def obter_info_maquina(maq_id, setor):
    if not os.path.exists(ARQUIVO_DADOS):
        return None
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        if not df_maq.empty:
            return df_maq.iloc[-1].to_dict()
    except:
        pass
    return None

def salvar_csv(dados, arquivo):
    df_novo = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df_existente = pd.read_csv(arquivo)
        df_existente = pd.concat([df_existente, df_novo], ignore_index=True)
        df_existente.to_csv(arquivo, index=False)
    else:
        df_novo.to_csv(arquivo, index=False)

# ==========================================
#        PAINEL DE CONTROLE DA MÁQUINA
# ==========================================
def painel_controle_maquina(maq_id, setor):
    with st.container(border=True):
        col_t, col_f = st.columns([8, 1])
        col_t.markdown(f"**⚙️ Máq: {maq_id}**")
        if col_f.button("❌", key=f"fechar_{maq_id}"):
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        info = obter_info_maquina(maq_id, setor)
        status_atual = info.get('Status', 'PRODUZINDO') if info else 'PRODUZINDO'
        hora_atual = info.get('Hora', '--:--') if info else ''
        
        limpo_status = status_atual.split(" - ")[0].replace("🟢 ", "").replace("🟡 ", "").replace("🛠️ ", "").replace("🔴 ", "")
        
        if limpo_status == "PRODUZINDO":
            st.success(f"🟢 Produzindo")
        elif limpo_status == "PARADA":
            st.error(f"🔴 Parada desde {hora_atual}")
        elif limpo_status == "MANUTENÇÃO":
            st.warning(f"🛠️ Manutenção desde {hora_atual}")
        else:
            st.info(f"🟡 {limpo_status} desde {hora_atual}")
            
        flow_key = f"flow_{maq_id}"
        if flow_key not in st.session_state:
            st.session_state[flow_key] = "pergunta"
            
        if st.session_state[flow_key] == "pergunta":
            st.write(f"Esta máquina ainda está em **{limpo_status}**?")
            c1, c2 = st.columns(2)
            if c1.button("✅ Sim", key=f"s_{maq_id}", use_container_width=True):
                st.session_state['maq_ativa'] = None
                if flow_key in st.session_state:
                    del st.session_state[flow_key]
                st.rerun()
            if c2.button("❌ Não", key=f"n_{maq_id}", use_container_width=True):
                st.session_state[flow_key] = "mudanca_status"
                st.rerun()
                
        elif st.session_state[flow_key] == "mudanca_status":
            st.markdown("##### Qual o status dela agora?")
            if st.button("🟢 PRODUZINDO", key=f"st_prod_{maq_id}", use_container_width=True):
                salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": "PRODUZINDO", "Hora": datetime.now().strftime("%H:%M")}, ARQUIVO_DADOS)
                st.session_state['maq_ativa'] = None
                del st.session_state[flow_key]
                st.rerun()
            if st.button("🟡 PREPARAÇÃO", key=f"st_prep_{maq_id}", use_container_width=True):
                st.session_state[flow_key] = "detalhe_prep"
                st.rerun()
            if st.button("🛠️ MANUTENÇÃO", key=f"st_man_{maq_id}", use_container_width=True):
                st.session_state[flow_key] = "detalhe_man"
                st.rerun()
            if st.button("🔴 PARADA", key=f"st_par_{maq_id}", use_container_width=True):
                salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": "PARADA", "Hora": datetime.now().strftime("%H:%M")}, ARQUIVO_DADOS)
                st.session_state['maq_ativa'] = None
                del st.session_state[flow_key]
                st.rerun()

        elif st.session_state[flow_key] == "detalhe_prep":
            with st.form(f"form_prep_{maq_id}"):
                st.write("Detalhes da Preparação:")
                tipo_prep = st.radio("Setup:", ["HASTE", "GUIA"], horizontal=True)
                troca_diametro = False
                if tipo_prep == "HASTE":
                    troca_diametro = st.toggle("📐 Troca Diâmetro?")
                troca_rebolo = st.toggle("🔄 Troca Rebolo?")
                
                # Pergunta de passagem de turno caso continue em preparação
                proximo_turno_num = "2° Turno" if "1" in st.session_state['turno'] else ("3° Turno" if "2" in st.session_state['turno'] else "1° Turno")
                ficar_proximo = st.radio(f"Vai ficar para o {proximo_turno_num} terminar?", ["Não", "Sim"], horizontal=True)
                
                if st.form_submit_button("💾 Salvar Preparação", type="primary"):
                    st_final = f"PREPARAÇÃO - {tipo_prep}"
                    if tipo_prep == "HASTE" and troca_diametro: st_final += " (C/ Diâmetro)"
                    if troca_rebolo: st_final += " (C/ Rebolo)"
                    if ficar_proximo == "Sim": st_final += f" [Fica para {proximo_turno_num}]"
                    
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": datetime.now().strftime("%H:%M")}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.success("✅ Salvo!")
                    time.sleep(0.5)
                    st.rerun()

        elif st.session_state[flow_key] == "detalhe_man":
            with st.form(f"form_man_{maq_id}"):
                motivo = st.text_input("📝 Motivo da Manutenção (Obrigatório):", placeholder="Ex: Quebra...")
                if st.form_submit_button("💾 Salvar Manutenção", type="primary"):
                    if not motivo.strip():
                        st.error("Informe o motivo!")
                    else:
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": f"MANUTENÇÃO - Motivo: {motivo}", "Hora": datetime.now().strftime("%H:%M")}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Salvo!")
                        time.sleep(0.5)
                        st.rerun()

# ==========================================
#               TELAS DO APP
# ==========================================

def tela_login():
    st.markdown("<h3 style='text-align: center; color: #14B8A6 !important; margin-top: 20px;'>🏭 App MES</h3>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #A1A1AA; font-size: 11px;'>Digite o código de acesso (ex: 1123, 1234, etc.)</p>", unsafe_allow_html=True)
    
    cod = st.text_input("Código de Acesso:", type="password", placeholder="Digite o código...")
    nome = st.text_input("Seu Nome ou RE:", placeholder="Seu nome...")
    
    if st.button("ENTRAR NO SISTEMA", use_container_width=True, type="primary"):
        codigos_validos = {
            "1123": ("1° TURNO", "AFC", "Afiação"),
            "1234": ("1° TURNO", "RTF", "Retífica"),
            "2123": ("2° TURNO", "AFC", "Afiação"),
            "2234": ("2° TURNO", "RTF", "Retífica"),
            "3123": ("3° TURNO", "AFC", "Afiação"),
            "3234": ("3° TURNO", "RTF", "Retífica")
        }
        
        if cod in codigos_validos and nome:
            st.session_state['turno'], st.session_state['setor_usuario'], setor_nome = codigos_validos[cod]
            st.session_state['operador'] = nome.upper()
            mudar_tela('menu')
        else:
            st.error("⚠️ Código inválido ou Nome em branco.")

def tela_menu():
    st.markdown(f"<p style='margin:0px;'><b>{st.session_state['operador']}</b> | {st.session_state['turno']} | Setor: <b>{'Afiação' if st.session_state['setor_usuario']=='AFC' else 'Retífica'}</b></p>", unsafe_allow_html=True)
    st.divider()
    
    # Exibe o botão do setor liberado pelo código
    if st.session_state['setor_usuario'] == 'AFC':
        if st.button("⚙️ ACESSAR MÓDULO AFIAÇÃO", use_container_width=True, type="primary"): mudar_tela('afc')
    else:
        if st.button("⚙️ ACESSAR MÓDULO RETÍFICA", use_container_width=True, type="primary"): mudar_tela('rtf')
        
    if st.button("🔍 CHECK-UP DE ANOMALIAS (PARADAS / SETUP)", use_container_width=True): mudar_tela('checkup')
    if st.button("👥 EQUIPE", use_container_width=True): mudar_tela('equipe')
    if st.button("✏️ EDITAR DADOS", use_container_width=True): mudar_tela('editar')
    if st.button("📋 RELATÓRIO DE TURNO", use_container_width=True): mudar_tela('relatorio')
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 Sair (Logout)", use_container_width=True):
        st.session_state['operador'] = ''
        mudar_tela('login')

def render_grid_vertical(lista_maquinas, setor, status_dict):
    for maq in lista_maquinas:
        if maq == "":
            st.write("")
        else:
            chave_busca = f"{setor} {maq}"
            status_atual = status_dict.get(chave_busca, "PRODUZINDO")
            icone = MAPA_STATUS.get(status_atual.split(" - ")[0], "🟢")
            
            label_botao = f"{icone} Máquina {maq} ({status_atual})"
            if st.button(label_botao, key=f"btn_vert_{setor}_{maq}", use_container_width=True):
                st.session_state['maq_ativa'] = maq
                st.session_state['setor_ativo'] = setor
                st.rerun()

def tela_checkup():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### 🔍 Check-up de Anomalias")
    
    status_dict = ler_status_atual()
    setor_atual = st.session_state['setor_usuario']
    
    todas_afc = [
        "30-161", "29-078", "32-081", "31-969", "34-132", "33-160", "36-084", "35-131",
        "38-596", "37-892", "40-142", "39-905", "41-141", "8-247", "6-868", "4-427", "9-088",
        "10-812", "7-743", "12-367", "11-365", "14-967", "13-964", "16-975", "15-973",
        "18-957", "17-140", "20-774", "19-760", "22-813", "21-206", "24-761", "23-165",
        "26-635", "25-209", "28-432", "27-431"
    ]
    todas_rtf = [
        "6-6J1", "17-6J1", "30-786", "32-918", "29-785", "4-425", "3-426",
        "34-842", "31-806", "7-267", "5-903", "36-854", "33-807", "9-815", "8-086",
        "38-881", "35-885", "11-363", "10-817", "40-912", "37-857", "13-969",
        "12-962", "42-885", "39-856", "15-977", "14-971", "18-925", "16-183",
        "20-927", "19-926", "22-916", "21-270", "24-259", "23-753", "26-260",
        "25-258", "28-954", "27-917"
    ]
    
    maquinas_com_problema = []
    lista_alvo = todas_afc if setor_atual == "AFC" else todas_rtf
    
    for m in lista_alvo:
        st_val = status_dict.get(f"{setor_atual} {m}", "PRODUZINDO")
        if "PRODUZINDO" not in st_val:
            maquinas_com_problema.append((setor_atual, m, st_val))
            
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo']:
        painel_controle_maquina(st.session_state['maq_ativa'], st.session_state['setor_ativo'])
        st.divider()

    if not maquinas_com_problema:
        st.success("🟢 Nenhuma anomalia no seu setor neste momento!")
    else:
        st.write("Clique na máquina para atualizar o status:")
        for setor_m, maq_m, st_m in maquinas_com_problema:
            icone = MAPA_STATUS.get(st_m.split(" - ")[0], "⚠️")
            if st.button(f"{icone} {setor_m} {maq_m} - {st_m}", key=f"chk_{setor_m}_{maq_m}", use_container_width=True):
                st.session_state['maq_ativa'] = maq_m
                st.session_state['setor_ativo'] = setor_m
                st.rerun()

def tela_afc():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### 🗂️ Afiação - Células")
    status_dict = ler_status_atual()
    
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'AFC':
        painel_controle_maquina(st.session_state['maq_ativa'], 'AFC')
    
    if st.session_state['celula_selecionada'] is None:
        if st.button("📌 Célula 1 (Esquerda)", use_container_width=True):
            st.session_state['celula_selecionada'] = 'celula_1'
            st.rerun()
        if st.button("📌 Célula 2 (Direita)", use_container_width=True):
            st.session_state['celula_selecionada'] = 'celula_2'
            st.rerun()
    else:
        if st.button("⬅️ Voltar Células"):
            st.session_state['celula_selecionada'] = None
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        if st.session_state['celula_selecionada'] == 'celula_1':
            render_grid_vertical([
                "30-161", "29-078", "32-081", "31-969",
                "34-132", "33-160", "36-084", "35-131",
                "38-596", "37-892", "40-142", "39-905", "41-141"
            ], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'celula_2':
            render_grid_vertical([
                "8-247", "6-868", "4-427", "9-088",
                "10-812", "7-743", "12-367", "11-365",
                "14-967", "13-964", "16-975", "15-973",
                "18-957", "17-140", "20-774", "19-760",
                "22-813", "21-206", "24-761", "23-165",
                "26-635", "25-209", "28-432", "27-431"
            ], "AFC", status_dict)

def tela_rtf():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### 🗂️ Retífica - Células")
    status_dict = ler_status_atual()
    
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'RTF':
        painel_controle_maquina(st.session_state['maq_ativa'], 'RTF')
    
    if st.session_state['celula_selecionada'] is None:
        if st.button("⚫ Centerless", use_container_width=True):
            st.session_state['celula_selecionada'] = 'cent'
            st.rerun()
        if st.button("🟣 Retíficas Padrão", use_container_width=True):
            st.session_state['celula_selecionada'] = 'rtf_padrao'
            st.rerun()
    else:
        if st.button("⬅️ Voltar Células"):
            st.session_state['celula_selecionada'] = None
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        if st.session_state['celula_selecionada'] == 'cent':
            render_grid_vertical(["6-6J1", "17-6J1"], "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'rtf_padrao':
            render_grid_vertical([
                "30-786", "32-918", "29-785", "4-425", "3-426",
                "34-842", "31-806", "7-267", "5-903", "36-854",
                "33-807", "9-815", "8-086", "38-881", "35-885",
                "11-363", "10-817", "40-912", "37-857", "13-969",
                "12-962", "42-885", "39-856", "15-977", "14-971",
                "18-925", "16-183", "20-927", "19-926", "22-916",
                "21-270", "24-259", "23-753", "26-260", "25-258",
                "28-954", "27-917"
            ], "RTF", status_dict)

def tela_equipe():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### Equipe")
    with st.form("form_equipe", clear_on_submit=True):
        tipo = st.radio("Tipo:", ["Ausência / Falta", "Treinamento"])
        nome = st.text_input("Nome:")
        if st.form_submit_button("REGISTRAR", use_container_width=True):
            if nome:
                salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                st.success("✅")

def tela_editar():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### Corrigir Dados")
    if os.path.exists(ARQUIVO_DADOS):
        df_maq = pd.read_csv(ARQUIVO_DADOS)
        df_editado = st.data_editor(df_maq, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Salvar", use_container_width=True):
            df_editado.to_csv(ARQUIVO_DADOS, index=False)
            st.success("Salvo!")

def tela_relatorio():
    if st.button("⬅️ Menu"): mudar_tela('menu')
    st.markdown("##### Fechamento de Turno")
    concluidos = st.text_area("Concluídos:", height=50)
    obs = st.text_area("Obs:", height=50)
    
    col1, col2 = st.columns(2)
    gerar = col1.button("👁️ Ver", use_container_width=True)
    encerrar = col2.button("🛑 ENCERRAR", type="primary", use_container_width=True)
        
    if gerar or encerrar:
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        df_maq = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
        if not df_maq.empty: df_maq = df_maq.drop_duplicates(subset=['Maquina'], keep='last')
        
        texto = f"🏭 PLANTA | {data_hoje} | {st.session_state['turno']}\n\n"
        for _, row in df_maq.iterrows():
            texto += f"- {row['Maquina']}: {row['Status']} ({row['Hora']})\n"
        
        st.code(texto, language="text")
        if encerrar:
            if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            st.success("Turno encerrado!")

# --- ROTEADOR ---
if st.session_state['tela_atual'] == 'login': tela_login()
elif st.session_state['tela_atual'] == 'menu': tela_menu()
elif st.session_state['tela_atual'] == 'checkup': tela_checkup()
elif st.session_state['tela_atual'] == 'afc': tela_afc()
elif st.session_state['tela_atual'] == 'rtf': tela_rtf()
elif st.session_state['tela_atual'] == 'equipe': tela_equipe()
elif st.session_state['tela_atual'] == 'editar': tela_editar()
elif st.session_state['tela_atual'] == 'relatorio': tela_relatorio()