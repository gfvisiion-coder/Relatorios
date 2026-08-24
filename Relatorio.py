import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# --- CONFIGURAÇÃO BASE DO APP ---
st.set_page_config(page_title="App MES - Planta", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

# --- CSS PREMIUM ---
CSS_APP = """
<style>
    .stApp { background-color: #121214 !important; }
    h1, h2, h3, h4, h5, p, span, div[data-testid="stMarkdownContainer"] { color: #F8FAFC !important; font-family: 'Inter', sans-serif !important; }
    label { color: #A1A1AA !important; font-size: 13px !important; font-weight: 600 !important; }
    
    /* Botões do Menu e Grid */
    button[kind="secondary"] { background-color: #202024 !important; color: #E4E4E7 !important; border: 1px solid #323238 !important; border-radius: 8px !important; transition: 0.2s; font-weight: bold !important; height: 60px !important;}
    button[kind="secondary"]:hover { border-color: #14B8A6 !important; background-color: #27272A !important; }
    
    /* Botões de Ação Principal */
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { background-color: #0D9488 !important; color: white !important; border: none !important; border-radius: 8px !important; height: 50px !important; font-weight: bold !important; }
    div[data-testid="stFormSubmitButton"] > button:hover, button[kind="primary"]:hover { background-color: #0F766E !important; }
    
    /* Inputs */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { background-color: #202024 !important; border: 1px solid #323238 !important; border-radius: 8px !important; }
    input, select, textarea { color: white !important; }
    header { visibility: hidden; }
</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"

# --- DICIONÁRIO DE STATUS VISUAL ---
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

def mudar_tela(nome_tela):
    st.session_state['tela_atual'] = nome_tela
    st.rerun()

# --- FUNÇÕES DE DADOS ---
def ler_status_atual():
    """Lê o CSV e retorna um dicionário com o último status de cada máquina."""
    if not os.path.exists(ARQUIVO_DADOS):
        return {}
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        # Pega o status base (remove as observações entre parênteses para o mapeamento visual)
        df['Status_Base'] = df['Status'].apply(lambda x: str(x).split(" (")[0].split(" - ")[0])
        # Mantém apenas o último registro de cada máquina
        df_ultimo = df.drop_duplicates(subset=['Maquina'], keep='last')
        return dict(zip(df_ultimo['Maquina'], df_ultimo['Status_Base']))
    except:
        return {}

def obter_info_maquina(maq_id, setor):
    """Busca todas as informações do último apontamento de uma máquina específica."""
    if not os.path.exists(ARQUIVO_DADOS):
        return None
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        if not df_maq.empty:
            return df_maq.iloc[-1].to_dict() # Retorna a última linha como dicionário
    except:
        pass
    return None

def salvar_csv(dados, arquivo):
    df_novo = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df_existente = pd.read_csv(arquivo)
        # Ao invés de sobrescrever, adicionamos ao histórico para gerar o relatório depois
        df_existente = pd.concat([df_existente, df_novo], ignore_index=True)
        df_existente.to_csv(arquivo, index=False)
    else:
        df_novo.to_csv(arquivo, index=False)

# ==========================================
#        MODAL DE APONTAMENTO (POP-UP)
# ==========================================
@st.dialog("⚙️ Detalhes e Apontamento")
def modal_apontamento(maq_id, setor):
    st.markdown(f"### Máquina: {maq_id}")
    
    # 1. BUSCA E EXIBE O STATUS ATUAL
    info = obter_info_maquina(maq_id, setor)
    
    if info:
        status_atual = info.get('Status', 'Desconhecido')
        hora_atual = info.get('Hora', '--:--')
        operador_atual = info.get('Operador', 'Não informado')
        
        if "PREPARAÇÃO" in status_atual or "SEQUÊNCIA" in status_atual:
            st.info(f"🟡 **Status Atual:** Em preparação desde as **{hora_atual}**.\n\n👤 **Operador:** {operador_atual}")
        elif "PRODUZINDO" in status_atual:
            st.success(f"🟢 **Status Atual:** Produzindo desde as **{hora_atual}**.\n\n👤 **Operador:** {operador_atual}")
        elif "PARADA" in status_atual:
            st.error(f"🔴 **Status Atual:** Máquina Parada desde as **{hora_atual}**.\n\n👤 **Operador:** {operador_atual}")
        elif "MANUTENÇÃO" in status_atual:
            st.warning(f"🛠️ **Status Atual:** Em manutenção desde as **{hora_atual}**.\n\n👤 **Informante:** {operador_atual}")
        else:
            st.write(f"**Status Atual:** {status_atual} às {hora_atual}")
    else:
        st.write("⚪ **Status Atual:** Nenhum apontamento registrado neste turno.")
        
    st.divider()
    
    # 2. FORMULÁRIO PARA ALTERAR O STATUS
    st.markdown("#### Deseja alterar o status?")
    
    with st.form(f"form_{maq_id}"):
        status = st.selectbox("Novo Status:", ["PRODUZINDO", "PREPARAÇÃO", "SEQUÊNCIA", "MANUTENÇÃO", "PARADA"])
        
        tipo_prep = None
        troca_diametro = False
        if setor == "RTF" and status == "PREPARAÇÃO":
            tipo_prep = st.radio("Tipo:", ["HASTE", "GUIA"], horizontal=True)
            if tipo_prep == "HASTE":
                troca_diametro = st.toggle("📐 Troca de Diâmetro?")
                
        troca_rebolo = st.toggle("🔄 Troca de Rebolo?")
        hora = st.text_input("Hora do Evento (Ex: 06:30):")
        
        if st.form_submit_button("💾 Salvar Novo Status", use_container_width=True, type="primary"):
            if hora:
                status_final = status
                if setor == "RTF" and status == "PREPARAÇÃO":
                    status_final += f" - {tipo_prep}"
                    if tipo_prep == "HASTE" and troca_diametro: status_final += " (C/ Troca Diâmetro)"
                
                if troca_rebolo: status_final += " (C/ Troca Rebolo)"
                
                salvar_csv({
                    "Setor": setor, 
                    "Maquina": f"{setor} {maq_id}", 
                    "Operador": st.session_state['operador'], 
                    "Status": status_final, 
                    "Hora": hora
                }, ARQUIVO_DADOS)
                
                st.success("Atualizado!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Preencha a Hora do novo evento!")

# ==========================================
#               TELAS DO APP
# ==========================================

def tela_login():
    st.markdown("<h1 style='text-align: center; color: #14B8A6 !important; margin-top: 50px;'>🏭 App MES</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #A1A1AA;'>Faça login para iniciar o turno</p>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    nome = st.text_input("Seu Nome ou RE:", placeholder="Digite aqui...")
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("ENTRAR NO SISTEMA", use_container_width=True, type="primary"):
        if nome:
            st.session_state['operador'] = nome.upper()
            mudar_tela('menu')
        else:
            st.error("⚠️ Identificação obrigatória.")

def tela_menu():
    st.markdown(f"<h3 style='color: #F8FAFC !important;'>Olá, {st.session_state['operador']} 👋</h3>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⚙️ MAPA AFIAÇÃO", use_container_width=True): mudar_tela('afc')
        if st.button("👥 GESTÃO DE EQUIPE", use_container_width=True): mudar_tela('equipe')
    with col2:
        if st.button("⚙️ MAPA RETÍFICA", use_container_width=True): mudar_tela('rtf')
        if st.button("✏️ CORRIGIR DADOS", use_container_width=True): mudar_tela('editar')

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📋 GERAR RELATÓRIO DE TURNO", use_container_width=True, type="primary"): mudar_tela('relatorio')
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🚪 Sair (Logout)", use_container_width=True):
        st.session_state['operador'] = ''
        mudar_tela('login')

def render_grid_matricial(matriz, setor, status_dict):
    """Renderiza a grade de botões respeitando os espaços vazios do layout físico."""
    for linha in matriz:
        cols = st.columns(len(linha))
        for i, maq in enumerate(linha):
            if maq == "":
                cols[i].write("") 
            else:
                chave_busca = f"{setor} {maq}"
                status_atual = status_dict.get(chave_busca, "")
                icone = MAPA_STATUS.get(status_atual, "⚪")
                
                label_botao = f"{icone} {maq}"
                if cols[i].button(label_botao, key=f"btn_{setor}_{maq}", use_container_width=True):
                    modal_apontamento(maq, setor)

def tela_afc():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("### 🗺️ Mapa da Afiação")
    st.caption("🟢 Produzindo | 🟡 Setup | 🔴 Parada | 🛠️ Manutenção | ⚪ Sem apontamento")
    st.divider()
    
    status_dict = ler_status_atual()
    
    col_esq, col_dir = st.columns(2)
    
    with col_esq:
        st.markdown("<h5 style='text-align: center; color: #14B8A6;'>Bloco Esquerdo</h5>", unsafe_allow_html=True)
        layout_esq = [
            ["30-161", "29-078"],
            ["32-081", "31-969"],
            ["34-132", "33-160"],
            ["36-084", "35-131"],
            ["38-596", "37-892"],
            ["40-142", "39-905"],
            ["", "41-141"]
        ]
        render_grid_matricial(layout_esq, "AFC", status_dict)

    with col_dir:
        st.markdown("<h5 style='text-align: center; color: #14B8A6;'>Bloco Direito</h5>", unsafe_allow_html=True)
        layout_dir = [
            ["8-247", "6-868"],
            ["4-427", "9-088"],
            ["10-812", "7-743"],
            ["12-367", "11-365"],
            ["14-967", "13-964"],
            ["16-975", "15-973"],
            ["18-957", "17-140"],
            ["20-774", "19-760"],
            ["22-813", "21-206"],
            ["24-761", "23-165"],
            ["26-635", "25-209"],
            ["28-432", "27-431"]
        ]
        render_grid_matricial(layout_dir, "AFC", status_dict)

def tela_rtf():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("### 🗺️ Mapa da Retífica")
    st.caption("🟢 Produzindo | 🟡 Setup | 🔴 Parada | 🛠️ Manutenção | ⚪ Sem apontamento")
    st.divider()
    
    status_dict = ler_status_atual()
    
    st.markdown("#### Centerless")
    layout_centerless = [
        ["6-6J1", "17-6J1"]
    ]
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        render_grid_matricial(layout_centerless, "RTF", status_dict)
    
    st.divider()
    
    st.markdown("#### Retíficas Padrão")
    layout_rtf = [
        ["30-786", "", "", ""], 
        ["32-918", "29-785", "4-425", "3-426"],
        ["34-842", "31-806", "7-267", "5-903"],
        ["36-854", "33-807", "9-815", "8-086"],
        ["38-881", "35-885", "11-363", "10-817"],
        ["40-912", "37-857", "13-969", "12-962"],
        ["42-885", "39-856", "15-977", "14-971"],
        ["", "", "18-925", "16-183"], 
        ["", "", "20-927", "19-926"],
        ["", "", "22-916", "21-270"],
        ["", "", "24-259", "23-753"],
        ["", "", "26-260", "25-258"],
        ["", "", "28-954", "27-917"]
    ]
    render_grid_matricial(layout_rtf, "RTF", status_dict)

def tela_equipe():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("### Gestão de Equipe")
    with st.form("form_equipe", clear_on_submit=True):
        tipo = st.radio("Tipo de Registro:", ["Ausência / Falta", "Operador em Treinamento"])
        nome = st.text_input("Nome do Colaborador:")
        if st.form_submit_button("REGISTRAR", use_container_width=True):
            if nome:
                salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                st.success("✅ Registrado!")
            else:
                st.error("⚠️ Digite o nome.")

def tela_editar():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("### ✏️ Corrigir Dados")
    st.caption("Edite diretamente na tabela. Pressione 'Delete' para apagar uma linha.")
    
    if os.path.exists(ARQUIVO_DADOS):
        df_maq = pd.read_csv(ARQUIVO_DADOS)
        df_editado = st.data_editor(df_maq, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Salvar Histórico", use_container_width=True):
            df_editado.to_csv(ARQUIVO_DADOS, index=False)
            st.success("Salvo!")
    else:
        st.info("Nenhuma operação registrada.")

def tela_relatorio():
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown("### 📋 Fechamento de Turno")
    
    turno = st.selectbox("Selecione o Turno:", ["1° TURNO", "2° TURNO", "3° TURNO"])
    concluidos = st.text_area("✔️ Ajustes e Setups Concluídos:")
    obs = st.text_area("📝 Observações:")
    
    col1, col2 = st.columns(2)
    with col1:
        gerar = st.button("👁️ Visualizar", use_container_width=True)
    with col2:
        encerrar = st.button("🛑 ENCERRAR TURNO", type="primary", use_container_width=True)
        
    if gerar or encerrar:
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        # Pega apenas o ÚLTIMO status de cada máquina para o relatório
        df_maq = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
        if not df_maq.empty:
            df_maq = df_maq.drop_duplicates(subset=['Maquina'], keep='last')
            
        df_eq = pd.read_csv(ARQUIVO_EQUIPE) if os.path.exists(ARQUIVO_EQUIPE) else pd.DataFrame(columns=["Tipo", "Nome"])
        if 'Operador' not in df_maq.columns: df_maq['Operador'] = ""
        
        manutencao = df_maq[df_maq['Status'].str.contains('MANUTENÇÃO', na=False)]['Maquina'].tolist()
        setups = df_maq[df_maq['Status'].str.contains('PREPARAÇÃO|SEQUÊNCIA', na=False)]
        producao = df_maq[df_maq['Status'].str.contains('PRODUZINDO', na=False)]
        paradas = df_maq[df_maq['Status'].str.contains('PARADA', na=False)]['Maquina'].tolist()
        
        treinamento = df_eq[df_eq['Tipo'] == 'Operador em Treinamento']['Nome'].tolist()
        ausencias = df_eq[df_eq['Tipo'] == 'Ausência / Falta']['Nome'].tolist()
        
        texto = f"🏭 PLANTA AFIAÇÃO E RETÍFICA | {data_hoje} | {turno}\n"
        texto += "SITUAÇÃO DO SETOR ⬇️⬇️⬇️\n\n"
        
        texto += "🛠️ MÁQUINAS EM MANUTENÇÃO (PARADA):\n"
        texto += "\n".join(f" - {maq}" for maq in manutencao) if manutencao else "N/A"
        texto += "\n\n🛑 PARADAS DURANTE O TURNO:\n"
        texto += "\n".join(f" - {maq}" for maq in paradas) if paradas else "N/A"
        texto += "\n\n⚙️ MÁQUINAS EM SETUP / AJUSTE:\n"
        
        if setups.empty: texto += "N/A\n"
        else:
            for _, row in setups.iterrows():
                op = f" ({row['Operador']})" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto += f"🔴 {row['Maquina']} - {row['Status']} - {row['Hora']}{op}\n"
                
        texto += "\n✅ EM PRODUÇÃO:\n"
        if producao.empty: texto += "N/A\n"
        else:
            for _, row in producao.iterrows():
                op = f" ({row['Operador']})" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto += f"🟢 {row['Maquina']} - PRODUZINDO{op}\n"
                
        texto += "\n✔️ SETUPS E ATIVIDADES CONCLUÍDAS:\n"
        texto += concluidos.strip() if concluidos.strip() else "N/A"
        texto += "\n\n📝 DESENVOLVIMENTO / OBSERVAÇÕES:\n"
        texto += obs.strip() if obs.strip() else "N/A"
        texto += "\n\n👥 GESTÃO DE EQUIPE:\n"
        texto += f"Ausências: {', '.join(ausencias) if ausencias else 'Nenhuma'}\n"
        texto += f"Treinamento: {', '.join(treinamento) if treinamento else 'Nenhum'}\n\nRESTANTE OK !"
        
        st.code(texto, language="text")
        
        if encerrar:
            if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            st.success("✨ Turno Encerrado! Banco limpo para o próximo turno.")

# --- ROTEADOR ---
if st.session_state['tela_atual'] == 'login': tela_login()
elif st.session_state['tela_atual'] == 'menu': tela_menu()
elif st.session_state['tela_atual'] == 'afc': tela_afc()
elif st.session_state['tela_atual'] == 'rtf': tela_rtf()
elif st.session_state['tela_atual'] == 'equipe': tela_equipe()
elif st.session_state['tela_atual'] == 'editar': tela_editar()
elif st.session_state['tela_atual'] == 'relatorio': tela_relatorio()