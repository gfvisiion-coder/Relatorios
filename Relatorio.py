import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# --- CONFIGURAÇÃO BASE DO APP ---
st.set_page_config(page_title="App MES - Planta", page_icon="📱", layout="centered", initial_sidebar_state="collapsed")

# --- CSS PREMIUM & FIX PARA MOBILE (SEM CORTAR) ---
CSS_APP = """
<style>
    .stApp { background-color: #121214 !important; }
    h1, h2, h3, h4, h5, p, span, div[data-testid="stMarkdownContainer"] { color: #F8FAFC !important; font-family: 'Inter', sans-serif !important; }
    label { color: #A1A1AA !important; font-size: 13px !important; font-weight: 600 !important; }
    
    /* Botões dos Grids e Células */
    button[kind="secondary"] { background-color: #202024 !important; color: #E4E4E7 !important; border: 1px solid #323238 !important; border-radius: 6px !important; font-weight: bold !important; height: 48px !important; font-size: 11px !important;}
    button[kind="secondary"]:hover { border-color: #14B8A6 !important; background-color: #27272A !important; }
    
    /* Botões de Ação Principal */
    div[data-testid="stFormSubmitButton"] > button, button[kind="primary"] { background-color: #0D9488 !important; color: white !important; border: none !important; border-radius: 8px !important; height: 45px !important; font-weight: bold !important; }
    
    /* Inputs */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { background-color: #202024 !important; border: 1px solid #323238 !important; border-radius: 8px !important; }
    input, select, textarea { color: white !important; }
    header { visibility: hidden; }

    /* FORÇAR COMPACIDADE MÁXIMA NO CELULAR */
    @media (max-width: 768px) {
        .block-container { padding-left: 0.2rem !important; padding-right: 0.2rem !important; padding-top: 1rem !important; }
        div[data-testid="stHorizontalBlock"] { 
            display: flex !important;
            flex-direction: row !important; 
            flex-wrap: nowrap !important; 
            gap: 2px !important;
        }
        div[data-testid="column"] { 
            flex: 1 1 auto !important; 
            min-width: 0 !important; 
            padding: 0px !important;
        }
        button[kind="secondary"] { padding: 0px !important; font-size: 10px !important; height: 42px !important; }
    }
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
if 'celula_selecionada' not in st.session_state:
    st.session_state['celula_selecionada'] = None
if 'maq_ativa' not in st.session_state:
    st.session_state['maq_ativa'] = None
if 'setor_ativo' not in st.session_state:
    st.session_state['setor_ativo'] = None

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
#        PAINEL DE CONTROLE DA MÁQUINA (FIXO)
# ==========================================
def painel_controle_maquina(maq_id, setor):
    with st.container(border=True):
        col_t, col_f = st.columns([8, 1])
        col_t.markdown(f"### ⚙️ Máquina: {maq_id}")
        if col_f.button("❌", key=f"fechar_{maq_id}"):
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        info = obter_info_maquina(maq_id, setor)
        status_atual = info.get('Status', 'Desconhecido') if info else '⚪ Sem registro'
        hora_atual = info.get('Hora', '--:--') if info else ''
        operador_atual = info.get('Operador', 'Não informado') if info else ''
        
        if info:
            if "PREPARAÇÃO" in status_atual or "SEQUÊNCIA" in status_atual:
                st.info(f"🟡 **Status:** Em preparação desde **{hora_atual}** (Op: {operador_atual})")
            elif "PRODUZINDO" in status_atual:
                st.success(f"🟢 **Status:** Produzindo desde **{hora_atual}** (Op: {operador_atual})")
            elif "PARADA" in status_atual:
                st.error(f"🔴 **Status:** Parada desde **{hora_atual}** (Op: {operador_atual})")
            elif "MANUTENÇÃO" in status_atual:
                st.warning(f"🛠️ **Status:** Em manutenção desde **{hora_atual}** (Resp: {operador_atual})")
            else:
                st.write(f"**Status:** {status_atual} às {hora_atual}")
        else:
            st.write("⚪ **Status:** Nenhum apontamento neste turno.")
            
        st.divider()
        
        flow_key = f"flow_{maq_id}"
        if flow_key not in st.session_state:
            st.session_state[flow_key] = "pergunta"
            
        if st.session_state[flow_key] == "pergunta":
            if "MANUTENÇÃO" in status_atual:
                st.write("⚠️ Esta máquina está em manutenção.")
                pergunta = "Ela já voltou a rodar?"
            else:
                pergunta = "Deseja alterar o status?"
                
            st.write(pergunta)
            c1, c2 = st.columns(2)
            if c1.button("✅ Sim", key=f"s_{maq_id}", use_container_width=True):
                st.session_state[flow_key] = "formulario"
                st.rerun()
            if c2.button("🚫 Cancelar", key=f"n_{maq_id}", use_container_width=True):
                st.session_state['maq_ativa'] = None
                if flow_key in st.session_state:
                    del st.session_state[flow_key]
                st.rerun()
                
        elif st.session_state[flow_key] == "formulario":
            with st.form(f"form_real_{maq_id}"):
                status = st.selectbox("Novo Status:", ["🟢 PRODUZINDO", "🟡 PREPARAÇÃO", "🛠️ MANUTENÇÃO", "🔴 PARADA"])
                
                motivo = ""
                if "MANUTENÇÃO" in status:
                    motivo = st.text_input("📝 Motivo da Manutenção (Obrigatório):", placeholder="Ex: Quebra de eixo...")
                    
                tipo_prep = None
                troca_diametro = False
                if setor == "RTF" and "PREPARAÇÃO" in status:
                    tipo_prep = st.radio("Tipo de Setup:", ["HASTE", "GUIA"], horizontal=True)
                    if tipo_prep == "HASTE":
                        troca_diametro = st.toggle("📐 Troca de Diâmetro?")
                        
                troca_rebolo = st.toggle("🔄 Troca de Rebolo?")
                hora = st.text_input("⏰ Hora do Evento (Ex: 06:30):")
                
                col_b1, col_b2 = st.columns(2)
                if col_b1.form_submit_button("⬅️ Voltar"):
                    st.session_state[flow_key] = "pergunta"
                    st.rerun()
                    
                if col_b2.form_submit_button("💾 Salvar", type="primary"):
                    if "MANUTENÇÃO" in status and not motivo.strip():
                        st.error("⚠️ Informe o motivo da manutenção!")
                    elif not hora.strip():
                        st.error("⚠️ Preencha a hora!")
                    else:
                        status_limpo = status.replace("🟢 ", "").replace("🟡 ", "").replace("🛠️ ", "").replace("🔴 ", "")
                        status_final = status_limpo
                        
                        if setor == "RTF" and "PREPARAÇÃO" in status:
                            status_final += f" - {tipo_prep}"
                            if tipo_prep == "HASTE" and troca_diametro: status_final += " (C/ Troca Diâmetro)"
                        if troca_rebolo: 
                            status_final += " (C/ Troca Rebolo)"
                        if motivo: 
                            status_final += f" - Motivo: {motivo}"
                        
                        salvar_csv({
                            "Setor": setor, 
                            "Maquina": f"{setor} {maq_id}", 
                            "Operador": st.session_state['operador'], 
                            "Status": status_final, 
                            "Hora": hora
                        }, ARQUIVO_DADOS)
                        
                        if flow_key in st.session_state:
                            del st.session_state[flow_key]
                        st.session_state['maq_ativa'] = None
                        st.success("✅ Salvo com sucesso!")
                        time.sleep(1)
                        st.rerun()

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
        if st.button("⚙️ AFIAÇÃO (CÉLULAS)", use_container_width=True): mudar_tela('afc')
        if st.button("👥 GESTÃO DE EQUIPE", use_container_width=True): mudar_tela('equipe')
    with col2:
        if st.button("⚙️ RETÍFICA (CÉLULAS)", use_container_width=True): mudar_tela('rtf')
        if st.button("✏️ CORRIGIR DADOS", use_container_width=True): mudar_tela('editar')

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📋 GERAR RELATÓRIO DE TURNO", use_container_width=True, type="primary"): mudar_tela('relatorio')
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🚪 Sair (Logout)", use_container_width=True):
        st.session_state['operador'] = ''
        mudar_tela('login')

def render_grid_matricial(matriz, setor, status_dict):
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
                    st.session_state['maq_ativa'] = maq
                    st.session_state['setor_ativo'] = setor
                    st.rerun()

def tela_afc():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("### 🗂️ Selecione a Célula - Afiação")
    st.caption("🟢 Produzindo | 🟡 Setup | 🔴 Parada | 🛠️ Manutenção | ⚪ Sem apontamento")
    st.divider()
    
    status_dict = ler_status_atual()
    
    # Se houver uma máquina ativa, exibe o painel de controle dela no topo
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'AFC':
        painel_controle_maquina(st.session_state['maq_ativa'], 'AFC')
        st.divider()
    
    if st.session_state['celula_selecionada'] is None:
        col1, col2 = st.columns(2)
        if col1.button("📌 Célula 1 (Bloco Esquerdo)", use_container_width=True):
            st.session_state['celula_selecionada'] = 'celula_1'
            st.rerun()
        if col2.button("📌 Célula 2 (Bloco Direito)", use_container_width=True):
            st.session_state['celula_selecionada'] = 'celula_2'
            st.rerun()
    else:
        if st.button("⬅️ Trocar de Célula"):
            st.session_state['celula_selecionada'] = None
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        st.divider()
        
        if st.session_state['celula_selecionada'] == 'celula_1':
            st.markdown("#### Célula 1 (Bloco Esquerdo)")
            matriz_esq = [
                ["30-161", "29-078"],
                ["32-081", "31-969"],
                ["34-132", "33-160"],
                ["36-084", "35-131"],
                ["38-596", "37-892"],
                ["40-142", "39-905"],
                ["", "41-141"]
            ]
            render_grid_matricial(matriz_esq, "AFC", status_dict)
            
        elif st.session_state['celula_selecionada'] == 'celula_2':
            st.markdown("#### Célula 2 (Bloco Direito Completo)")
            matriz_dir = [
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
            render_grid_matricial(matriz_dir, "AFC", status_dict)

def tela_rtf():
    if st.button("⬅️ Voltar ao Menu"): mudar_tela('menu')
    st.markdown("### 🗂️ Selecione a Célula - Retífica")
    st.caption("🟢 Produzindo | 🟡 Setup | 🔴 Parada | 🛠️ Manutenção | ⚪ Sem apontamento")
    st.divider()
    
    status_dict = ler_status_atual()
    
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'RTF':
        painel_controle_maquina(st.session_state['maq_ativa'], 'RTF')
        st.divider()
    
    if st.session_state['celula_selecionada'] is None:
        col1, col2 = st.columns(2)
        if col1.button("⚫ Centerless", use_container_width=True):
            st.session_state['celula_selecionada'] = 'cent'
            st.rerun()
        if col2.button("🟣 Retíficas Padrão", use_container_width=True):
            st.session_state['celula_selecionada'] = 'rtf_padrao'
            st.rerun()
    else:
        if st.button("⬅️ Trocar de Célula"):
            st.session_state['celula_selecionada'] = None
            st.session_state['maq_ativa'] = None
            st.rerun()
            
        st.divider()
        
        if st.session_state['celula_selecionada'] == 'cent':
            st.markdown("#### Centerless")
            matriz = [["6-6J1", "17-6J1"]]
            render_grid_matricial(matriz, "RTF", status_dict)
            
        elif st.session_state['celula_selecionada'] == 'rtf_padrao':
            st.markdown("#### Retíficas Padrão")
            matriz = [
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
            render_grid_matricial(matriz, "RTF", status_dict)

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