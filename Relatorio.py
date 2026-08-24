import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# --- CONFIGURAÇÃO BASE DO APP ---
st.set_page_config(page_title="App MES", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

# --- CSS PREMIUM (Visual de Aplicativo Mobile) ---
CSS_APP = """
<style>
    .stApp { background-color: #121214 !important; }
    h1, h2, h3, p, span, div[data-testid="stMarkdownContainer"] { color: #F8FAFC !important; font-family: 'Inter', sans-serif !important; }
    label { color: #A1A1AA !important; font-size: 13px !important; font-weight: 600 !important; }
    
    /* Botões do Menu */
    .btn-menu > button { background-color: #202024 !important; color: #14B8A6 !important; border: 1px solid #323238 !important; border-radius: 12px !important; height: 90px !important; font-size: 16px !important; font-weight: bold !important; transition: 0.2s; margin-bottom: 10px; }
    .btn-menu > button:hover { border-color: #14B8A6 !important; background-color: #1A1A1E !important; }
    
    /* Botão Voltar */
    .btn-voltar > button { background-color: transparent !important; color: #A1A1AA !important; border: 1px solid #323238 !important; border-radius: 8px !important; margin-bottom: 20px; }
    
    /* Botões de Ação Principal */
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { background-color: #0D9488 !important; color: white !important; border: none !important; border-radius: 8px !important; height: 50px !important; font-weight: bold !important; }
    div[data-testid="stFormSubmitButton"] > button:hover, button[kind="primary"]:hover { background-color: #0F766E !important; }
    
    /* Botão Perigo */
    .btn-danger > button { background-color: #991B1B !important; color: white !important; }
    .btn-danger > button:hover { background-color: #7F1D1D !important; }
    
    /* Inputs */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { background-color: #202024 !important; border: 1px solid #323238 !important; border-radius: 8px !important; }
    input, select, textarea { color: white !important; }
    header { visibility: hidden; }
</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"

# --- GERENCIAMENTO DE ESTADO (NAVEGAÇÃO) ---
if 'tela_atual' not in st.session_state:
    st.session_state['tela_atual'] = 'login'
if 'operador' not in st.session_state:
    st.session_state['operador'] = ''

def mudar_tela(nome_tela):
    st.session_state['tela_atual'] = nome_tela
    st.rerun()

# --- FUNÇÃO DE SALVAMENTO INTELIGENTE ---
def salvar_csv(dados, arquivo):
    df_novo = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df_existente = pd.read_csv(arquivo)
        chave = 'Maquina' if 'Maquina' in dados else 'Nome'
        if chave in df_existente.columns and dados[chave] in df_existente[chave].values:
            idx = df_existente.index[df_existente[chave] == dados[chave]].tolist()[0]
            for key, value in dados.items():
                df_existente.at[idx, key] = value
            df_existente.to_csv(arquivo, index=False)
        else:
            df_novo.to_csv(arquivo, mode='a', header=False, index=False)
    else:
        df_novo.to_csv(arquivo, index=False)


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
    st.markdown("<p style='color: #A1A1AA;'>Selecione o módulo desejado:</p>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("⚙️ AFIAÇÃO", use_container_width=True): mudar_tela('afc')
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("👥 EQUIPE", use_container_width=True): mudar_tela('equipe')
        st.markdown('</div>', unsafe_allow_html=True)
        
    with col2:
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("⚙️ RETÍFICA", use_container_width=True): mudar_tela('rtf')
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("✏️ EDITAR DADOS", use_container_width=True): mudar_tela('editar')
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
    if st.button("📋 GERAR RELATÓRIO FINAL", use_container_width=True): mudar_tela('relatorio')
    st.markdown('</div>', unsafe_allow_html=True)
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 Sair (Logout)", use_container_width=True):
        st.session_state['operador'] = ''
        mudar_tela('login')

def tela_afc():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### Apontamento - Afiação")
    with st.form("form_afc"):
        num_maq = st.text_input("NÚMERO DA MÁQUINA (Ex: 33)")
        status = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO", "SEQUÊNCIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
        troca_rebolo = st.toggle("🔄 Troca de Rebolo?")
        hora = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:30")
        
        if st.form_submit_button("SALVAR DADOS", use_container_width=True):
            if num_maq and hora:
                status_final = f"{status} (C/ Troca Rebolo)" if troca_rebolo else status
                salvar_csv({"Setor": "AFC", "Maquina": f"AFC {num_maq.strip().upper()}", "Operador": st.session_state['operador'], "Status": status_final, "Hora": hora}, ARQUIVO_DADOS)
                st.success("✅ Salvo com sucesso!")
                time.sleep(1)
                mudar_tela('menu')
            else:
                st.error("⚠️ Preencha a Máquina e a Hora!")

def tela_rtf():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### Apontamento - Retífica")
    num_maq_rtf = st.text_input("NÚMERO DA MÁQUINA (Ex: 10)")
    status_rtf = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
    troca_rebolo_rtf = st.toggle("🔄 Troca de Rebolo?")
    hora_rtf = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:50")

    tipo_prep = None
    troca_diametro = False
    if status_rtf == "PREPARAÇÃO":
        tipo_prep = st.radio("Tipo:", ["HASTE", "GUIA"], horizontal=True)
        if tipo_prep == "HASTE":
            troca_diametro = st.toggle("📐 Troca de Diâmetro?")
            
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("SALVAR DADOS", type="primary", use_container_width=True):
        if num_maq_rtf and hora_rtf:
            status_final = status_rtf
            if status_rtf == "PREPARAÇÃO":
                status_final += f" - {tipo_prep}"
                if tipo_prep == "HASTE" and troca_diametro: status_final += " (C/ Troca Diâmetro)"
            if troca_rebolo_rtf: status_final += " (C/ Troca Rebolo)"
            
            salvar_csv({"Setor": "RTF", "Maquina": f"RTF {num_maq_rtf.strip().upper()}", "Operador": st.session_state['operador'], "Status": status_final, "Hora": hora_rtf}, ARQUIVO_DADOS)
            st.success("✅ Salvo com sucesso!")
            time.sleep(1)
            mudar_tela('menu')
        else:
            st.error("⚠️ Preencha a Máquina e a Hora!")

def tela_equipe():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
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
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### ✏️ Corrigir Dados")
    st.caption("Edite diretamente na tabela abaixo. Selecione a linha e aperte 'Delete' para apagar.")
    
    st.markdown("#### Operações")
    if os.path.exists(ARQUIVO_DADOS):
        try:
            df_maq = pd.read_csv(ARQUIVO_DADOS)
            df_maq_editado = st.data_editor(df_maq, num_rows="dynamic", use_container_width=True)
            if st.button("💾 Salvar Edição - Operações", use_container_width=True):
                df_maq_editado.to_csv(ARQUIVO_DADOS, index=False)
                st.success("Atualizado!")
        except:
            st.error("Erro na leitura de operações.")
    else:
        st.info("Nenhuma operação registrada.")
        
    st.divider()
    
    st.markdown("#### Equipe")
    if os.path.exists(ARQUIVO_EQUIPE):
        try:
            df_eq = pd.read_csv(ARQUIVO_EQUIPE)
            df_eq_editado = st.data_editor(df_eq, num_rows="dynamic", use_container_width=True)
            if st.button("💾 Salvar Edição - Equipe", use_container_width=True):
                df_eq_editado.to_csv(ARQUIVO_EQUIPE, index=False)
                st.success("Atualizado!")
        except:
            st.error("Erro na leitura da equipe.")
    else:
        st.info("Nenhum registro de equipe.")

def tela_relatorio():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### 📋 Fechamento de Turno")
    
    turno = st.selectbox("Selecione o Turno:", ["1° TURNO", "2° TURNO", "3° TURNO"])
    concluidos = st.text_area("✔️ Ajustes e Setups Concluídos:", height=100)
    obs = st.text_area("📝 Observações e Desenvolvimento:", height=100)
    
    col1, col2 = st.columns(2)
    with col1:
        gerar = st.button("👁️ Visualizar Relatório", use_container_width=True)
    with col2:
        st.markdown('<div class="btn-danger">', unsafe_allow_html=True)
        encerrar = st.button("🛑 ENCERRAR TURNO", type="primary", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
    if gerar or encerrar:
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        df_maq = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
        df_eq = pd.read_csv(ARQUIVO_EQUIPE) if os.path.exists(ARQUIVO_EQUIPE) else pd.DataFrame(columns=["Tipo", "Nome"])
        if 'Operador' not in df_maq.columns: df_maq['Operador'] = ""
        
        manutencao = df_maq[df_maq['Status'].str.contains('MANUTENÇÃO', na=False)]['Maquina'].dropna().astype(str).tolist()
        setups = df_maq[df_maq['Status'].str.contains('PREPARAÇÃO|SEQUÊNCIA', na=False)]
        producao_rtf = df_maq[(df_maq['Setor'] == 'RTF') & (df_maq['Status'].str.contains('PRODUZINDO', na=False))]
        paradas = df_maq[df_maq['Status'].str.contains('PARADA', na=False)]['Maquina'].dropna().astype(str).tolist()
        
        treinamento = df_eq[df_eq['Tipo'] == 'Operador em Treinamento']['Nome'].dropna().astype(str).tolist()
        ausencias = df_eq[df_eq['Tipo'] == 'Ausência / Falta']['Nome'].dropna().astype(str).tolist()
        
        texto = f"🏭 PLANTA AFIAÇÃO E RETÍFICA | {data_hoje} | {turno}\n"
        texto += "SITUAÇÃO DO SETOR ⬇️⬇️⬇️\n\n"
        
        texto += "🛠️ MÁQUINAS EM MANUTENÇÃO (PARADA):\n"
        texto += "\n".join(f" - {maq}" for maq in manutencao) if manutencao else "N/A"
        texto += "\n\n"
        
        texto += "🛑 PARADAS DURANTE O TURNO:\n"
        texto += "\n".join(f" - {maq}" for maq in paradas) if paradas else "N/A"
        texto += "\n\n"
        
        texto += "⚙️ MÁQUINAS EM SETUP / AJUSTE:\n"
        if setups.empty: texto += "N/A\n"
        else:
            for _, row in setups.iterrows():
                op_nome = f" ({row['Operador']})" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto += f"🔴 {row['Maquina']} - {row['Status']} - {row['Hora']}{op_nome}\n"
        texto += "\n"
        
        texto += "✅ EM PRODUÇÃO (RETÍFICAS):\n"
        if producao_rtf.empty: texto += "N/A\n"
        else:
            for _, row in producao_rtf.iterrows():
                op_nome = f" ({row['Operador']})" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto += f"🟢 {row['Maquina']} - PRODUZINDO{op_nome}\n"
        texto += "\n"
        
        texto += "✔️ SETUPS E ATIVIDADES CONCLUÍDAS:\n"
        texto += concluidos.strip() if concluidos.strip() else "N/A"
        texto += "\n\n"
        
        texto += "📝 DESENVOLVIMENTO / OBSERVAÇÕES:\n"
        texto += obs.strip() if obs.strip() else "N/A"
        texto += "\n\n"
        
        texto += "👥 GESTÃO DE EQUIPE:\n"
        texto += f"Ausências: {', '.join(ausencias) if ausencias else 'Nenhuma'}\n"
        texto += f"Treinamento: {', '.join(treinamento) if treinamento else 'Nenhum'}\n\n"
        texto += "RESTANTE OK !"
        
        st.code(texto, language="text")
        
        if encerrar:
            if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            st.success("✨ Turno Encerrado! Banco limpo.")

# --- ROTEADOR (ROUTER) ---
if st.session_state['tela_atual'] == 'login':
    tela_login()
elif st.session_state['tela_atual'] == 'menu':
    tela_menu()
elif st.session_state['tela_atual'] == 'afc':
    tela_afc()
elif st.session_state['tela_atual'] == 'rtf':
    tela_rtf()
elif st.session_state['tela_atual'] == 'equipe':
    tela_equipe()
elif st.session_state['tela_atual'] == 'editar':
    tela_editar()
elif st.session_state['tela_atual'] == 'relatorio':
    tela_relatorio()