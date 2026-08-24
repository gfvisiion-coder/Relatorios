import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

st.set_page_config(page_title="App MES", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

# CSS para visual de APP Mobile
CSS_APP = """
<style>
    .stApp { background-color: #121214 !important; }
    h1, h2, h3, p, span { color: #F8FAFC !important; font-family: 'Inter', sans-serif !important; }
    .btn-menu > button { background-color: #202024 !important; color: #14B8A6 !important; border: 1px solid #323238 !important; border-radius: 12px !important; height: 100px !important; font-size: 18px !important; font-weight: bold !important; transition: 0.2s; }
    .btn-menu > button:hover { border-color: #14B8A6 !important; background-color: #1A1A1E !important; }
    .btn-voltar > button { background-color: transparent !important; color: #A1A1AA !important; border: 1px solid #323238 !important; margin-bottom: 20px; }
    div[data-testid="stFormSubmitButton"] > button { background-color: #0D9488 !important; color: white !important; border-radius: 8px !important; height: 50px !important; font-weight: bold !important; }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { background-color: #202024 !important; border: 1px solid #323238 !important; border-radius: 8px !important; }
    input, select { color: white !important; }
    header { visibility: hidden; }
</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"

# --- GERENCIAMENTO DE ESTADO DAS TELAS ---
if 'tela_atual' not in st.session_state:
    st.session_state['tela_atual'] = 'login'
if 'operador' not in st.session_state:
    st.session_state['operador'] = ''

def mudar_tela(nome_tela):
    st.session_state['tela_atual'] = nome_tela
    st.rerun()

def salvar_csv(dados):
    df_novo = pd.DataFrame([dados])
    if os.path.exists(ARQUIVO_DADOS):
        df_existente = pd.read_csv(ARQUIVO_DADOS)
        if 'Maquina' in df_existente.columns and dados['Maquina'] in df_existente['Maquina'].values:
            idx = df_existente.index[df_existente['Maquina'] == dados['Maquina']].tolist()[0]
            for key, value in dados.items():
                df_existente.at[idx, key] = value
            df_existente.to_csv(ARQUIVO_DADOS, index=False)
        else:
            df_novo.to_csv(ARQUIVO_DADOS, mode='a', header=False, index=False)
    else:
        df_novo.to_csv(ARQUIVO_DADOS, index=False)

# --- TELAS DO APP ---

def tela_login():
    st.markdown("<h1 style='text-align: center; color: #14B8A6 !important; margin-bottom: 50px;'>🛠️ App MES</h1>", unsafe_allow_html=True)
    with st.container():
        nome = st.text_input("Digite seu Nome ou RE:", placeholder="Seu nome aqui...")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("ENTRAR NO SISTEMA", use_container_width=True, type="primary"):
            if nome:
                st.session_state['operador'] = nome.upper()
                mudar_tela('menu')
            else:
                st.error("Por favor, identifique-se.")

def tela_menu():
    st.markdown(f"<h3 style='color: #A1A1AA !important;'>Olá, {st.session_state['operador']} 👋</h3>", unsafe_allow_html=True)
    st.markdown("<h2>Selecione o Módulo</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("⚙️ AFIAÇÃO", use_container_width=True): mudar_tela('afc')
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="btn-menu">', unsafe_allow_html=True)
        if st.button("⚙️ RETÍFICA", use_container_width=True): mudar_tela('rtf')
        st.markdown('</div>', unsafe_allow_html=True)
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sair da Conta (Logout)", use_container_width=True):
        st.session_state['operador'] = ''
        mudar_tela('login')

def tela_afc():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### Lançamento - Afiação")
    with st.form("form_afc"):
        num_maq = st.text_input("NÚMERO DA MÁQUINA (Ex: 33)")
        status = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO", "SEQUÊNCIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
        troca_rebolo = st.toggle("🔄 Troca de Rebolo?")
        hora = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:30")
        
        if st.form_submit_button("SALVAR", use_container_width=True):
            if num_maq and hora:
                status_final = f"{status} (C/ Troca Rebolo)" if troca_rebolo else status
                salvar_csv({"Setor": "AFC", "Maquina": f"AFC {num_maq.strip().upper()}", "Operador": st.session_state['operador'], "Status": status_final, "Hora": hora})
                st.success("Salvo com sucesso!")
                time.sleep(1)
                mudar_tela('menu')
            else:
                st.error("Preencha a Máquina e a Hora!")

def tela_rtf():
    st.markdown('<div class="btn-voltar">', unsafe_allow_html=True)
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("### Lançamento - Retífica")
    num_maq_rtf = st.text_input("NÚMERO DA MÁQUINA (Ex: 10)")
    status_rtf = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
    troca_rebolo_rtf = st.toggle("🔄 Troca de Rebolo?")
    hora_rtf = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:50")

    tipo_prep = None
    troca_diametro = False
    if status_rtf == "PREPARAÇÃO":
        tipo_prep = st.radio("Selecione o tipo:", ["HASTE", "GUIA"], horizontal=True)
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
            
            salvar_csv({"Setor": "RTF", "Maquina": f"RTF {num_maq_rtf.strip().upper()}", "Operador": st.session_state['operador'], "Status": status_final, "Hora": hora_rtf})
            st.success("Salvo com sucesso!")
            time.sleep(1)
            mudar_tela('menu')
        else:
            st.error("Preencha a Máquina e a Hora!")

# --- ROTEADOR (ROUTER) ---
if st.session_state['tela_atual'] == 'login':
    tela_login()
elif st.session_state['tela_atual'] == 'menu':
    tela_menu()
elif st.session_state['tela_atual'] == 'afc':
    tela_afc()
elif st.session_state['tela_atual'] == 'rtf':
    tela_rtf()