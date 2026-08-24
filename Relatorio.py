import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# 1. Configuração Base (Layout Wide para visual de Dashboard)
st.set_page_config(page_title="Sistema MES", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")

# 2. CSS Premium (Estilo Corporativo / SaaS)
CSS_MES_THEME = """
<style>
    /* Fundo geral mais suave */
    .stApp { background-color: #0F172A !important; }
    
    /* Tipografia e Cores de Texto */
    h1, h2, h3, p, span, div[data-testid="stMarkdownContainer"] { 
        color: #F8FAFC !important; 
        font-family: 'Inter', 'Segoe UI', sans-serif !important; 
    }
    
    /* Labels dos inputs */
    label { 
        color: #94A3B8 !important; 
        font-size: 13px !important; 
        font-weight: 600 !important; 
        letter-spacing: 0.5px;
    }
    
    /* Inputs, Selects e Textareas */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { 
        background-color: #1E293B !important; 
        border: 1px solid #334155 !important; 
        border-radius: 8px !important; 
        transition: all 0.2s ease;
    }
    input, select, textarea { color: #F8FAFC !important; -webkit-text-fill-color: #F8FAFC !important; }
    div[data-baseweb="input"] > div:focus-within, div[data-baseweb="select"] > div:focus-within { 
        border-color: #3B82F6 !important; 
        box-shadow: 0 0 0 1px #3B82F6 !important;
    }
    
    /* Formulários (Cards) */
    div[data-testid="stForm"] { 
        background-color: #1E293B !important; 
        border: 1px solid #334155 !important; 
        border-radius: 12px !important; 
        padding: 25px !important; 
        border-top: 4px solid #3B82F6 !important; 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    
    /* Botões Principais */
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { 
        background-color: #2563EB !important; 
        color: white !important; 
        font-weight: 600 !important; 
        border: none !important; 
        border-radius: 8px !important; 
        transition: all 0.2s ease !important; 
        height: 45px !important; 
    }
    div[data-testid="stFormSubmitButton"] > button:hover, button[kind="primary"]:hover { 
        background-color: #1D4ED8 !important; 
        transform: translateY(-1px);
    }
    
    /* Abas (Tabs) */
    button[data-baseweb="tab"] { 
        background-color: transparent !important; 
        color: #94A3B8 !important; 
        font-weight: 600 !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
        padding-bottom: 10px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] { 
        color: #3B82F6 !important; 
        border-bottom: 2px solid #3B82F6 !important; 
    }
    
    /* Ocultar cabeçalho padrão do Streamlit */
    header {visibility: hidden;}
    
    /* Animação de Loading */
    .loading-screen { 
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; 
        background: #0F172A; z-index: 999999; display: flex; flex-direction: column; 
        justify-content: center; align-items: center; 
        animation: fadeOut 0.5s forwards; animation-delay: 1.2s; pointer-events: none; 
    }
    .spinner { 
        width: 60px; height: 60px; border-radius: 50%; 
        border: 3px solid transparent; border-top-color: #3B82F6; border-right-color: #60A5FA; 
        animation: spin 1s linear infinite; margin-bottom: 20px; 
    }
    .loading-text { color: #60A5FA !important; font-weight: 600; letter-spacing: 1.5px; font-size: 14px; }
    
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    @keyframes fadeOut { to { opacity: 0; visibility: hidden; } }
</style>
"""
st.markdown(CSS_MES_THEME, unsafe_allow_html=True)

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"

# Tela de Carregamento
if 'carregado' not in st.session_state:
    st.markdown("""<div class="loading-screen"><div class="spinner"></div><div class="loading-text">INICIALIZANDO SISTEMA MES...</div></div>""", unsafe_allow_html=True)
    time.sleep(1.2)
    st.session_state['carregado'] = True

def salvar_csv(dados, arquivo):
    df = pd.DataFrame([dados])
    if os.path.exists(arquivo):
        df.to_csv(arquivo, mode='a', header=False, index=False)
    else:
        df.to_csv(arquivo, index=False)

def main():
    # Cabeçalho Refinado
    st.markdown("<h1 style='text-align: center; font-weight: 800; letter-spacing: 1px; font-size: 2.2rem;'>SISTEMA MES</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #60A5FA !important; font-weight: 500; font-size: 1.1rem; margin-top: -10px; margin-bottom: 30px;'>CONTROLE DE PLANTA - AFIAÇÃO</p>", unsafe_allow_html=True)
    
    # Abas com Ícones
    aba_afc, aba_rtf, aba_equipe, aba_editar, aba_relatorio = st.tabs(["⚙️ Operação AFC", "⚙️ Operação RTF", "👥 Gestão de Equipe", "✏️ Base de Dados", "📋 Relatório de Turno"])
    
    # --- ABA AFC ---
    with aba_afc:
        st.markdown("### Lançamento de Status - AFC")
        with st.form("form_afc", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                # Pede apenas o número
                num_maq = st.text_input("NÚMERO DA MÁQUINA AFC", placeholder="Ex: 33")
                status = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO", "SEQUÊNCIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
                # Toggle profissional
                troca_rebolo = st.toggle("🔄 Houve Troca de Rebolo?")
            with col2:
                operador = st.text_input("NOME DO PREPARADOR / OPERADOR", placeholder="Digite o nome completo")
                hora = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:30")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Registrar Evento AFC", use_container_width=True):
                if num_maq and hora and operador:
                    maq_nome = f"AFC - {num_maq.strip().upper()}"
                    status_final = f"{status} (Com Troca de Rebolo)" if troca_rebolo else status
                    
                    salvar_csv({"Setor": "AFC", "Maquina": maq_nome, "Operador": operador.upper(), "Status": status_final, "Hora": hora}, ARQUIVO_DADOS)
                    st.success(f"✅ {maq_nome} registrada como {status_final} às {hora}!")
                else:
                    st.error("⚠️ Preencha todos os campos obrigatórios (Máquina, Operador e Hora)!")

    # --- ABA RTF ---
    with aba_rtf:
        st.markdown("### Lançamento de Status - RTF")
        with st.form("form_rtf", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                # Pede apenas o número
                num_maq = st.text_input("NÚMERO DA MÁQUINA RTF", placeholder="Ex: 10")
                # Separação Haste/Guia direto no status
                status = st.selectbox("STATUS ATUAL", ["PREPARAÇÃO - HASTE", "PREPARAÇÃO - GUIA", "PRODUZINDO", "MANUTENÇÃO", "PARADA"])
            with col2:
                operador = st.text_input("NOME DO PREPARADOR / OPERADOR", placeholder="Digite o nome completo")
                hora = st.text_input("HORA DO EVENTO", placeholder="Ex: 06:50")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Registrar Evento RTF", use_container_width=True):
                if num_maq and hora and operador:
                    maq_nome = f"RTF - {num_maq.strip().upper()}"
                    
                    salvar_csv({"Setor": "RTF", "Maquina": maq_nome, "Operador": operador.upper(), "Status": status, "Hora": hora}, ARQUIVO_DADOS)
                    st.success(f"✅ {maq_nome} registrada como {status} às {hora}!")
                else:
                    st.error("⚠️ Preencha todos os campos obrigatórios (Máquina, Operador e Hora)!")

    # --- ABA EQUIPE ---
    with aba_equipe:
        st.markdown("### Gestão de Pessoas (Líder)")
        with st.form("form_equipe", clear_on_submit=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                tipo = st.radio("TIPO DE REGISTRO", ["Operador em Treinamento", "Ausência / Falta"])
            with col2:
                nome = st.text_input("NOME DO COLABORADOR", placeholder="Nome completo do funcionário")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Salvar Registro de Colaborador", use_container_width=True):
                if nome:
                    salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                    st.success("✅ Colaborador registrado com sucesso!")
                else:
                    st.error("⚠️ Por favor, digite o nome do colaborador!")

    # --- ABA EDITAR ---
    with aba_editar:
        st.markdown("### Corrigir ou Excluir Dados")
        st.info("💡 **Dica:** Edite as células clicando nelas. Para excluir, selecione a linha clicando na margem esquerda e pressione a tecla **Delete**. Clique em Salvar para aplicar.")
        
        col_ed1, col_ed2 = st.columns(2)
        
        with col_ed1:
            st.markdown("#### ⚙️ Operações Registradas")
            if os.path.exists(ARQUIVO_DADOS):
                try:
                    df_maq = pd.read_csv(ARQUIVO_DADOS)
                    if 'Operador' not in df_maq.columns: df_maq['Operador'] = ""
                    df_maq_editado = st.data_editor(df_maq, num_rows="dynamic", use_container_width=True, key="edit_maq")
                    if st.button("💾 Atualizar Operações", use_container_width=True):
                        df_maq_editado.to_csv(ARQUIVO_DADOS, index=False)
                        st.success("Dados atualizados!")
                except Exception as e:
                    st.error("Erro ao ler os dados das máquinas.")
            else:
                st.caption("Nenhuma operação registrada no turno.")
                
        with col_ed2:
            st.markdown("#### 👥 Equipe Registrada")
            if os.path.exists(ARQUIVO_EQUIPE):
                try:
                    df_eq = pd.read_csv(ARQUIVO_EQUIPE)
                    df_eq_editado = st.data_editor(df_eq, num_rows="dynamic", use_container_width=True, key="edit_eq")
                    if st.button("💾 Atualizar Equipe", use_container_width=True):
                        df_eq_editado.to_csv(ARQUIVO_EQUIPE, index=False)
                        st.success("Dados atualizados!")
                except Exception as e:
                    st.error("Erro ao ler os dados da equipe.")
            else:
                st.caption("Nenhum colaborador registrado no turno.")
                
        st.divider()
        with st.expander("⚠️ ZERAR TODOS OS DADOS (FIM DE TURNO)"):
            st.warning("Esta ação é irreversível. Todos os dados coletados neste turno serão apagados do servidor.")
            if st.button("🗑️ ENCERRAR TURNO E APAGAR DADOS", type="primary", use_container_width=True):
                if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
                if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
                st.success("✨ Sistema redefinido e pronto para um novo turno!")
                time.sleep(1)
                st.rerun()

    # --- ABA RELATÓRIO FINAL ---
    with aba_relatorio:
        st.markdown("### Exportar Relatório Consolidado")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            gerar = st.button("🔄 Gerar Relatório de Hoje", type="primary", use_container_width=True)
        with col2:
            st.write("") # Espaçamento para alinhar
            
        if gerar:
            data_hoje = datetime.now().strftime("%d/%m/%Y")
            
            try:
                df_maq = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
            except pd.errors.ParserError:
                df_maq = pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
                if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)

            try:
                df_eq = pd.read_csv(ARQUIVO_EQUIPE) if os.path.exists(ARQUIVO_EQUIPE) else pd.DataFrame(columns=["Tipo", "Nome"])
            except pd.errors.ParserError:
                df_eq = pd.DataFrame(columns=["Tipo", "Nome"])
                if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            
            if 'Operador' not in df_maq.columns: df_maq['Operador'] = ""
            
            # Filtros atualizados para capturar os novos status com Toggle (AFC) e Haste/Guia (RTF)
            manutencao = df_maq[df_maq['Status'] == 'MANUTENÇÃO']['Maquina'].tolist()
            rtf_setup = df_maq[(df_maq['Setor'] == 'RTF') & (df_maq['Status'].str.contains('PREPARAÇÃO', na=False))]
            rtf_prod = df_maq[(df_maq['Setor'] == 'RTF') & (df_maq['Status'] == 'PRODUZINDO')]
            afc_setup = df_maq[(df_maq['Setor'] == 'AFC') & (df_maq['Status'].str.contains('PREPARAÇÃO|SEQUÊNCIA', na=False))]
            paradas = df_maq[df_maq['Status'] == 'PARADA']['Maquina'].tolist()
            
            treinamento = df_eq[df_eq['Tipo'] == 'Operador em Treinamento']['Nome'].tolist()
            ausencias = df_eq[df_eq['Tipo'] == 'Ausência / Falta']['Nome'].tolist()
            
            # Formatação do texto do relatório
            texto_final = f"🏭 PLANTA AFIAÇÃO - {data_hoje}\n"
            texto_final += "="*40 + "\n\n"
            
            texto_final += "🛠️ MÁQUINAS EM MANUTENÇÃO\n"
            texto_final += "\n".join(manutencao) if manutencao else "N/A"
            texto_final += "\n\n" + "-"*40 + "\n\n"
            
            texto_final += "⚙️ SETUP / AJUSTE\n"
            for index, row in rtf_setup.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - {row['Status']} - {row['Hora']}{op_nome}\n"
            for index, row in afc_setup.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - {row['Status']} - {row['Hora']}{op_nome}\n"
            texto_final += "\n" + "-"*40 + "\n\n"
            
            texto_final += "✅ EM PRODUÇÃO (RTF)\n"
            for index, row in rtf_prod.iterrows():
                op_nome = f" - {row['Operador']}" if pd.notna(row['Operador']) and row['Operador'] != "" else ""
                texto_final += f"{row['Maquina']} - PRODUZINDO{op_nome}\n"
            texto_final += "\n" + "-"*40 + "\n\n"
            
            texto_final += "🛑 PARADAS DURANTE O TURNO\n"
            texto_final += "\n".join(paradas) if paradas else "N/A"
            texto_final += "\n\n" + "-"*40 + "\n\n"
            
            texto_final += "👥 EQUIPE\n"
            texto_final += "Operador em Treinamento:\n"
            texto_final += "\n".join(treinamento) if treinamento else "N/A"
            texto_final += "\n\nAusências:\n"
            texto_final += "\n".join(ausencias) if ausencias else "N/A"
            
            st.markdown("#### Pré-visualização do Relatório (Copie e cole no WhatsApp/E-mail)")
            st.code(texto_final, language="text")

if __name__ == "__main__":
    main()