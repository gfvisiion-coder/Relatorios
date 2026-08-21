import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# Configuração Base
st.set_page_config(page_title="Sistema MES", layout="centered", initial_sidebar_state="collapsed")

# CSS Premium 
CSS_MES_THEME = """
<style>
.stApp { background-color: #1E1F22 !important; }
h1, h2, h3, p, span, div[data-testid="stMarkdownContainer"] { color: #ffffff !important; font-family: 'Segoe UI', Tahoma, sans-serif !important; }
label { color: #D1D1D1 !important; font-size: 12px !important; font-weight: bold !important; text-transform: uppercase; }
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { background-color: #18191B !important; border: 1px solid #3A3A3A !important; border-radius: 6px !important; }
input, select, textarea { color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
div[data-baseweb="input"] > div:focus-within, div[data-baseweb="select"] > div:focus-within, div[data-baseweb="textarea"] > div:focus-within { border-color: #8B5CF6 !important; }
div[data-testid="stForm"] { background-color: #232428 !important; border: 1px solid #323338 !important; border-radius: 12px !important; padding: 30px !important; border-top: 4px solid #8B5CF6 !important; }
div[data-testid="stFormSubmitButton"] > button { background-color: #4C1D95 !important; color: white !important; font-weight: bold !important; border: none !important; border-radius: 6px !important; transition: 0.3s !important; height: 50px !important; }
div[data-testid="stFormSubmitButton"] > button:hover { background-color: #6D28D9 !important; }
button[data-baseweb="tab"] { background-color: #2B2D31 !important; color: #D1D1D1 !important; border-radius: 6px 6px 0 0 !important; border: 1px solid #3A3A3A !important; margin-right: 5px !important; }
button[data-baseweb="tab"][aria-selected="true"] { background-color: #4C1D95 !important; color: white !important; border-color: #4C1D95 !important; }
header {visibility: hidden;}
.loading-screen { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: #09090B; z-index: 999999; display: flex; flex-direction: column; justify-content: center; align-items: center; animation: fadeOut 0.5s forwards; animation-delay: 1.5s; pointer-events: none; }
.spinner { width: 120px; height: 120px; border-radius: 50%; border: 4px solid transparent; border-top-color: #8B5CF6; border-right-color: #6D28D9; animation: spin 1s linear infinite; position: relative; margin-bottom: 25px; }
.spinner::before { content: ""; position: absolute; top: 10px; left: 10px; right: 10px; bottom: 10px; border-radius: 50%; border: 3px solid transparent; border-top-color: #4C1D95; animation: spin 2s linear infinite reverse; }
.loading-text { color: #8B5CF6 !important; font-weight: bold; letter-spacing: 2px; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
@keyframes fadeOut { to { opacity: 0; visibility: hidden; } }
</style>
"""
st.markdown(CSS_MES_THEME, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"

if 'carregado' not in st.session_state:
    st.markdown("""<div class="loading-screen"><div class="spinner"></div><div class="loading-text">INICIANDO KERNEL...</div></div>""", unsafe_allow_html=True)
    time.sleep(1.5)
    st.session_state['carregado'] = True

def salvar_csv(dados, arquivo):
    df = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df.to_csv(arquivo, mode='a', header=False, index=False)
    else:
        df.to_csv(arquivo, index=False)

def main():
    st.markdown("<h2 style='text-align: center; font-weight: 900;'>SISTEMA MES</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #8B5CF6 !important; font-weight: bold; margin-top: -15px;'>CONTROLE DE PLANTA</p>", unsafe_allow_html=True)
    st.divider()
    
    aba_afc, aba_rtf, aba_equipe, aba_editar, aba_relatorio = st.tabs(["⚙️ AFC", "⚙️ RTF", "👥 EQUIPE", "✏️ EDITAR", "📋 RELATÓRIO"])
    
    # --- ABA AFC ---
    with aba_afc:
        with st.form("form_afc", clear_on_submit=True):
            maq = st.text_input("NOME DA MÁQUINA (Ex: AFC 33)")
            operador = st.text_input("NOME DO PREPARADOR / OPERADOR")
            status = st.selectbox("STATUS", ["PREPARAÇÃO", "SEQUÊNCIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
            hora = st.text_input("HORA DO EVENTO (Ex: 06:30)")
            
            if st.form_submit_button("Salvar Status AFC", use_container_width=True):
                if maq and hora and operador:
                    salvar_csv({"Setor": "AFC", "Maquina": maq.upper(), "Operador": operador.upper(), "Status": status, "Hora": hora}, ARQUIVO_DADOS)
                    st.success(f"{maq.upper()} registrada como {status} às {hora}!")
                else:
                    st.error("⚠️ Preencha a máquina, o operador e a hora!")

    # --- ABA RTF ---
    with aba_rtf:
        with st.form("form_rtf", clear_on_submit=True):
            maq = st.text_input("NOME DA MÁQUINA (Ex: RTF 10)")
            operador = st.text_input("NOME DO PREPARADOR / OPERADOR")
            status = st.selectbox("STATUS", ["PREPARAÇÃO", "SEQUÊNCIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
            hora = st.text_input("HORA DO EVENTO (Ex: 06:50)")
            
            if st.form_submit_button("Salvar Status RTF", use_container_width=True):
                if maq and hora and operador:
                    salvar_csv({"Setor": "RTF", "Maquina": maq.upper(), "Operador": operador.upper(), "Status": status, "Hora": hora}, ARQUIVO_DADOS)
                    st.success(f"{maq.upper()} registrada como {status} às {hora}!")
                else:
                    st.error("⚠️ Preencha a máquina, o operador e a hora!")

    # --- ABA EQUIPE ---
    with aba_equipe:
        with st.form("form_equipe", clear_on_submit=True):
            st.markdown("### 👥 Gestão de Pessoas (Líder)")
            tipo = st.radio("TIPO DE REGISTRO", ["Operador em Treinamento", "Ausência / Falta"])
            nome = st.text_input("NOME DO COLABORADOR")
            if st.form_submit_button("Registrar Colaborador", use_container_width=True):
                if nome:
                    salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                    st.success("Registrado com sucesso!")
                else:
                    st.error("⚠️ Por favor, digite o nome do colaborador!")

    # --- ABA EDITAR ---
    with aba_editar:
        st.markdown("### ✏️ Corrigir ou Excluir Dados")
        st.caption("Você pode alterar os textos diretamente nas tabelas abaixo. Para apagar uma linha, selecione a caixa à esquerda e aperte **Delete**. Não esqueça de clicar em 'Salvar'!")
        
        # Edição de Máquinas
        st.markdown("#### ⚙️ Registros de Operações")
        if os.path.exists(ARQUIVO_DADOS):
            try:
                df_maq = pd.read_csv(ARQUIVO_DADOS)
                if 'Operador' not in df_maq.columns:
                    df_maq['Operador'] = ""
                
                df_maq_editado = st.data_editor(df_maq, num_rows="dynamic", use_container_width=True, key="edit_maq")
                
                if st.button("💾 Salvar Alterações nas Operações"):
                    df_maq_editado.to_csv(ARQUIVO_DADOS, index=False)
                    st.success("Dados de operações corrigidos com sucesso!")
            except Exception as e:
                st.error("Erro ao ler os dados das máquinas.")
        else:
            st.info("Nenhuma máquina registrada ainda.")
            
        st.divider()
        
        # Edição de Equipe
        st.markdown("#### 👥 Registros da Equipe")
        if os.path.exists(ARQUIVO_EQUIPE):
            try:
                df_eq = pd.read_csv(ARQUIVO_EQUIPE)
                df_eq_editado = st.data_editor(df_eq, num_rows="dynamic", use_container_width=True, key="edit_eq")
                
                if st.button("💾 Salvar Alterações na Equipe"):
                    df_eq_editado.to_csv(ARQUIVO_EQUIPE, index=False)
                    st.success("Dados da equipe corrigidos com sucesso!")
            except Exception as e:
                st.error("Erro ao ler os dados da equipe.")
        else:
            st.info("Nenhum colaborador registrado ainda.")
            
        st.divider()
        
        with st.expander("⚠️ ZERAR TODOS OS DADOS (FIM DE TURNO)"):
            st.warning("Atenção: Isso irá apagar **todos** os registros atuais. Só clique aqui se quiser iniciar os relatórios de um novo turno.")
            if st.button("🗑️ APAGAR TUDO E REINICIAR", type="primary", use_container_width=True):
                if os.path.exists(ARQUIVO_DADOS):
                    os.remove(ARQUIVO_DADOS)
                if os.path.exists(ARQUIVO_EQUIPE):
                    os.remove(ARQUIVO_EQUIPE)
                st.success("✨ Todos os dados foram apagados! O sistema está pronto para um novo turno.")
                time.sleep(1)
                st.rerun()

    # --- ABA RELATÓRIO FINAL ---
    with aba_relatorio:
        st.markdown("### 📋 Gerador de Relatório para WhatsApp/Email")
        
        col1, col2 = st.columns(2)
        with col1:
            gerar = st.button("🔄 Gerar Relatório de Hoje", type="primary", use_container_width=True)
        with col2:
            apagar = st.button("🗑️ Apagar Dados e Relatório", use_container_width=True)

        if apagar:
            if os.path.exists(ARQUIVO_DADOS):
                os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE):
                os.remove(ARQUIVO_EQUIPE)
            st.success("✨ Todos os dados foram apagados com sucesso!")
            time.sleep(1)
            st.rerun()

        if gerar:
            data_hoje = datetime.now().strftime("%d/%m/%Y")
            
            try:
                df_maq = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
            except pd.errors.ParserError:
                df_maq = pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
                if os.path.exists(ARQUIVO_DADOS):
                    os.remove(ARQUIVO_DADOS)

            try:
                df_eq = pd.read_csv(ARQUIVO_EQUIPE) if os.path.exists(ARQUIVO_EQUIPE) else pd.DataFrame(columns=["Tipo", "Nome"])
            except pd.errors.ParserError:
                df_eq = pd.DataFrame(columns=["Tipo", "Nome"])
                if os.path.exists(ARQUIVO_EQUIPE):
                    os.remove(ARQUIVO_EQUIPE)
            
            if 'Operador' not in df_maq.columns:
                df_maq['Operador'] = ""
            
            manutencao = df_maq[df_maq['Status'] == 'MANUTENÇÃO']['Maquina'].tolist()
            rtf_setup = df_maq[(df_maq['Setor'] == 'RTF') & (df_maq['Status'].isin(['PREPARAÇÃO', 'SEQUÊNCIA']))]
            rtf_prod = df_maq[(df_maq['Setor'] == 'RTF') & (df_maq['Status'] == 'PRODUZINDO')]
            afc_setup = df_maq[(df_maq['Setor'] == 'AFC') & (df_maq['Status'].isin(['PREPARAÇÃO', 'SEQUÊNCIA']))]
            paradas = df_maq[df_maq['Status'] == 'PARADA']['Maquina'].tolist()
            
            treinamento = df_eq[df_eq['Tipo'] == 'Operador em Treinamento']['Nome'].tolist()
            ausencias = df_eq[df_eq['Tipo'] == 'Ausência / Falta']['Nome'].tolist()
            
            texto_final = f"PLANTA AFIACAO {data_hoje}\n"
            texto_final += "MAQUINAS EM MANUTENÇAO\n\n"
            texto_final += "\n".join(manutencao) if manutencao else "N/A"
            texto_final += "\n\nSetup/Ajuste\n\n"
            
            for index, row in rtf_setup.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - {row['Status']} - {row['Hora']}{op_nome}\n"
            texto_final += "\n"
            
            for index, row in rtf_prod.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - PRODUZINDO{op_nome}\n"
                
            texto_final += "\n"
            for index, row in afc_setup.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - {row['Status']} - {row['Hora']}{op_nome}\n"
                
            texto_final += "\n-----------------------------------------------\n"
            texto_final += "PARADAS DURANTE O TURNO.\n\n"
            texto_final += "\n".join(paradas) if paradas else "N/A"
            texto_final += "\n\nOPERADOR EM TREINAMENTO\n"
            texto_final += "\n".join(treinamento) if treinamento else "N/A"
            texto_final += "\n\nAusências\n"
            texto_final += "\n".join(ausencias) if ausencias else "N/A"
            
            st.code(texto_final, language="text")

if __name__ == "__main__":
    main()