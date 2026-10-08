import streamlit as st
import pandas as pd
import re
import os
import time
from datetime import datetime, timezone, timedelta, time as dtime
import requests
import math
import unicodedata
import uuid
import threading
import json
import base64
import hmac
import hashlib
import textwrap
import html
from requests.adapters import HTTPAdapter
import extra_streamlit_components as stx

# =============================================================
# 🛡️ PROTEÇÃO CONTRA RECURSÃO EM RERUNS DO STREAMLIT
# =============================================================
# O Streamlit reexecuta este arquivo no MESMO processo. Como o app usa wrappers
# de compatibilidade para pd.read_csv/to_csv/os.path.exists/os.remove, um rerun
# poderia herdar os wrappers da execução anterior. Restauramos as implementações
# reais ANTES de qualquer acesso ao Turso ou a arquivos.
from pandas.io.parsers import read_csv as _BASE_PANDAS_READ_CSV
from pandas.core.generic import NDFrame as _BASE_PANDAS_NDFRAME
import genericpath as _BASE_GENERICPATH

pd.read_csv = _BASE_PANDAS_READ_CSV
pd.DataFrame.to_csv = _BASE_PANDAS_NDFRAME.to_csv
os.path.exists = _BASE_GENERICPATH.exists
os.remove = os.unlink

# Configuração do Streamlit deve ocorrer antes de qualquer outro comando st.*.
st.set_page_config(page_title="Relatório - Setor Afiação", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")


# ==========================================
# 🚀 INTEGRAÇÃO COM BANCO DE DADOS TURSO
# ==========================================
# O app usa o Turso como fonte oficial dos dados. Os arquivos CSV antigos
# continuam sendo reconhecidos pelo código abaixo, mas agora são apenas nomes
# lógicos de tabelas no banco. O Excel de rebolos continua sendo um arquivo
# estático de leitura.
try:
    TURSO_URL = st.secrets.get("TURSO_DATABASE_URL", os.getenv("TURSO_DATABASE_URL", ""))
    TURSO_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", os.getenv("TURSO_AUTH_TOKEN", ""))
except Exception:
    TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

if not TURSO_URL or not TURSO_TOKEN:
    st.error("⚠️ TURSO_DATABASE_URL e TURSO_AUTH_TOKEN não foram configurados nos Secrets.")
    st.stop()

# Segredo usado para assinar o cookie de login automático.
# Se LOGIN_COOKIE_SECRET não existir nos Secrets, usamos o token do Turso
# apenas como chave interna do servidor (ele nunca é enviado ao navegador).
try:
    LOGIN_COOKIE_SECRET = str(st.secrets.get("LOGIN_COOKIE_SECRET", TURSO_TOKEN))
except Exception:
    LOGIN_COOKIE_SECRET = str(os.getenv("LOGIN_COOKIE_SECRET", TURSO_TOKEN))

TURSO_URL = str(TURSO_URL).strip()
if TURSO_URL.startswith("libsql://"):
    TURSO_HTTP_URL = "https://" + TURSO_URL[len("libsql://"):]
elif TURSO_URL.startswith("https://"):
    TURSO_HTTP_URL = TURSO_URL
else:
    TURSO_HTTP_URL = "https://" + TURSO_URL
TURSO_HTTP_URL = TURSO_HTTP_URL.rstrip("/")
TURSO_PIPELINE_URL = TURSO_HTTP_URL + "/v3/pipeline"

_TURSO_HEADERS = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json",
}

@st.cache_resource(show_spinner=False)
def _http_session():
    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update(_TURSO_HEADERS)
    return sess


def _post_turso(payload, timeout=30):
    try:
        return _http_session().post(TURSO_PIPELINE_URL, json=payload, timeout=(5, timeout))
    except requests.RequestException as exc:
        raise RuntimeError(f"Não foi possível acessar o Turso: {exc}") from exc


@st.cache_resource(show_spinner=False)
def _runtime_db_cache():
    return {
        "lock": threading.RLock(),
        "exists": {},
        "tables": {},
        "latest": None,
        "estado_ok": False,
        "index_ok": set(),
    }


def _turso_value(value):
    """Converte um valor Python para o formato de argumentos do protocolo Turso."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        import base64
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _turso_decode(value):
    if value is None:
        return None
    typ = value.get("type")
    if typ == "null":
        return None
    if typ == "integer":
        try:
            return int(value.get("value", 0))
        except Exception:
            return 0
    if typ == "float":
        return value.get("value")
    if typ == "blob":
        import base64
        try:
            return base64.b64decode(value.get("base64", ""))
        except Exception:
            return None
    return value.get("value")


def turso_request(sql, args=None, want_rows=True, timeout=30):
    """Executa uma instrução SQL diretamente na API HTTP do Turso."""
    stmt = {"sql": sql, "want_rows": want_rows}
    if args:
        stmt["args"] = [_turso_value(v) for v in args]

    payload = {
        "baton": None,
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"},
        ],
    }

    resp = _post_turso(payload, timeout=timeout)

    if resp.status_code != 200:
        raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:1000]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Resposta inválida do Turso: {resp.text[:1000]}") from exc

    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"O Turso não retornou resultado: {data}")

    first = results[0]
    if first.get("type") == "error":
        err = first.get("error", {})
        raise RuntimeError(f"Erro SQL Turso: {err.get('message', err)}")

    result = first.get("response", {}).get("result", {})
    return result


def _quote_identifier(name):
    return '"' + str(name).replace('"', '""') + '"'


def _sql_type(series):
    if pd.api.types.is_bool_dtype(series):
        return "INTEGER"
    if pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "REAL"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TEXT"
    return "TEXT"


def tabela_existe(nome_tabela):
    cache = _runtime_db_cache()
    agora = time.monotonic()
    with cache["lock"]:
        item = cache["exists"].get(nome_tabela)
        if item and agora - item[0] < 300:
            return item[1]
    result = turso_request("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", [nome_tabela], True)
    existe = bool(result.get("rows"))
    with cache["lock"]:
        cache["exists"][nome_tabela] = (agora, existe)
    return existe


def _marcar_tabela_existe(nome_tabela, existe=True):
    cache = _runtime_db_cache()
    with cache["lock"]:
        cache["exists"][nome_tabela] = (time.monotonic(), bool(existe))


def _invalidar_cache_turso(nome_tabela=None, invalidar_existencia=False):
    cache = _runtime_db_cache()
    with cache["lock"]:
        if nome_tabela is None:
            cache["tables"].clear()
            cache["latest"] = None
            if invalidar_existencia:
                cache["exists"].clear()
            return
        cache["tables"].pop(nome_tabela, None)
        if nome_tabela == globals().get("ARQUIVO_DADOS", "banco_operacao.csv"):
            cache["latest"] = None
        if invalidar_existencia:
            cache["exists"].pop(nome_tabela, None)


def _table_ttl(nome_tabela):
    return {
        "banco_cnc.csv": 120.0,
        "ultimo_fechamento.csv": 60.0,
        "historico_relatorios.csv": 30.0,
        "historico_eventos.csv": 30.0,
        "banco_equipe.csv": 10.0,
        "banco_armarios.csv": 5.0,
        "alertas_preset.csv": 3.0,
        "historico_devolucoes.csv": 10.0,
        "banco_operacao.csv": 3.0,
    }.get(str(nome_tabela), 10.0)


def criar_tabela_dataframe(df, nome_tabela):
    colunas = list(df.columns)
    if not colunas:
        return
    definicoes = ", ".join(f"{_quote_identifier(col)} {_sql_type(df[col])}" for col in colunas)
    turso_request(f"CREATE TABLE IF NOT EXISTS {_quote_identifier(nome_tabela)} ({definicoes})", want_rows=False)
    _marcar_tabela_existe(nome_tabela, True)
    _invalidar_cache_turso(nome_tabela)
    if nome_tabela == globals().get("ARQUIVO_DADOS", "banco_operacao.csv"):
        cache = _runtime_db_cache()
        with cache["lock"]:
            cache["index_ok"].discard(nome_tabela)
        _garantir_indice_operacao()


def _garantir_indice_operacao():
    nome = globals().get("ARQUIVO_DADOS", "banco_operacao.csv")
    if not tabela_existe(nome):
        return
    cache = _runtime_db_cache()
    with cache["lock"]:
        if nome in cache["index_ok"]:
            return
    try:
        turso_request(f'CREATE INDEX IF NOT EXISTS "idx_operacao_maquina" ON {_quote_identifier(nome)} ("Maquina")', want_rows=False)
        with cache["lock"]:
            cache["index_ok"].add(nome)
    except Exception:
        pass


def _garantir_estado_maquinas():
    cache = _runtime_db_cache()
    with cache["lock"]:
        if cache["estado_ok"]:
            return
    estado = "__estado_maquinas"
    turso_request(
        f'''CREATE TABLE IF NOT EXISTS {_quote_identifier(estado)} (
            "Setor" TEXT,
            "Maquina" TEXT PRIMARY KEY,
            "Operador" TEXT,
            "Status" TEXT,
            "Hora" TEXT
        )''', want_rows=False)
    probe = turso_request(f"SELECT 1 FROM {_quote_identifier(estado)} LIMIT 1", want_rows=True)
    if not probe.get("rows"):
        dados = globals().get("ARQUIVO_DADOS", "banco_operacao.csv")
        if tabela_existe(dados):
            try:
                turso_request(
                    f'''INSERT OR REPLACE INTO {_quote_identifier(estado)}
                        ("Setor", "Maquina", "Operador", "Status", "Hora")
                        SELECT t."Setor", t."Maquina", t."Operador", t."Status", t."Hora"
                        FROM {_quote_identifier(dados)} AS t
                        INNER JOIN (
                            SELECT "Maquina", MAX(rowid) AS rid
                            FROM {_quote_identifier(dados)}
                            GROUP BY "Maquina"
                        ) AS x ON x.rid = t.rowid''', want_rows=False, timeout=60)
            except Exception:
                pass
    _garantir_indice_operacao()
    with cache["lock"]:
        cache["estado_ok"] = True
        cache["latest"] = None


def _estado_upsert_stmt(vals):
    estado = "__estado_maquinas"
    sql = f'''INSERT INTO {_quote_identifier(estado)}
        ("Setor", "Maquina", "Operador", "Status", "Hora")
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT("Maquina") DO UPDATE SET
            "Setor"=excluded."Setor",
            "Operador"=excluded."Operador",
            "Status"=excluded."Status",
            "Hora"=excluded."Hora"'''
    return {"type": "execute", "stmt": {"sql": sql, "args": [_turso_value(v) for v in vals], "want_rows": False}}


def inserir_dataframe(df, nome_tabela):
    if df.empty:
        return
    if not tabela_existe(nome_tabela):
        criar_tabela_dataframe(df, nome_tabela)
    colunas = list(df.columns)
    nomes = ", ".join(_quote_identifier(c) for c in colunas)
    placeholders = ", ".join("?" for _ in colunas)
    sql = f"INSERT INTO {_quote_identifier(nome_tabela)} ({nomes}) VALUES ({placeholders})"
    rows = []
    for row in df.itertuples(index=False, name=None):
        vals = []
        for value in row:
            if pd.isna(value): vals.append(None)
            elif isinstance(value, pd.Timestamp): vals.append(value.isoformat())
            else: vals.append(value.item() if hasattr(value, "item") else value)
        rows.append(vals)
    eh_operacao = nome_tabela == globals().get("ARQUIVO_DADOS", "banco_operacao.csv")
    if eh_operacao:
        _garantir_estado_maquinas()
    lote_tam = 50 if eh_operacao else 100
    for inicio in range(0, len(rows), lote_tam):
        lote = rows[inicio:inicio + lote_tam]
        requests_pipeline = []
        for vals in lote:
            requests_pipeline.append({"type": "execute", "stmt": {"sql": sql, "args": [_turso_value(v) for v in vals], "want_rows": False}})
            if eh_operacao:
                row_map = dict(zip(colunas, vals))
                requests_pipeline.append(_estado_upsert_stmt([row_map.get("Setor"), row_map.get("Maquina"), row_map.get("Operador"), row_map.get("Status"), row_map.get("Hora")]))
        requests_pipeline.append({"type": "close"})
        payload = {"baton": None, "requests": requests_pipeline}
        resp = _post_turso(payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:1000]}")
        data = resp.json()
        for result in data.get("results", []):
            if result.get("type") == "error":
                err = result.get("error", {})
                raise RuntimeError(f"Erro SQL Turso: {err.get('message', err)}")
    _invalidar_cache_turso(nome_tabela)


def _carregar_tabela_bruta(nome_tabela):
    cache = _runtime_db_cache()
    agora = time.monotonic()
    ttl = _table_ttl(nome_tabela)
    with cache["lock"]:
        item = cache["tables"].get(nome_tabela)
        if item and agora - item[0] < ttl:
            return item[1].copy()
    result = turso_request(f"SELECT * FROM {_quote_identifier(nome_tabela)}", want_rows=True)
    cols = [c.get("name") for c in result.get("cols", [])]
    rows = [[_turso_decode(v) for v in row] for row in result.get("rows", [])]
    df = pd.DataFrame(rows, columns=cols)
    with cache["lock"]:
        cache["tables"][nome_tabela] = (agora, df)
    return df.copy()


def _carregar_ultimos_apontamentos():
    _garantir_estado_maquinas()
    cache = _runtime_db_cache()
    agora = time.monotonic()
    with cache["lock"]:
        item = cache.get("latest")
        if item and agora - item[0] < 2.0:
            return item[1].copy()
    estado = "__estado_maquinas"
    result = turso_request(f'SELECT "Setor", "Maquina", "Operador", "Status", "Hora" FROM {_quote_identifier(estado)}', want_rows=True)
    cols = [c.get("name") for c in result.get("cols", [])]
    rows = [[_turso_decode(v) for v in row] for row in result.get("rows", [])]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        df = pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
    with cache["lock"]:
        cache["latest"] = (agora, df)
    return df.copy()


def _reconstruir_estado_maquinas():
    cache = _runtime_db_cache()
    estado = "__estado_maquinas"
    dados = globals().get("ARQUIVO_DADOS", "banco_operacao.csv")
    try:
        _garantir_estado_maquinas()
        turso_request(f"DELETE FROM {_quote_identifier(estado)}", want_rows=False)
        if tabela_existe(dados):
            turso_request(
                f'''INSERT OR REPLACE INTO {_quote_identifier(estado)}
                    ("Setor", "Maquina", "Operador", "Status", "Hora")
                    SELECT t."Setor", t."Maquina", t."Operador", t."Status", t."Hora"
                    FROM {_quote_identifier(dados)} AS t
                    INNER JOIN (
                        SELECT "Maquina", MAX(rowid) AS rid
                        FROM {_quote_identifier(dados)}
                        GROUP BY "Maquina"
                    ) AS x ON x.rid = t.rowid''', want_rows=False, timeout=60)
    finally:
        with cache["lock"]:
            cache["latest"] = None
            cache["index_ok"].discard(dados)
        _garantir_indice_operacao()


def carregar_tabela(nome_tabela, colunas_padrao=None, **kwargs):
    """Substitui pd.read_csv para as tabelas persistentes do app."""
    colunas_padrao = colunas_padrao or []
    try:
        df = _carregar_tabela_bruta(nome_tabela).copy()
        if kwargs.get("dtype") is not None and not df.empty:
            dtype = kwargs.get("dtype")
            try:
                if isinstance(dtype, dict):
                    for col, typ in dtype.items():
                        if col in df.columns:
                            df[col] = df[col].astype(typ)
                else:
                    df = df.astype(dtype)
            except Exception:
                pass
        if df.empty and colunas_padrao:
            df = pd.DataFrame(columns=colunas_padrao)
        return df
    except Exception as exc:
        if not tabela_existe(nome_tabela):
            return pd.DataFrame(columns=colunas_padrao)
        raise exc


def _turso_batch_atomico(steps, timeout=30):
    """Executa um batch Hrana no mesmo stream e reporta erro de qualquer etapa."""
    payload = {
        "baton": None,
        "requests": [
            {"type": "batch", "batch": {"steps": steps}},
            {"type": "close"},
        ],
    }
    resp = _post_turso(payload, timeout=timeout)

    if resp.status_code != 200:
        raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:1000]}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"O Turso não retornou resultado: {data}")

    first = results[0]
    if first.get("type") == "error":
        err = first.get("error", {})
        raise RuntimeError(f"Erro Turso: {err.get('message', err)}")

    batch_result = first.get("response", {}).get("result", {})
    step_errors = batch_result.get("step_errors", []) or []
    erros = [e for e in step_errors if e]
    if erros:
        msg = erros[0].get("message", erros[0]) if isinstance(erros[0], dict) else erros[0]
        raise RuntimeError(f"Erro SQL Turso em transação: {msg}")


def _stmt_batch(sql, args=None, condition=None):
    step = {
        "stmt": {
            "sql": sql,
            "args": [_turso_value(v) for v in (args or [])],
            "want_rows": False,
        }
    }
    if condition is not None:
        step["condition"] = condition
    return step


def salvar_tabela(df, nome_tabela, modo="replace"):
    """
    Persistência segura.

    No modo replace, os dados novos são montados primeiro em uma tabela temporária.
    Só depois ocorre a troca dentro de uma transação. Se internet/inserção falhar,
    a tabela antiga continua intacta.
    """
    df = df.copy()
    if modo not in ("replace", "append"):
        modo = "replace"

    if modo == "append":
        if not tabela_existe(nome_tabela):
            criar_tabela_dataframe(df, nome_tabela)
        inserir_dataframe(df, nome_tabela)
        return

    colunas = list(df.columns)
    if not colunas:
        raise RuntimeError(f"Recusei substituir {nome_tabela}: DataFrame sem colunas.")

    # Carrega tudo na temporária sem tocar na tabela oficial.
    tmp = f"__tmp_{re.sub(r'[^0-9A-Za-z_]+', '_', str(nome_tabela))}_{uuid.uuid4().hex[:10]}"
    try:
        definicoes = ", ".join(
            f"{_quote_identifier(col)} {_sql_type(df[col])}" for col in colunas
        )
        turso_request(f"CREATE TABLE {_quote_identifier(tmp)} ({definicoes})", want_rows=False)
        if not df.empty:
            inserir_dataframe(df, tmp)

        # A troca é atômica: DROP e RENAME ficam dentro da mesma transação.
        steps = [
            _stmt_batch("BEGIN IMMEDIATE"),
            _stmt_batch(
                f"DROP TABLE IF EXISTS {_quote_identifier(nome_tabela)}",
                condition={"type": "ok", "step": 0},
            ),
            _stmt_batch(
                f"ALTER TABLE {_quote_identifier(tmp)} RENAME TO {_quote_identifier(nome_tabela)}",
                condition={"type": "ok", "step": 1},
            ),
            _stmt_batch(
                "COMMIT",
                condition={"type": "ok", "step": 2},
            ),
            # Se qualquer etapa da troca falhar, desfaz a transação.
            _stmt_batch(
                "ROLLBACK",
                condition={
                    "type": "or",
                    "conds": [
                        {"type": "error", "step": 0},
                        {"type": "error", "step": 1},
                        {"type": "error", "step": 2},
                        {"type": "error", "step": 3},
                    ],
                },
            ),
        ]
        _turso_batch_atomico(steps)
    except Exception:
        # Tenta limpar apenas a temporária. A oficial não é tocada antes da troca atômica.
        try:
            turso_request(f"DROP TABLE IF EXISTS {_quote_identifier(tmp)}", want_rows=False)
        except Exception:
            pass
        raise
    finally:
        _marcar_tabela_existe(nome_tabela, True)
        _invalidar_cache_turso(nome_tabela)
        if nome_tabela == globals().get("ARQUIVO_DADOS", "banco_operacao.csv"):
            _reconstruir_estado_maquinas()


def remover_tabela(nome_tabela):
    """Remove a tabela solicitada; use apenas em ações explícitas de exclusão."""
    turso_request(f"DROP TABLE IF EXISTS {_quote_identifier(nome_tabela)}", want_rows=False)
    _marcar_tabela_existe(nome_tabela, False)
    _invalidar_cache_turso(nome_tabela)
    if nome_tabela == globals().get("ARQUIVO_DADOS", "banco_operacao.csv"):
        cache = _runtime_db_cache()
        with cache["lock"]:
            cache["latest"] = None
            cache["index_ok"].discard(nome_tabela)
        try:
            turso_request('DELETE FROM "__estado_maquinas"', want_rows=False)
        except Exception:
            pass

# (Mantenha o restante das suas variáveis globais aqui, como FUSO_BR, TODAS_AFC, etc)
# Obs: O ARQUIVO_REBOLOS (Excel) pode continuar igual, pois planilhas estáticas de leitura ficam no código fonte.

# --- CONFIGURAÇÃO BASE DO APP ---
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

# --- DESIGN SYSTEM RESPONSIVO (DESKTOP + TABLET + MOBILE) ---
CSS_APP = """
<style>
    :root {
        --bg: #08080B;
        --surface: rgba(20, 20, 27, 0.88);
        --surface-2: #1A1A22;
        --border: rgba(255,255,255,.09);
        --text: #F7F7FA;
        --muted: #9CA3AF;
        --purple: #8B5CF6;
        --purple-2: #6D28D9;
        --teal: #2DD4BF;
        --danger: #EF4444;
        --warning: #F59E0B;
        --radius: 16px;
    }

    html { scroll-behavior: smooth; }

    .stApp {
        background:
            radial-gradient(circle at 15% 5%, rgba(139,92,246,.13), transparent 28%),
            radial-gradient(circle at 90% 15%, rgba(45,212,191,.08), transparent 25%),
            linear-gradient(180deg, #08080B 0%, #0C0C11 55%, #08080B 100%) !important;
        color: var(--text) !important;
    }

    h1, h2, h3, h4, h5, h6, p,
    div[data-testid="stMarkdownContainer"] > p {
        color: var(--text) !important;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }

    label {
        color: #D4D4D8 !important;
        font-size: 11px !important;
        font-weight: 800 !important;
        text-transform: uppercase;
        letter-spacing: .7px;
    }

    .block-container {
        width: 100% !important;
        max-width: 1480px !important;
        padding: 1.25rem 2rem 4rem !important;
        margin: 0 auto !important;
    }

    /* Cards / containers */
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background: linear-gradient(180deg, rgba(25,25,34,.91), rgba(16,16,22,.94));
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px;
        box-shadow: 0 18px 55px rgba(0,0,0,.25);
        backdrop-filter: blur(12px);
    }

    /* Inputs */
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="textarea"] > div {
        background: rgba(30,30,40,.92) !important;
        border: 1px solid rgba(255,255,255,.12) !important;
        border-radius: 12px !important;
        min-height: 46px !important;
        transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }

    div[data-baseweb="input"] > div:focus-within,
    div[data-baseweb="select"] > div:focus-within,
    div[data-baseweb="textarea"] > div:focus-within {
        border-color: rgba(139,92,246,.9) !important;
        box-shadow: 0 0 0 3px rgba(139,92,246,.14) !important;
    }

    input, select, textarea {
        color: #FAFAFA !important;
        font-size: 15px !important;
        font-weight: 650 !important;
    }

    input::placeholder, textarea::placeholder { color: #71717A !important; }

    /* Botões */
    div[data-testid="stButton"] > button,
    div[data-testid="stFormSubmitButton"] > button {
        min-height: 54px !important;
        height: auto !important;
        padding: 10px 14px !important;
        border-radius: 13px !important;
        font-size: 13px !important;
        line-height: 1.25 !important;
        white-space: normal !important;
        font-weight: 800 !important;
        letter-spacing: .15px !important;
        transition: transform .16s ease, border-color .16s ease, background .16s ease, box-shadow .16s ease !important;
    }

    div[data-testid="stButton"] > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {
        transform: translateY(-1px);
    }

    div[data-testid="stButton"] > button:active,
    div[data-testid="stFormSubmitButton"] > button:active {
        transform: scale(.985);
    }

    button[kind="secondary"] {
        background: linear-gradient(180deg, rgba(31,31,42,.96), rgba(22,22,30,.96)) !important;
        color: #F4F4F5 !important;
        border: 1px solid rgba(255,255,255,.10) !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
        width: 100% !important;
        margin-bottom: 6px !important;
    }

    button[kind="secondary"]:hover {
        border-color: rgba(139,92,246,.72) !important;
        background: linear-gradient(180deg, rgba(39,39,52,.98), rgba(28,28,38,.98)) !important;
        color: #FFFFFF !important;
        box-shadow: 0 8px 28px rgba(139,92,246,.10);
    }

    div[data-testid="stFormSubmitButton"] > button,
    button[kind="primary"] {
        background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 55%, #0F766E 135%) !important;
        color: white !important;
        border: 1px solid rgba(255,255,255,.10) !important;
        box-shadow: 0 10px 28px rgba(109,40,217,.26) !important;
        width: 100% !important;
    }

    div[data-testid="stFormSubmitButton"] > button:hover,
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #9F7AEA 0%, #7C3AED 55%, #0D9488 135%) !important;
        box-shadow: 0 14px 35px rgba(109,40,217,.33) !important;
    }

    /* Tabs */
    div[data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(18,18,24,.72);
        padding: 6px;
        border-radius: 14px;
        border: 1px solid var(--border);
        overflow-x: auto;
    }
    button[data-baseweb="tab"] {
        border-radius: 10px !important;
        min-height: 42px !important;
        padding: 0 14px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: rgba(139,92,246,.16) !important;
    }

    /* Expanders / dataframes */
    div[data-testid="stExpander"] {
        border: 1px solid var(--border) !important;
        border-radius: 14px !important;
        overflow: hidden;
        background: rgba(17,17,23,.65) !important;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
    }

    /* Hero do login */
    .login-hero {
        width: min(680px, 100%);
        margin: 5vh auto 18px;
        text-align: center;
        padding: 18px 12px 6px;
    }
    .login-logo {
        width: 72px;
        height: 72px;
        margin: 0 auto 18px;
        border-radius: 22px;
        display: grid;
        place-items: center;
        font-size: 34px;
        background: linear-gradient(145deg, rgba(139,92,246,.24), rgba(45,212,191,.12));
        border: 1px solid rgba(255,255,255,.11);
        box-shadow: 0 18px 55px rgba(109,40,217,.24), inset 0 1px 0 rgba(255,255,255,.08);
    }
    .login-title {
        margin: 0;
        font-size: clamp(28px, 4vw, 42px);
        line-height: 1.02;
        font-weight: 900;
        letter-spacing: -1.2px;
        background: linear-gradient(90deg, #FFFFFF, #C4B5FD 55%, #5EEAD4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .login-subtitle {
        margin: 10px auto 0;
        max-width: 520px;
        color: #A1A1AA !important;
        font-size: 14px;
    }
    .login-pill {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        margin-top: 14px;
        padding: 7px 11px;
        border-radius: 999px;
        border: 1px solid rgba(45,212,191,.18);
        background: rgba(45,212,191,.07);
        color: #99F6E4;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        text-transform: uppercase;
    }

    /* Cabeçalho do usuário */
    .user-shell {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 16px 18px;
        margin: 2px 0 18px;
        border-radius: 18px;
        border: 1px solid rgba(255,255,255,.09);
        background: linear-gradient(135deg, rgba(139,92,246,.12), rgba(18,18,25,.82) 44%, rgba(45,212,191,.07));
        box-shadow: 0 16px 48px rgba(0,0,0,.22);
    }
    .user-left { display:flex; align-items:center; gap:13px; min-width:0; }
    .user-avatar {
        width: 46px; height: 46px; min-width: 46px;
        display:grid; place-items:center;
        border-radius:14px;
        font-size:20px;
        background: rgba(139,92,246,.15);
        border: 1px solid rgba(139,92,246,.28);
    }
    .user-kicker { color:#A1A1AA; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.65px; }
    .user-name { color:#FAFAFA; font-size:18px; line-height:1.15; font-weight:900; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .user-meta { color:#5EEAD4; font-size:12px; font-weight:750; margin-top:3px; }
    .live-badge {
        flex: 0 0 auto;
        padding: 8px 10px;
        border-radius: 999px;
        color:#C4B5FD;
        border:1px solid rgba(139,92,246,.24);
        background:rgba(139,92,246,.08);
        font-size:10px;
        font-weight:900;
        text-transform:uppercase;
        letter-spacing:.6px;
    }

    .menu-section-title {
        color:#E4E4E7;
        font-size:12px;
        font-weight:900;
        text-transform:uppercase;
        letter-spacing:.85px;
        margin: 4px 0 10px;
    }

    /* Toasts */
    div[data-testid="stToast"] {
        background: rgba(69,10,10,.97) !important;
        border: 1px solid rgba(239,68,68,.75) !important;
        border-radius: 14px !important;
        padding: 15px !important;
        box-shadow: 0 18px 48px rgba(0,0,0,.35);
    }
    div[data-testid="stToast"] div[data-testid="stMarkdownContainer"] > p {
        color: #FFB4B4 !important;
        font-weight: 850 !important;
        font-size: 15px !important;
    }

    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(239,68,68,.55); }
        70% { box-shadow: 0 0 0 11px rgba(239,68,68,0); }
        100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
    }
    .alerta-pisca {
        animation: pulse-red 2s infinite;
        background: rgba(69,10,10,.84) !important;
        border: 1px solid rgba(239,68,68,.75) !important;
        padding: 15px;
        border-radius: 14px;
        margin-bottom: 20px;
    }

    header { visibility: hidden; }
    footer { visibility: hidden; }

    /* TABLET */
    @media (max-width: 1100px) {
        .block-container { padding: 1rem 1rem 3.5rem !important; }
        div[data-testid="stHorizontalBlock"] { gap: .65rem !important; }
    }

    /* CELULAR: interface mais próxima de app nativo */
    @media (max-width: 768px) {
        .stApp {
            background:
                radial-gradient(circle at 50% -10%, rgba(139,92,246,.18), transparent 33%),
                linear-gradient(180deg, #08080B 0%, #0A0A0F 100%) !important;
        }
        .block-container {
            max-width: 100% !important;
            padding: .55rem .65rem 2.5rem !important;
        }

        /* Faz colunas virarem blocos empilhados quando não couberem. */
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: .55rem !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width: min(100%, 220px) !important;
            flex: 1 1 100% !important;
            width: 100% !important;
        }

        div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
            border-radius: 15px;
            padding: 12px;
        }

        div[data-testid="stButton"] > button,
        div[data-testid="stFormSubmitButton"] > button {
            min-height: 58px !important;
            border-radius: 14px !important;
            font-size: 13px !important;
            padding: 11px 12px !important;
        }

        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"] > div {
            min-height: 50px !important;
            border-radius: 13px !important;
        }
        input, select, textarea { font-size: 16px !important; } /* evita zoom automático no iPhone */

        .login-hero { margin-top: 4vh; padding-top: 8px; }
        .login-logo { width:64px; height:64px; border-radius:20px; font-size:30px; margin-bottom:15px; }
        .login-title { font-size: 30px; }
        .login-subtitle { font-size: 13px; padding: 0 10px; }

        .user-shell { padding: 13px; border-radius: 16px; margin-bottom: 13px; }
        .user-avatar { width:42px; height:42px; min-width:42px; border-radius:13px; }
        .user-name { font-size: 16px; }
        .user-meta { font-size: 11px; }
        .live-badge { display:none; }

        div[data-baseweb="tab-list"] { border-radius:12px; padding:4px; }
        button[data-baseweb="tab"] { min-width:max-content; font-size:12px !important; }

        /* Mais espaço para toque em checkbox/radio/toggle */
        div[role="radiogroup"] { gap: 8px !important; }
    }

    /* DESKTOP GRANDE */
    @media (min-width: 1280px) {
        .block-container { padding-top: 1rem !important; }
        div[data-testid="stButton"] > button { min-height: 56px !important; }
    }

    /* =========================================================
       TOP NAV + HOME DASHBOARD
       ========================================================= */
    .app-topbar {
        position: sticky; top: .55rem; z-index: 999;
        display: flex; align-items: center; gap: 18px;
        width: 100%; min-height: 68px; padding: 10px 12px 10px 14px;
        margin: 0 0 22px 0; border: 1px solid rgba(255,255,255,.10);
        border-radius: 18px; background: rgba(20,20,28,.92);
        backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
        box-shadow: 0 16px 45px rgba(0,0,0,.24);
    }
    .app-brand {display:flex;align-items:center;gap:10px;flex:0 0 auto;min-width:max-content;text-decoration:none!important;}
    .app-brand-icon {width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#8B5CF6,#0F766E);color:#fff;font-size:18px;box-shadow:0 8px 22px rgba(109,40,217,.28);}
    .app-brand-copy {line-height:1.05;}
    .app-brand-name {color:#FAFAFA;font-size:13px;font-weight:950;letter-spacing:.4px;}
    .app-brand-sub {color:#8B8B98;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;margin-top:4px;}
    .app-nav-scroll {display:flex;align-items:center;gap:4px;flex:1 1 auto;min-width:0;overflow-x:auto;scrollbar-width:none;padding:2px;}
    .app-nav-scroll::-webkit-scrollbar {display:none;}
    .app-nav-link {display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 13px;border-radius:11px;color:#AFAFBA!important;text-decoration:none!important;font-size:12px;font-weight:850;white-space:nowrap;border:1px solid transparent;transition:.18s ease;}
    .app-nav-link:hover {color:#FFFFFF!important;background:rgba(255,255,255,.055);}
    .app-nav-link.active {color:#FFFFFF!important;background:linear-gradient(135deg,rgba(139,92,246,.22),rgba(45,212,191,.10));border-color:rgba(139,92,246,.28);box-shadow:inset 0 1px 0 rgba(255,255,255,.04);}
    .app-top-user {display:flex;align-items:center;gap:8px;flex:0 0 auto;padding:6px 9px 6px 7px;border-radius:12px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.07);}
    .app-top-avatar {width:30px;height:30px;border-radius:10px;display:grid;place-items:center;background:rgba(139,92,246,.17);color:#C4B5FD;font-size:13px;font-weight:900;}
    .app-top-user-name {color:#F4F4F5;font-size:11px;font-weight:850;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .app-top-user-meta {color:#71717A;font-size:9px;font-weight:700;margin-top:1px;}
    .machine-search {flex:0 1 190px;min-width:150px;margin:0;}
    .machine-search-wrap {height:40px;display:flex;align-items:center;gap:7px;padding:0 8px 0 11px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08);border-radius:11px;}
    .machine-search-wrap:focus-within {border-color:rgba(139,92,246,.6);box-shadow:0 0 0 3px rgba(139,92,246,.10);}
    .machine-search-wrap input {width:100%;min-width:0;height:34px;padding:0;border:0;outline:0;background:transparent!important;color:#F4F4F5!important;font-size:12px!important;font-weight:700!important;}
    .machine-search-wrap input::placeholder {color:#73737E!important;}
    .machine-search-wrap button {width:28px;height:28px;min-width:28px;border:0;border-radius:8px;cursor:pointer;background:rgba(139,92,246,.16);color:#C4B5FD;font-weight:900;}
    .dash-welcome {display:flex;align-items:end;justify-content:space-between;gap:18px;margin:4px 0 16px;}
    .dash-eyebrow {color:#8B8B98;font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.9px;}
    .dash-title {color:#F7F7FA!important;font-size:clamp(25px,3vw,38px);font-weight:950;letter-spacing:-1px;margin:3px 0 0;line-height:1.05;}
    .dash-subtitle {color:#92929D!important;font-size:13px;margin-top:8px;}
    .dash-date {color:#B8B8C2;font-size:11px;font-weight:800;white-space:nowrap;padding-bottom:4px;}
    .kpi-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 16px;}
    .kpi-card {position:relative;overflow:hidden;min-height:132px;padding:17px;border-radius:17px;background:linear-gradient(180deg,rgba(28,28,38,.96),rgba(19,19,26,.96));border:1px solid rgba(255,255,255,.085);box-shadow:0 14px 36px rgba(0,0,0,.18);}
    .kpi-card::after {content:'';position:absolute;width:120px;height:120px;border-radius:999px;right:-55px;top:-60px;opacity:.13;background:var(--kpi-color,#8B5CF6);filter:blur(2px);}
    .kpi-head {display:flex;align-items:center;justify-content:space-between;gap:8px;}
    .kpi-label {color:#A8A8B2;font-size:10px;font-weight:900;letter-spacing:.75px;text-transform:uppercase;}
    .kpi-icon {width:31px;height:31px;display:grid;place-items:center;border-radius:10px;background:rgba(139,92,246,.10);color:var(--kpi-color);font-size:14px;}
    .kpi-value {color:#FFFFFF;font-size:34px;font-weight:950;letter-spacing:-1.3px;line-height:1;margin-top:17px;}
    .kpi-foot {display:flex;align-items:center;gap:6px;color:#777782;font-size:10px;font-weight:750;margin-top:8px;}
    .kpi-dot {width:6px;height:6px;border-radius:99px;background:var(--kpi-color);box-shadow:0 0 12px var(--kpi-color);}
    .dashboard-grid {display:grid;grid-template-columns:minmax(0,1.1fr) minmax(360px,.9fr);gap:14px;margin-top:14px;align-items:start;}
    .dash-panel {background:linear-gradient(180deg,rgba(26,26,35,.94),rgba(18,18,25,.96));border:1px solid rgba(255,255,255,.085);border-radius:18px;padding:17px;box-shadow:0 14px 38px rgba(0,0,0,.17);height:auto;align-self:start;}
    .sector-panel {padding:13px 15px;}
    .sector-panel .sector-row {margin-top:11px;}
    .sector-panel .sector-mini {margin-top:5px;}
    .dash-panel-title {color:#F4F4F5;font-size:13px;font-weight:900;}
    .dash-panel-sub {color:#777782;font-size:10px;font-weight:700;margin-top:4px;}
    .sector-row {display:grid;grid-template-columns:82px 1fr 48px;align-items:center;gap:10px;margin-top:17px;}
    .sector-name {color:#CFCFD6;font-size:11px;font-weight:900;}
    .sector-track {height:9px;background:rgba(255,255,255,.055);border-radius:999px;overflow:hidden;}
    .sector-fill {height:100%;border-radius:999px;background:linear-gradient(90deg,#8B5CF6,#2DD4BF);}
    .sector-pct {color:#AFAFBA;font-size:10px;font-weight:850;text-align:right;}
    .sector-mini {display:flex;gap:12px;flex-wrap:wrap;margin:8px 0 0 92px;}
    .sector-mini span {color:#777782;font-size:9px;font-weight:750;}
    .sector-mini b {color:#CFCFD6;}
    .attention-list {display:flex;flex-direction:column;gap:8px;margin-top:13px;}
    .attention-item {display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:10px;padding:9px 10px;border-radius:12px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.055);}
    .attention-ico {width:34px;height:34px;display:grid;place-items:center;border-radius:10px;background:rgba(245,158,11,.10);}
    .attention-machine {color:#E8E8EC;font-size:11px;font-weight:900;}
    .attention-status {color:#7F7F8A;font-size:9px;font-weight:700;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .attention-sector {color:#A78BFA;font-size:9px;font-weight:900;padding:4px 6px;border-radius:7px;background:rgba(139,92,246,.10);}
    .attention-empty {color:#8A8A95;font-size:11px;padding:18px 0 4px;text-align:center;}
    .quick-title {color:#E4E4E7;font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.8px;margin:22px 0 10px;}
    @media (max-width:1180px) {
        .app-topbar {gap:10px;} .app-brand-sub,.app-top-user-meta {display:none;}
        .machine-search {flex-basis:155px;min-width:130px;} .app-nav-link {padding:0 10px;}
        .kpi-grid {grid-template-columns:repeat(2,minmax(0,1fr));} .dashboard-grid {grid-template-columns:1fr;}
    }
    @media (max-width:768px) {
        .app-topbar {position:relative;top:0;display:grid;grid-template-columns:1fr auto;gap:9px;padding:10px;margin-bottom:15px;border-radius:15px;}
        .app-brand {grid-column:1;} .app-top-user {grid-column:2;padding:5px;} .app-top-user-copy {display:none;}
        .app-nav-scroll {grid-column:1/-1;grid-row:2;width:100%;order:3;} .app-nav-link {min-height:38px;padding:0 11px;font-size:11px;}
        .machine-search {grid-column:1/-1;grid-row:3;width:100%;min-width:0;} .machine-search-wrap {height:42px;}
        .dash-welcome {align-items:flex-start;margin-top:2px;} .dash-date {display:none;} .dash-title {font-size:27px;} .dash-subtitle {font-size:12px;}
        .kpi-grid {grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;} .kpi-card {min-height:116px;padding:13px;border-radius:15px;}
        .kpi-value {font-size:29px;margin-top:14px;} .kpi-label {font-size:9px;} .kpi-foot {font-size:9px;}
        .dashboard-grid {gap:10px;} .dash-panel {padding:14px;border-radius:15px;}
        .sector-row {grid-template-columns:62px 1fr 42px;gap:8px;} .sector-mini {margin-left:70px;gap:8px;}
    }
    @media (max-width:430px) {
        .app-brand-name {font-size:12px;} .app-brand-icon {width:34px;height:34px;border-radius:10px;}
        .kpi-grid {grid-template-columns:1fr 1fr;} .kpi-card {min-height:108px;} .kpi-icon {width:27px;height:27px;border-radius:8px;}
        .kpi-value {font-size:27px;} .sector-mini {margin-left:0;padding-left:0;}
        .attention-item {grid-template-columns:32px minmax(0,1fr);} .attention-sector {display:none;}
    }

    /* =========================================================
       NAVEGAÇÃO NATIVA (SEM RELOAD / SEM PERDER SESSION_STATE)
       ========================================================= */
    .st-key-topbar_native {
        position: sticky; top: .55rem; z-index: 999;
        padding: 10px 12px 8px; margin: 0 0 8px 0;
        border: 1px solid rgba(255,255,255,.10); border-radius: 18px;
        background: rgba(20,20,28,.94);
        backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
        box-shadow: 0 16px 45px rgba(0,0,0,.24);
    }
    .native-brand {display:flex;align-items:center;gap:10px;min-height:42px;}
    .native-brand-icon {width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#8B5CF6,#0F766E);color:#fff;font-size:18px;box-shadow:0 8px 22px rgba(109,40,217,.28);}
    .native-brand-name {color:#FAFAFA;font-size:13px;font-weight:950;letter-spacing:.4px;line-height:1.05;}
    .native-brand-sub {color:#8B8B98;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;margin-top:4px;}
    .native-user {display:flex;align-items:center;justify-content:flex-end;gap:8px;min-height:42px;}
    .native-user-avatar {width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:rgba(139,92,246,.17);color:#C4B5FD;font-size:13px;font-weight:900;}
    .native-user-name {color:#F4F4F5;font-size:11px;font-weight:850;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right;}
    .native-user-meta {color:#71717A;font-size:9px;font-weight:700;margin-top:1px;text-align:right;}
    .st-key-topbar_native div[data-testid="stTextInput"] {margin-top:2px;}
    .st-key-topbar_native div[data-testid="stTextInput"] > div > div {
        min-height:42px !important; border-radius:12px !important;
        background:rgba(255,255,255,.055)!important; border-color:rgba(255,255,255,.09)!important;
    }
    .st-key-topbar_native div[data-testid="stTextInput"] input {font-size:12px!important;color:#F4F4F5!important;}
    .st-key-topbar_nav_native {margin: 0 0 18px 0; overflow-x:auto; scrollbar-width:none;}
    .st-key-topbar_nav_native::-webkit-scrollbar {display:none;}
    .st-key-topbar_nav_native div[data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;gap:.42rem!important;min-width:max-content;}
    .st-key-topbar_nav_native div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {flex:0 0 auto!important;width:auto!important;min-width:108px!important;}
    .st-key-topbar_nav_native div[data-testid="stButton"] > button {
        min-height:40px!important;height:40px!important;padding:0 13px!important;border-radius:11px!important;
        white-space:nowrap!important;font-size:11px!important;margin:0!important;
    }

    /* Preparações - Home */
    .prep-kpi-breakdown {display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:12px;}
    .prep-kpi-mini {padding:7px 8px;border-radius:10px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.055);}
    .prep-kpi-mini-label {color:#858590;font-size:8px;font-weight:850;text-transform:uppercase;letter-spacing:.45px;}
    .prep-kpi-mini-value {color:#F7F7FA;font-size:15px;font-weight:950;margin-top:2px;}
    .prep-kpi-mini.active {border-color:rgba(45,212,191,.14);background:rgba(45,212,191,.055);}
    .prep-kpi-mini.waiting {border-color:rgba(245,158,11,.15);background:rgba(245,158,11,.055);}
    .prep-kpi-mini.active .prep-kpi-mini-value {color:#5EEAD4;}
    .prep-kpi-mini.waiting .prep-kpi-mini-value {color:#FBBF24;}
    .prep-summary {display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;}
    .prep-chip {display:inline-flex;align-items:center;gap:6px;padding:6px 9px;border-radius:999px;font-size:9px;font-weight:850;border:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.035);color:#A8A8B2;}
    .prep-chip b {font-size:11px;color:#F4F4F5;}
    .prep-chip.active {background:rgba(45,212,191,.07);border-color:rgba(45,212,191,.16);color:#5EEAD4;}
    .prep-chip.waiting {background:rgba(245,158,11,.07);border-color:rgba(245,158,11,.17);color:#FBBF24;}
    .prep-section-title {display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:14px;margin-bottom:7px;color:#CFCFD6;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.55px;}
    .prep-section-count {display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 6px;border-radius:8px;background:rgba(255,255,255,.055);color:#F4F4F5;font-size:10px;}
    .prep-list {display:flex;flex-direction:column;gap:7px;}
    .prep-item {display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:9px;padding:9px 10px;border-radius:12px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.055);}
    .prep-item.active {border-left:3px solid rgba(45,212,191,.82);}
    .prep-item.waiting {border-left:3px solid rgba(245,158,11,.82);}
    .prep-ico {width:32px;height:32px;display:grid;place-items:center;border-radius:9px;background:rgba(139,92,246,.10);font-size:13px;}
    .prep-machine {color:#ECECF0;font-size:11px;font-weight:900;}
    .prep-status {color:#81818C;font-size:9px;font-weight:700;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .prep-meta {display:flex;align-items:center;gap:5px;margin-top:3px;color:#676772;font-size:8px;font-weight:750;}
    .prep-time {min-width:62px;text-align:right;color:#F4F4F5;font-size:11px;font-weight:950;}
    .prep-time span {display:block;color:#6F6F79;font-size:8px;font-weight:750;margin-bottom:1px;}
    .prep-empty {padding:13px 8px;color:#777782;font-size:10px;text-align:center;border:1px dashed rgba(255,255,255,.07);border-radius:11px;}
    .prep-more {color:#777782;font-size:9px;font-weight:750;text-align:center;padding-top:6px;}
    .prep-sector-block {margin-top:8px;}
    .prep-sector-head {display:flex;align-items:center;justify-content:space-between;gap:8px;margin:9px 0 6px;padding:6px 8px;border-radius:9px;background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.045);}
    .prep-sector-name {font-size:9px;font-weight:950;letter-spacing:.55px;text-transform:uppercase;color:#D4D4D8;}
    .prep-sector-name.afc {color:#5EEAD4;}
    .prep-sector-name.rtf {color:#93C5FD;}
    .prep-sector-count {min-width:22px;height:20px;padding:0 6px;display:inline-grid;place-items:center;border-radius:7px;background:rgba(255,255,255,.055);color:#F4F4F5;font-size:9px;font-weight:900;}
    /* Visão gerencial por processo */
    .mgr-intro {display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:2px 0 13px;}
    .mgr-title {color:#F7F7FA;font-size:22px;font-weight:950;letter-spacing:-.5px;}
    .mgr-sub {color:#858590;font-size:10px;font-weight:700;margin-top:4px;}
    .mgr-summary {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:0 0 14px;}
    .mgr-summary-card {padding:12px 13px;border-radius:14px;background:linear-gradient(180deg,rgba(27,27,37,.96),rgba(19,19,27,.96));border:1px solid rgba(255,255,255,.07);}
    .mgr-summary-label {color:#858590;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.5px;}
    .mgr-summary-num {color:#FFFFFF;font-size:26px;font-weight:950;line-height:1;margin-top:8px;}
    .mgr-summary-meta {color:#6F6F7A;font-size:8px;font-weight:750;margin-top:5px;}
    .mgr-process {margin-top:12px;padding:14px;border-radius:17px;background:linear-gradient(180deg,rgba(25,25,34,.95),rgba(18,18,25,.97));border:1px solid rgba(255,255,255,.075);box-shadow:0 12px 32px rgba(0,0,0,.14);}
    .mgr-process-head {display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;}
    .mgr-process-name {display:flex;align-items:center;gap:8px;color:#F1F1F4;font-size:12px;font-weight:950;}
    .mgr-process-dot {width:8px;height:8px;border-radius:99px;background:var(--mgr-color,#8B5CF6);box-shadow:0 0 14px var(--mgr-color,#8B5CF6);}
    .mgr-process-count {padding:5px 8px;border-radius:9px;color:#BDBDC7;background:rgba(255,255,255,.045);font-size:9px;font-weight:900;}
    .mgr-machine-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;}
    .mgr-machine {position:relative;overflow:hidden;min-height:112px;padding:11px;border-radius:13px;background:rgba(255,255,255,.032);border:1px solid rgba(255,255,255,.055);border-left:3px solid var(--state-color,#2DD4BF);}
    .mgr-machine-top {display:flex;align-items:center;justify-content:space-between;gap:8px;}
    .mgr-machine-name {color:#F4F4F5;font-size:11px;font-weight:950;}
    .mgr-state {max-width:64%;padding:4px 6px;border-radius:7px;background:rgba(255,255,255,.045);color:var(--state-color,#2DD4BF);font-size:7px;font-weight:950;text-transform:uppercase;letter-spacing:.25px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .mgr-machine-data {display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:11px;}
    .mgr-data-box {min-width:0;padding:7px;border-radius:9px;background:rgba(255,255,255,.028);}
    .mgr-data-box span {display:block;color:#686873;font-size:7px;font-weight:800;text-transform:uppercase;letter-spacing:.35px;}
    .mgr-data-box b {display:block;color:#DCDCE2;font-size:9px;font-weight:900;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .mgr-next {margin-top:7px;color:#7E7E89;font-size:8px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .mgr-next b {color:#F59E0B;}
    .mgr-empty {padding:18px 6px;text-align:center;color:#73737E;font-size:10px;border:1px dashed rgba(255,255,255,.07);border-radius:11px;}
    @media (max-width:1280px) {.mgr-machine-grid {grid-template-columns:repeat(3,minmax(0,1fr));}}
    @media (max-width:980px) {.mgr-summary {grid-template-columns:repeat(2,minmax(0,1fr));}.mgr-machine-grid {grid-template-columns:repeat(2,minmax(0,1fr));}}
    @media (max-width:560px) {.mgr-intro {display:block;}.mgr-summary {grid-template-columns:1fr 1fr;gap:7px}.mgr-process {padding:11px}.mgr-machine-grid {grid-template-columns:1fr}.mgr-machine {min-height:104px}.mgr-summary-num {font-size:23px;}}
    /* Desempenho mensal de setups */
    .setup-month-panel {margin-top:14px;background:linear-gradient(180deg,rgba(26,26,35,.94),rgba(18,18,25,.96));border:1px solid rgba(255,255,255,.085);border-radius:18px;padding:17px;box-shadow:0 14px 38px rgba(0,0,0,.17);}
    .setup-month-top {display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:13px;}
    .setup-month-title {color:#F4F4F5;font-size:13px;font-weight:900;}
    .setup-month-sub {color:#777782;font-size:10px;font-weight:700;margin-top:4px;}
    .setup-month-badge {flex:0 0 auto;padding:6px 9px;border-radius:10px;background:rgba(139,92,246,.09);border:1px solid rgba(139,92,246,.18);color:#C4B5FD;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.45px;}
    .setup-sector-summary {display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:10px;}
    .setup-sector-pill {display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 11px;border-radius:12px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.055);}
    .setup-sector-pill span {color:#888893;font-size:9px;font-weight:800;}
    .setup-sector-pill b {color:#E9E9ED;font-size:10px;font-weight:900;}
    .setup-month-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;}
    .setup-metric-card {position:relative;overflow:hidden;padding:13px;border-radius:14px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);min-height:118px;}
    .setup-metric-card::after {content:'';position:absolute;right:-32px;top:-34px;width:80px;height:80px;border-radius:99px;background:var(--setup-color);opacity:.10;}
    .setup-metric-head {display:flex;align-items:center;justify-content:space-between;gap:8px;color:#9B9BA6;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.45px;}
    .setup-metric-head b {color:var(--setup-color);font-size:15px;}
    .setup-metric-main {display:flex;align-items:baseline;gap:7px;margin-top:12px;}
    .setup-metric-main strong {color:#FFFFFF;font-size:27px;font-weight:950;line-height:1;}
    .setup-metric-main span {color:#74747F;font-size:8px;font-weight:750;}
    .setup-metric-average {display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:13px;padding-top:9px;border-top:1px solid rgba(255,255,255,.055);}
    .setup-metric-average span {color:#70707B;font-size:8px;font-weight:750;}
    .setup-metric-average b {color:var(--setup-color);font-size:11px;font-weight:950;white-space:nowrap;}
    @media (max-width:1180px) {.setup-month-grid {grid-template-columns:repeat(2,minmax(0,1fr));}}
    @media (max-width:520px) {.setup-month-top {display:block;} .setup-month-badge {display:inline-block;margin-top:8px;} .setup-sector-summary {grid-template-columns:1fr;} .setup-month-grid {grid-template-columns:1fr 1fr;gap:7px;} .setup-metric-card {padding:11px;min-height:112px;} .setup-metric-main strong {font-size:24px;} .setup-metric-average {display:block;} .setup-metric-average b {display:block;margin-top:3px;}}

    @media (max-width:768px) {
        .st-key-topbar_native {position:relative;top:0;padding:9px;border-radius:15px;}
        .st-key-topbar_native div[data-testid="stHorizontalBlock"] {gap:.5rem!important;}
        .st-key-topbar_native div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {min-width:min(100%,220px)!important;}
        .native-user {justify-content:flex-start;}
        .native-user-name,.native-user-meta {text-align:left;}
        .st-key-topbar_nav_native {margin-bottom:14px;}
        .st-key-topbar_nav_native div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {min-width:105px!important;flex:0 0 105px!important;}
        .st-key-topbar_nav_native div[data-testid="stButton"] > button {min-height:40px!important;height:40px!important;font-size:10px!important;padding:0 9px!important;}
        .prep-item {grid-template-columns:31px minmax(0,1fr) auto;padding:8px;}
        .prep-time {min-width:55px;font-size:10px;}
    }

</style>
"""
st.markdown(CSS_APP, unsafe_allow_html=True)


# --- AJUSTE V8: mantém tema escuro; somente campos digitáveis ficam claros com texto preto ---
CSS_INPUTS_V8 = """
<style>
    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div,
    div[data-baseweb="select"] > div {
        background: #FFFFFF !important;
        border-color: #D4D4D8 !important;
        box-shadow: none !important;
    }

    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea,
    div[data-baseweb="select"] input,
    input[type="text"], input[type="password"], input[type="number"],
    input[type="search"], input[type="email"], input[type="tel"],
    input[type="date"], input[type="time"], textarea {
        color: #111111 !important;
        caret-color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    div[data-baseweb="select"] [role="combobox"],
    div[data-baseweb="select"] [role="combobox"] * {
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    input::placeholder, textarea::placeholder {
        color: #71717A !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #71717A !important;
    }

    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus {
        -webkit-text-fill-color: #111111 !important;
        box-shadow: 0 0 0 1000px #FFFFFF inset !important;
        transition: background-color 9999s ease-out 0s;
    }

    .classic-user-card {
        background: #18181B;
        padding: 14px 16px;
        border-radius: 12px;
        border: 1px solid #27272A;
        border-left: 4px solid #14B8A6;
        box-shadow: 0 8px 24px rgba(0,0,0,.20);
        margin-bottom: 15px;
    }
    .classic-user-label { margin:0 !important; font-size:11px !important; color:#A1A1AA !important; text-transform:uppercase; letter-spacing:.55px; font-weight:800; }
    .classic-user-name { margin:4px 0 0 !important; font-size:17px !important; color:#F4F4F5 !important; font-weight:900; }
    .classic-user-meta { margin:3px 0 0 !important; font-size:12px !important; color:#2DD4BF !important; font-weight:800; }

    .dashboard-left-stack {
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-width: 0;
    }
    .dashboard-left-stack .setup-month-panel {
        margin-top: 0 !important;
        padding: 15px;
    }
    .dashboard-left-stack .setup-month-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .dashboard-left-stack .setup-metric-card {
        min-height: 112px;
    }

    @media (max-width: 520px) {
        .dashboard-left-stack .setup-month-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        }
        .dashboard-left-stack .setup-month-panel { padding: 12px; }
    }

    /* V9: médias sempre em grade 2x2 abaixo de Produção por setor */
    .setup-month-panel-compact { margin-top: 14px !important; padding: 14px !important; }
    .setup-month-grid-2x2 { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
    .setup-month-panel-compact .setup-metric-card { min-height: 108px; padding: 11px; }
    .setup-month-panel-compact .setup-metric-main strong { font-size: 24px; }
    .setup-month-panel-compact .setup-metric-average { margin-top: 10px; padding-top: 8px; }

    @media (max-width: 700px) {
        .setup-month-panel-compact { padding: 12px !important; }
        .setup-month-grid-2x2 { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 7px !important; }
    }
</style>
"""
st.markdown(CSS_INPUTS_V8, unsafe_allow_html=True)

# --- AJUSTE V9.2: contraste garantido nos campos digitáveis em celular ---
CSS_MOBILE_INPUT_FIX = """
<style>
@media (max-width: 768px) {
    div[data-baseweb="input"],
    div[data-baseweb="textarea"],
    div[data-baseweb="select"] {
        color-scheme: light !important;
    }

    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div,
    div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        color: #111111 !important;
        border-color: #D4D4D8 !important;
    }

    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea,
    div[data-baseweb="select"] input,
    input[type="text"],
    input[type="password"],
    input[type="number"],
    input[type="search"],
    input[type="email"],
    input[type="tel"],
    input[type="date"],
    input[type="time"],
    textarea {
        background-color: #FFFFFF !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
        caret-color: #000000 !important;
        opacity: 1 !important;
        text-shadow: none !important;
        font-size: 16px !important;
    }

    div[data-baseweb="input"] input:focus,
    div[data-baseweb="textarea"] textarea:focus,
    input:focus, textarea:focus {
        background-color: #FFFFFF !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
        caret-color: #000000 !important;
    }

    input::placeholder, textarea::placeholder {
        color: #71717A !important;
        -webkit-text-fill-color: #71717A !important;
        opacity: 1 !important;
    }

    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus,
    textarea:-webkit-autofill {
        -webkit-text-fill-color: #111111 !important;
        caret-color: #000000 !important;
        -webkit-box-shadow: 0 0 0 1000px #FFFFFF inset !important;
        box-shadow: 0 0 0 1000px #FFFFFF inset !important;
    }

    input::selection, textarea::selection {
        background: #C4B5FD !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }
}
</style>
"""
st.markdown(CSS_MOBILE_INPUT_FIX, unsafe_allow_html=True)



# --- GERENCIADOR DE COOKIES E ARQUIVOS ---
# IMPORTANTE: CookieManager é um componente do navegador. Na primeira renderização
# ele pode devolver {} e, assim que o navegador responde, o próprio componente
# provoca um rerun. Usamos apenas UMA instância/getAll para evitar corrida e flicker.
cookie_manager = stx.CookieManager(key="cookie_manager_principal")
try:
    cookies_salvos = cookie_manager.cookies or {}
except Exception:
    cookies_salvos = {}

COOKIE_LOGIN = "relatorio_afiacao_auto_login_v2"

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))

def gerar_token_login(nome, turno, setor, perfil, dias=365):
    payload = {
        "nome": str(nome),
        "turno": str(turno),
        "setor": str(setor),
        "perfil": str(perfil),
        "exp": int(time.time()) + int(dias * 86400),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assinatura = hmac.new(LOGIN_COOKIE_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(assinatura)}"

def validar_token_login(token):
    try:
        parte_payload, parte_assinatura = str(token).split(".", 1)
        raw = _b64url_decode(parte_payload)
        assinatura_recebida = _b64url_decode(parte_assinatura)
        assinatura_esperada = hmac.new(LOGIN_COOKIE_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
            return None
        payload = json.loads(raw.decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        campos = ["nome", "turno", "setor", "perfil"]
        if not all(payload.get(c) for c in campos):
            return None
        return payload
    except Exception:
        return None

ARQUIVO_DADOS = "banco_operacao.csv"
ARQUIVO_EQUIPE = "banco_equipe.csv"
ARQUIVO_HISTORICO = "historico_relatorios.csv"
ARQUIVO_HISTORICO_EVENTOS = "historico_eventos.csv"
ARQUIVO_ARMARIOS = "banco_armarios.csv"
ARQUIVO_ALERTAS = "alertas_preset.csv"
ARQUIVO_CNC = "banco_cnc.csv"
ARQUIVO_FECHAMENTO = "ultimo_fechamento.csv"
ARQUIVO_REBOLOS = "rebolos.xlsx"


# --- CAMADA DE COMPATIBILIDADE ---
# O código original continua usando read_csv/to_csv/exists/remove. Estes wrappers
# redirecionam somente os antigos CSVs para o Turso e deixam o Excel intacto.
TABELAS_TURSO = {
    ARQUIVO_DADOS, ARQUIVO_EQUIPE, ARQUIVO_HISTORICO,
    ARQUIVO_HISTORICO_EVENTOS, ARQUIVO_ARMARIOS, ARQUIVO_ALERTAS,
    ARQUIVO_CNC, ARQUIVO_FECHAMENTO, "historico_devolucoes.csv"
}

# Referências estáveis às implementações reais restauradas no início do arquivo.
# Nunca capture pd.read_csv/os.path.exists diretamente neste ponto, pois eles
# podem já ter sido substituídos em uma execução anterior do Streamlit.
_original_pd_read_csv = _BASE_PANDAS_READ_CSV
_original_df_to_csv = _BASE_PANDAS_NDFRAME.to_csv
_original_exists = _BASE_GENERICPATH.exists
_original_remove = os.unlink


def _nome_tabela_caminho(path):
    try:
        nome = os.fspath(path)
        return nome if nome in TABELAS_TURSO else None
    except Exception:
        return None


def _read_csv_persistente(filepath, *args, **kwargs):
    tabela = _nome_tabela_caminho(filepath)
    if tabela:
        colunas = kwargs.pop("names", None) or []
        return carregar_tabela(tabela, colunas_padrao=colunas, **kwargs)
    return _original_pd_read_csv(filepath, *args, **kwargs)


def _to_csv_persistente(self, path_or_buf=None, *args, **kwargs):
    tabela = _nome_tabela_caminho(path_or_buf) if path_or_buf is not None else None
    if tabela:
        salvar_tabela(self, tabela, modo="replace")
        return None
    return _original_df_to_csv(self, path_or_buf, *args, **kwargs)


def _exists_persistente(path):
    tabela = _nome_tabela_caminho(path)
    if tabela:
        return tabela_existe(tabela)
    return _original_exists(path)


def _remove_persistente(path, *args, **kwargs):
    tabela = _nome_tabela_caminho(path)
    if tabela:
        remover_tabela(tabela)
        return
    return _original_remove(path, *args, **kwargs)


pd.read_csv = _read_csv_persistente
pd.DataFrame.to_csv = _to_csv_persistente
os.path.exists = _exists_persistente
os.remove = _remove_persistente

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

def get_turno_logico(dt=None):
    if dt is None: dt = datetime.now(FUSO_BR)
    t = dt.time()
    d = dt.date()
    if dtime(6, 20) <= t < dtime(14, 20): return d.strftime("%d/%m/%Y"), "1° TURNO"
    elif dtime(14, 20) <= t < dtime(22, 20): return d.strftime("%d/%m/%Y"), "2° TURNO"
    else:
        if t < dtime(6, 20): d -= timedelta(days=1)
        return d.strftime("%d/%m/%Y"), "3° TURNO"

def obter_item_rodando_atual(maq_full):
    try:
        df = _carregar_ultimos_apontamentos()
        row = df[df['Maquina'] == maq_full]
        if not row.empty:
            st_hist = str(row.iloc[-1]['Status'])
            for marcador in ["[Item:", "[Item Atual:", "[Novo Item:"]:
                if marcador in st_hist:
                    return st_hist.split(marcador)[1].split("]")[0].strip()
    except Exception:
        pass
    try:
        tabela = _quote_identifier(globals().get("ARQUIVO_DADOS", "banco_operacao.csv"))
        result = turso_request(
            f'''SELECT "Status" FROM {tabela}
                WHERE "Maquina"=?
                  AND ("Status" LIKE '%[Item:%' OR "Status" LIKE '%[Item Atual:%' OR "Status" LIKE '%[Novo Item:%')
                ORDER BY rowid DESC LIMIT 1''', [maq_full], True)
        rows = result.get("rows", [])
        if rows:
            st_hist = str(_turso_decode(rows[0][0]))
            for marcador in ["[Item:", "[Item Atual:", "[Novo Item:"]:
                if marcador in st_hist:
                    return st_hist.split(marcador)[1].split("]")[0].strip()
    except Exception:
        pass
    return "-"

def processar_padrao(df_all, maquinas, prefixo_setor):
    linhas = []
    for maq in maquinas:
        if not maq.startswith(prefixo_setor): continue
        df_maq = df_all[df_all['Maquina'] == maq]
        ciclo_ativo, status_limpo, hora_prep, preparador = False, "", "", ""
        for _, row in df_maq.iterrows():
            st_val, h_val = str(row['Status']), str(row['Hora'])
            st_upper = st_val.strip().upper()
            if "ENERGIA RESTAURADA" in st_upper: continue
            
            prep_atual = ""
            if "[Prep:" in st_val: prep_atual = st_val.split("[Prep:")[1].split("]")[0].strip()
            elif "[Prep. Sugerido:" in st_val: prep_atual = st_val.split("[Prep. Sugerido:")[1].split("]")[0].strip()
            elif "[PREP:" in st_upper: prep_atual = st_upper.split("[PREP:")[1].split("]")[0].strip()
            if prep_atual: preparador = prep_atual

            is_setup_wait = st_upper.startswith("PREPARAÇÃO") or st_upper.startswith("PREPARACAO") or st_upper.startswith("SEQUÊNCIA") or st_upper.startswith("SEQUENCIA") or st_upper.startswith("AGUARDANDO")
            is_preparando = st_upper.startswith("PREPARANDO")
            is_conclusao = st_upper.startswith("PRODUZINDO") or st_upper.startswith("PARADA") or st_upper.startswith("MANUTENÇÃO")

            if is_setup_wait:
                if not ciclo_ativo:
                    ciclo_ativo, hora_prep = True, h_val
                    s_limpo = st_val.split("[")[0].strip().upper().replace("PREPARAÇÃO - ", "")
                    status_limpo = s_limpo if s_limpo else "SETUP"
                    
                if "[AGENDADO:" in st_upper:
                    try: hora_prep = st_upper.split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "AGENDADA PARA" in st_upper:
                    try: hora_prep = st_upper.split("AGENDADA PARA")[1].strip()
                    except: pass
                    
            elif is_preparando:
                if not ciclo_ativo: ciclo_ativo, hora_prep = True, h_val
                if "[AGENDADO:" in st_upper:
                    try: hora_prep = st_upper.split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "AGENDADA PARA" in st_upper:
                    try: hora_prep = st_upper.split("AGENDADA PARA")[1].strip()
                    except: pass
                status_limpo = "PREPARANDO"
                
            elif is_conclusao and ciclo_ativo:
                if "QUEDA DE ENERGIA" in st_upper: continue
                num_maq, str_prep = maq.replace(f"{prefixo_setor} ", ""), f" - {preparador}" if preparador else ""
                
                if st_upper.startswith("PRODUZINDO"):
                    status_final = "MÁQUINA LIBERADA"
                    if "[Obs:" in st_val:
                        try: str_prep += f" (Obs: {st_val.split('[Obs:')[1].split(']')[0].strip()})"
                        except: pass
                elif st_upper.startswith("MANUTENÇÃO"): status_final = "SETUP INTERROMPIDO (MANUTENÇÃO)"
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
        st_final_up = str(st_final).strip().upper()
        
        is_finished = st_final_up.startswith("PRODUZINDO")
        is_interrompido = st_final_up.startswith("PARADA") or st_final_up.startswith("MANUTENÇÃO")
        
        if h_inicio is None and h_fim is not None:
            h_inicio = h_fim 
            p1 = "Apontamento Direto"
            
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
            st_val, h_val = str(h_row['Status']), str(h_row['Hora'])
            st_upper = st_val.strip().upper()
            if "ENERGIA RESTAURADA" in st_upper: continue
            
            is_setup_wait = st_upper.startswith("PREPARAÇÃO") or st_upper.startswith("PREPARACAO") or st_upper.startswith("SEQUÊNCIA") or st_upper.startswith("SEQUENCIA") or st_upper.startswith("AGUARDANDO")
            is_preparando = st_upper.startswith("PREPARANDO")
            is_conclusao = st_upper.startswith("PRODUZINDO") or st_upper.startswith("PARADA") or st_upper.startswith("MANUTENÇÃO")
            
            if is_setup_wait:
                if not ciclo_ativo:
                    ciclo_ativo = True
                    hora_agenda_orig = h_val
                    adiamentos = []
                    hora_inicio, hora_assumido, hora_fim, prep_1, prep_2 = None, None, None, None, None
                    
                if "AGENDADA PARA" in st_upper:
                    try: 
                        h_novo = st_upper.split("AGENDADA PARA")[1].strip()
                        if not hora_agenda_orig: hora_agenda_orig = h_novo
                        elif h_novo != hora_agenda_orig and h_novo not in adiamentos: adiamentos.append(h_novo)
                    except: pass
                elif "[AGENDADO:" in st_upper:
                    try: 
                        h_novo = st_upper.split("[AGENDADO:")[1].split("]")[0].strip()
                        if not hora_agenda_orig: hora_agenda_orig = h_novo
                        elif h_novo != hora_agenda_orig and h_novo not in adiamentos: adiamentos.append(h_novo)
                    except: pass
                    
            elif is_preparando:
                ciclo_ativo = True
                if not hora_agenda_orig: hora_agenda_orig = h_val
                if "[ASSUMIDO]" in st_upper:
                    hora_assumido = h_val
                    try: prep_2 = st_upper.split("[PREP:")[1].split("]")[0].strip()
                    except: pass
                else:
                    if hora_inicio is None: hora_inicio = h_val
                    try: prep_1 = st_upper.split("[PREP:")[1].split("]")[0].strip()
                    except: pass
                    
            elif is_conclusao and ciclo_ativo:
                if "QUEDA DE ENERGIA" in st_upper: continue
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
            st_upper = st_val.upper()
            if "ENERGIA RESTAURADA" in st_upper or "QUEDA DE ENERGIA" in st_upper: continue
            
            is_target = st_upper.startswith(palavra_chave.upper())
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
    setup_mask = df_completo['Status'].str.match(r'^(?i)(PREPARAÇÃO|PREPARACAO|SEQUÊNCIA|SEQUENCIA|AGUARDANDO|PREPARANDO)') if not df_completo.empty else pd.Series(dtype=bool)
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
    # Histórico é append-only: não baixa e regrava tudo a cada fechamento.
    salvar_tabela(novo_hist, ARQUIVO_HISTORICO, modo="append")
    
    if not df_completo.empty:
        df_eventos = df_completo.copy()
        df_eventos['Data_Registro'] = data_alvo
        df_eventos['Turno_Registro'] = turno_alvo
        # Eventos também são append-only.
        salvar_tabela(df_eventos, ARQUIVO_HISTORICO_EVENTOS, modo="append")
    
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
                df_recorte = last_row
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

def verificar_virada_turno():
    df = _carregar_ultimos_apontamentos().copy()
    if df.empty:
        return
    turno_real = turno_atual_horario()
    hora_corte = "06:20" if turno_real == "1° TURNO" else ("14:20" if turno_real == "2° TURNO" else "22:20")
    novas_linhas = []
    for _, ultimo_registro in df.iterrows():
        maq = ultimo_registro['Maquina']
        st_atual = str(ultimo_registro['Status'])
        st_upper = st_atual.upper()
        hora_registro = str(ultimo_registro['Hora'])
        
        is_setup = st_upper.startswith("PREPARAÇÃO") or st_upper.startswith("PREPARACAO") or st_upper.startswith("PREPARANDO") or st_upper.startswith("SEQUÊNCIA") or st_upper.startswith("SEQUENCIA")
        
        tem_agendamento_futuro = "[AGENDADO:" in st_upper or "AGENDADA PARA" in st_upper
        
        if is_setup and not tem_agendamento_futuro:
            mins_passados = diff_mins(hora_registro, datetime.now(FUSO_BR).strftime("%H:%M"))
            if mins_passados > 0: 
                precisa_cortar = (turno_real == "1° TURNO" and diff_mins(hora_registro, "06:20") > 0 and diff_mins("06:20", hora_registro) > 12*60) or \
                               (turno_real == "2° TURNO" and diff_mins(hora_registro, "14:20") > 0 and diff_mins(hora_registro, "14:20") < 8*60) or \
                               (turno_real == "3° TURNO" and diff_mins(hora_registro, "22:20") > 0 and diff_mins(hora_registro, "22:20") < 8*60)
                if precisa_cortar:
                    tags = extrair_tags_producao(st_atual)
                    st_tipo_limpo = st_atual.split("[")[0].strip()
                    novo_st = f"AGUARDANDO PREPARADOR - {st_tipo_limpo} [Corte de Turno] {tags}".strip()
                    novas_linhas.append({"Setor": ultimo_registro['Setor'], "Maquina": maq, "Operador": "SISTEMA", "Status": novo_st, "Hora": hora_corte})
    if novas_linhas:
        # Apenas acrescenta os novos eventos; não regrava todo o histórico.
        salvar_tabela(pd.DataFrame(novas_linhas), ARQUIVO_DADOS, modo="append")

def registrar_queda_energia(setor):
    lista_maquinas = TODAS_AFC if setor == "AFC" else TODAS_RTF
    df = _carregar_ultimos_apontamentos().copy()
    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
    novas_linhas = []
    for maq_id in lista_maquinas:
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        st_atual = str(df_maq.iloc[-1]['Status']) if not df_maq.empty else "PRODUZINDO"
        if "Queda de Energia" not in st_atual:
            novas_linhas.append({"Setor": setor, "Maquina": maq_full, "Operador": st.session_state.get('operador', 'SISTEMA'), "Status": "PARADA - Motivo: Queda de Energia", "Hora": hora_br_str})
    if novas_linhas:
        salvar_tabela(pd.DataFrame(novas_linhas), ARQUIVO_DADOS, modo="append")

def restaurar_queda_energia(setor):
    lista_maquinas = TODAS_AFC if setor == "AFC" else TODAS_RTF
    df_atual = _carregar_ultimos_apontamentos().copy()
    if df_atual.empty:
        return
    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
    novas_linhas = []
    tabela = _quote_identifier(ARQUIVO_DADOS)
    for maq_id in lista_maquinas:
        maq_full = f"{setor} {maq_id}"
        atual = df_atual[df_atual['Maquina'] == maq_full]
        if atual.empty:
            continue
        st_atual = str(atual.iloc[-1]['Status'])
        if "Queda de Energia" not in st_atual:
            continue
        st_recuperado = "PRODUZINDO"
        try:
            result = turso_request(
                f'''SELECT "Status" FROM {tabela}
                    WHERE "Maquina"=? AND "Status" NOT LIKE '%Queda de Energia%'
                    ORDER BY rowid DESC LIMIT 1''', [maq_full], True)
            rows = result.get("rows", [])
            if rows:
                st_recuperado = str(_turso_decode(rows[0][0]))
        except Exception:
            pass
        novas_linhas.append({"Setor": setor, "Maquina": maq_full, "Operador": st.session_state.get('operador', 'SISTEMA'), "Status": f"{st_recuperado} [Energia Restaurada]", "Hora": hora_br_str})
    if novas_linhas:
        salvar_tabela(pd.DataFrame(novas_linhas), ARQUIVO_DADOS, modo="append")

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
            df_dados = _carregar_ultimos_apontamentos().copy()
            df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Posicao': str, 'Status': str, 'Armario': str})
            
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
                        
                        delta_mins = int((h_alvo_dt - agora_dt).total_seconds() / 60)
                        
                        if -120 <= delta_mins <= 180:
                            setor_maq = maq_id_full.split(" ")[0]
                            maq_num_only = maq_id_full.split(" ")[1]
                            gaveta_num = maq_num_only.split("-")[0]
                            
                            filtro_armario = "Afiadoras" if setor_maq == "AFC" else "Retíficas"
                            
                            gaveta_row = df_arm[
                                (df_arm['Posicao'] == str(gaveta_num)) & 
                                (df_arm['Armario'].str.contains(filtro_armario, case=False, na=False))
                            ]
                            
                            is_vazio = True
                            if not gaveta_row.empty:
                                if str(gaveta_row.iloc[0]['Status']).strip().upper() != 'VAZIO':
                                    is_vazio = False
                            
                            if is_vazio:
                                alertas_urgentes.append({
                                    'maquina': maq_id_full, 
                                    'gaveta': f"{gaveta_num} ({setor_maq})", 
                                    'hora': hora_alvo, 
                                    'delta': delta_mins
                                })
        except: pass
        
    if alertas_urgentes:
        html_alertas = "<div class='alerta-pisca'>"
        html_alertas += "<h4 style='margin-top:0; color:#fca5a5;'>🚨 ALERTA DE GAVETA VAZIA / PREPARAÇÃO IMINENTE</h4>"
        for alerta in sorted(alertas_urgentes, key=lambda x: x['delta']):
            if alerta['delta'] > 0:
                tempo_txt = f"falta(m) {alerta['delta']} min para a parada"
            elif alerta['delta'] == 0:
                tempo_txt = "é agora (neste momento)"
            else:
                tempo_txt = f"atrasado há {abs(alerta['delta'])} min"
                
            html_alertas += f"<p style='color:#fee2e2; margin-bottom:5px; font-size:15px;'>• Máquina <b>{alerta['maquina']}</b> (Gaveta {alerta['gaveta']}) agendada para <b>{alerta['hora']}</b> — <i>{tempo_txt}</i> -> <b style='color:#ff4444;'>GAVETA VAZIA!</b></p>"
        html_alertas += "</div>"
        st.markdown(html_alertas, unsafe_allow_html=True)

def exibir_alertas_preparador():
    if st.session_state.get('perfil') != 'preparador': return
    
    nome_usuario = st.session_state.get('operador', '').upper()
    if not nome_usuario: return
    
    status_dict = ler_status_atual()
    agora_dt = datetime.now(FUSO_BR)
    alertas_tempo = []
    alertas_prog = []
    
    for maq, st_val in status_dict.items():
        if f"[PREP: {nome_usuario}]" in st_val.upper() or f"[PREP. SUGERIDO: {nome_usuario}]" in st_val.upper():
            hora_alvo = ""
            if "AGENDADA PARA" in st_val.upper():
                try: hora_alvo = st_val.upper().split("AGENDADA PARA")[1].strip()
                except: pass
            elif "[AGENDADO:" in st_val.upper():
                try: hora_alvo = st_val.upper().split("[AGENDADO:")[1].split("]")[0].strip()
                except: pass
                
            if hora_alvo:
                h_alvo_dt = datetime.strptime(hora_alvo, "%H:%M").replace(year=agora_dt.year, month=agora_dt.month, day=agora_dt.day, tzinfo=FUSO_BR)
                if h_alvo_dt < agora_dt and (agora_dt - h_alvo_dt).total_seconds() > 12 * 3600: h_alvo_dt += timedelta(days=1)
                elif h_alvo_dt > agora_dt and (h_alvo_dt - agora_dt).total_seconds() > 12 * 3600: h_alvo_dt -= timedelta(days=1)
                
                delta_mins = int((h_alvo_dt - agora_dt).total_seconds() / 60)
                
                if -120 <= delta_mins <= 30:
                    alertas_tempo.append({'maquina': maq, 'hora': hora_alvo, 'delta': delta_mins})

        is_sugerido = f"[PREP. SUGERIDO: {nome_usuario}]" in st_val.upper()
        is_aguardando = "AGUARDANDO" in st_val.upper() or "AGENDADO" in st_val.upper() or "AGENDADA" in st_val.upper()
        is_prog_ok = "[PROG: OK" in st_val.upper()
        
        if is_sugerido and is_aguardando and is_prog_ok:
            alertas_prog.append(maq)
    
    if alertas_tempo or alertas_prog:
        html_alertas = "<div class='alerta-pisca'>"
        
        if alertas_tempo:
            html_alertas += "<h4 style='margin-top:0; color:#fca5a5;'>⏰ ATENÇÃO: SUAS PREPARAÇÕES PRÓXIMAS / ATRASADAS</h4>"
            for alerta in sorted(alertas_tempo, key=lambda x: x['delta']):
                chave_toast = f"toast_prep_{alerta['maquina']}_{alerta['hora']}"
                if chave_toast not in st.session_state:
                    st.session_state[chave_toast] = True
                    msg = f"Sua preparação na {alerta['maquina']} será às {alerta['hora']}!" if alerta['delta'] > 0 else f"A máquina {alerta['maquina']} está ATRASADA ({alerta['hora']})!"
                    st.toast(msg, icon="⏰")

                if alerta['delta'] > 0: tempo_txt = f"falta(m) {alerta['delta']} min"
                elif alerta['delta'] == 0: tempo_txt = "é agora!"
                else: tempo_txt = f"atrasada há {abs(alerta['delta'])} min"
                
                html_alertas += f"<p style='color:#fee2e2; margin-bottom:5px; font-size:15px;'>• Máquina <b>{alerta['maquina']}</b> (Agendada para <b>{alerta['hora']}</b>) — <i>{tempo_txt}</i></p>"
                
        if alertas_prog:
            if alertas_tempo: html_alertas += "<hr style='border-color: #ef4444; margin: 10px 0;'>"
            html_alertas += "<h4 style='margin-top:0; color:#86efac;'>💻 PROGRAMA LIBERADO</h4>"
            for maq in alertas_prog:
                chave_toast_prog = f"toast_prog_ok_{maq}"
                if chave_toast_prog not in st.session_state:
                    st.session_state[chave_toast_prog] = True
                    st.toast(f"O programa da {maq} já foi enviado para a máquina!", icon="💻")
                html_alertas += f"<p style='color:#dcfce7; margin-bottom:5px; font-size:15px;'>• <b>{maq}:</b> Programa validado! O setup está liberado para iniciar.</p>"
            
        html_alertas += "</div>"
        st.markdown(html_alertas, unsafe_allow_html=True)

def dar_baixa_armario(ordem_alvo, operador_nome="SISTEMA"):
    if not ordem_alvo or not str(ordem_alvo).strip() or not os.path.exists(ARQUIVO_ARMARIOS): return
    try:
        ordem_formatada = str(ordem_alvo).strip().upper().replace(".0", "").lstrip("0")
        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str, 'Armario': str, 'Observacao': str})
        if 'Item' not in df_arm.columns: df_arm['Item'] = ""
        if 'Observacao' not in df_arm.columns: df_arm['Observacao'] = ""
        
        df_arm['Ordem_busca'] = df_arm['Ordem'].astype(str).str.strip().str.upper().str.replace(".0", "", regex=False).str.lstrip("0")
        idx_ordem = df_arm[df_arm['Ordem_busca'] == ordem_formatada].index
        if not idx_ordem.empty:
            item_removido = str(df_arm.loc[idx_ordem[0], 'Item'])
            maq_removida = str(df_arm.loc[idx_ordem[0], 'Posicao'])
            armario_removido = str(df_arm.loc[idx_ordem[0], 'Armario'])
            
            hora_br_str = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")
            novo_alerta = {
                "Data_Hora": hora_br_str, "Armario": armario_removido, "Maquina": maq_removida, 
                "Ordem_Retirada": ordem_formatada, "Item": item_removido, "Preparador": operador_nome
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
        ordem_formatada = str(ordem_alvo).strip().upper().replace(".0", "").lstrip("0")
        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str)
        df_arm['Ordem_busca'] = df_arm['Ordem'].astype(str).str.strip().str.upper().str.replace(".0", "", regex=False).str.lstrip("0")
        match = df_arm[df_arm['Ordem_busca'] == ordem_formatada]
        if not match.empty:
            return str(match.iloc[0]['Item']).strip().replace(".0", "").lstrip("0")
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
if 'lirs_setor' not in st.session_state: st.session_state['lirs_setor'] = 'AFC'
if 'lirs_maq_ativa' not in st.session_state: st.session_state['lirs_maq_ativa'] = None

# Login automático por UM cookie assinado.
# O navegador só guarda um token validado; o código de acesso não é salvo.
if not st.session_state['operador'] and not st.session_state['logout_realizado']:
    token_cookie = cookies_salvos.get(COOKIE_LOGIN)
    acesso = validar_token_login(token_cookie) if token_cookie else None
    if acesso:
        st.session_state['operador'] = acesso["nome"]
        st.session_state['turno'] = acesso["turno"]
        st.session_state['setor_usuario'] = acesso["setor"]
        st.session_state['perfil'] = acesso["perfil"]
        st.session_state['tela_atual'] = 'menu'

def mudar_tela(nome_tela, forcar_rerun=False):
    # Quando usada como callback de botão, a alteração acontece ANTES do rerun natural
    # do Streamlit. Assim não precisamos disparar um segundo rerun.
    st.session_state['tela_atual'] = nome_tela
    st.session_state['celula_selecionada'] = None
    st.session_state['maq_ativa'] = None
    st.session_state['gaveta_selecionada'] = None
    st.session_state['fila_prev_sel'] = None
    st.session_state['setor_prev_sel'] = None
    st.session_state['lirs_maq_ativa'] = None
    if forcar_rerun:
        st.rerun()


def botao_navegar(label, nome_tela, **kwargs):
    """Botão de navegação sem o rerun duplo que causava o efeito de piscar."""
    return st.button(label, on_click=mudar_tela, args=(nome_tela,), **kwargs)


def definir_estado(chave, valor):
    st.session_state[chave] = valor


def definir_estados(valores):
    for chave, valor in valores.items():
        st.session_state[chave] = valor

def executar_manutencao_periodica():
    # O turno é calculado localmente; só acessamos o banco quando a chave de turno muda.
    # Isso elimina checagens periódicas durante a navegação normal.
    chave_turno = get_turno_logico()
    if st.session_state.get('_manutencao_turno_chave') == chave_turno:
        return
    st.session_state['_manutencao_turno_chave'] = chave_turno
    checar_e_auto_encerrar()
    verificar_virada_turno()


def ler_status_atual():
    executar_manutencao_periodica()
    try:
        df = _carregar_ultimos_apontamentos().copy()
    except Exception:
        return {}
    if df.empty:
        return {}
    try:
        status_calculado = {}
        agora_br_dt = datetime.now(FUSO_BR)
        for _, row in df.iterrows():
            maq = row['Maquina']
            st_raw = str(row['Status']).replace(" [Energia Restaurada]", "") 
            
            hora_alvo = ""
            if "AGENDADA PARA" in st_raw:
                try: hora_alvo = st_raw.split("AGENDADA PARA")[1].strip().split(" ")[0]
                except: pass
            elif "[AGENDADO:" in st_raw:
                try: hora_alvo = st_raw.split("[AGENDADO:")[1].split("]")[0].strip()
                except: pass
                
            if hora_alvo:
                try:
                    h_alvo_dt = datetime.strptime(hora_alvo, "%H:%M").replace(
                        year=agora_br_dt.year, month=agora_br_dt.month, day=agora_br_dt.day, tzinfo=FUSO_BR
                    )
                    
                    if h_alvo_dt < agora_br_dt and (agora_br_dt - h_alvo_dt).total_seconds() > 12 * 3600: 
                        h_alvo_dt += timedelta(days=1)
                    elif agora_br_dt < h_alvo_dt and (h_alvo_dt - agora_br_dt).total_seconds() > 12 * 3600: 
                        h_alvo_dt -= timedelta(days=1)
                        
                    if agora_br_dt >= h_alvo_dt:
                        tipo_agendado = st_raw.split(" AGENDADA PARA")[0] if "AGENDADA PARA" in st_raw else st_raw.split(" [AGENDADO:")[0]
                        tipo_agendado = tipo_agendado.replace("AGUARDANDO PREPARADOR - ", "").strip()
                        
                        st_base = f"AGUARDANDO PREPARADOR - {tipo_agendado}"
                        sug = f" [Prep. Sugerido: {st_raw.split('[Prep. Sugerido:')[1].split(']')[0].strip()}]" if "[Prep. Sugerido:" in st_raw else ""
                        tags = extrair_tags_producao(st_raw)
                        status_calculado[maq] = f"{st_base}{sug} {tags}".strip()
                    else:
                        st_limpo = st_raw.replace("AGUARDANDO PREPARADOR - ", "").strip()
                        status_calculado[maq] = st_limpo
                except:
                    status_calculado[maq] = st_raw
            else:
                status_calculado[maq] = st_raw
                
        return status_calculado
    except: return {}

def obter_info_maquina(maq_id, setor):
    try:
        # Reaproveita os últimos apontamentos, sem baixar o histórico inteiro.
        df = _carregar_ultimos_apontamentos()
        if df.empty:
            return None
        maq_full = f"{setor} {maq_id}"
        df_maq = df[df['Maquina'] == maq_full]
        if not df_maq.empty:
            return df_maq.iloc[-1].to_dict()
    except Exception:
        pass
    return None

def salvar_csv(dados, arquivo):
    """Grava UMA linha com INSERT direto no Turso.

    Antes esta função baixava a tabela inteira, adicionava uma linha e enviava
    tudo novamente. Isso ficava progressivamente mais lento conforme o histórico
    crescia.
    """
    dados = dict(dados)
    # Proteção global: nenhum novo apontamento pode entrar com dois horários
    # [AGENDADO] no mesmo Status. Mantém apenas o último horário informado.
    try:
        if str(arquivo) == str(ARQUIVO_DADOS) and 'Status' in dados:
            dados['Status'] = _agendamento_unico_status(dados.get('Status', ''))
    except Exception:
        pass
    df_novo = pd.DataFrame([dados])
    salvar_tabela(df_novo, arquivo, modo="append")

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
            
        col_f.button("✕", key=f"fechar_{maq_id}", on_click=definir_estado, args=('maq_ativa', None))

        if setor == 'RTF':
            with st.expander("🔄 Alterar Tipo CNC desta Máquina"):
                c_tipo1, c_tipo2 = st.columns([3, 2])
                novo_tipo = c_tipo1.selectbox("Definir como:", ["RTF_CNC3 (Normal)", "RTF_CNC2 (Facetadora)", "RTF_CNC1 (Centerless)"], index=0)
                if c_tipo2.button("💾 Salvar Tipo", use_container_width=True):
                    tipo_limpo = novo_tipo.split(" ")[0]
                    set_tipo_cnc(maq_id, tipo_limpo)
                    st.success(f"✅ Máquina alterada para {tipo_limpo}!")
                    st.rerun()
            
        status_dict = ler_status_atual()
        status_atual = status_dict.get(f"{setor} {maq_id}", "PRODUZINDO")
        info = obter_info_maquina(maq_id, setor)
        hora_atual = info.get('Hora', '--:--') if info else ''

        op_armario, item_armario = "", ""
        if os.path.exists(ARQUIVO_ARMARIOS):
            try:
                df_arm_temp = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str)
                gaveta_num = maq_id.split("-")[0]
                filtro_arm = "Afiadoras" if setor == "AFC" else "Retíficas"
                gaveta_row = df_arm_temp[(df_arm_temp['Posicao'] == str(gaveta_num)) & (df_arm_temp['Armario'].str.contains(filtro_arm))]
                if not gaveta_row.empty and str(gaveta_row.iloc[0]['Status']).strip() != 'VAZIO':
                    op_armario = str(gaveta_row.iloc[0].get('Ordem', '')).replace('.0', '').replace('nan', '').strip()
                    item_armario = str(gaveta_row.iloc[0].get('Item', '')).replace('.0', '').replace('nan', '').strip()
            except: pass
        
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
        
        status_exibicao = status_atual
        if st.session_state.get('perfil') == 'preset':
            status_exibicao = re.sub(r' \[Prep\. Sugerido:.*?\]', '', status_atual)
            status_exibicao = re.sub(r' \[Prep:.*?\]', '', status_exibicao)
            status_exibicao = re.sub(r' \[Prog:.*?\]', '', status_exibicao)
            
        if "AGUARDANDO PREPARADOR" in status_atual: st.warning(f"🟠 Status Atual: {status_exibicao}")
        elif "AGENDADO" in status_atual or "AGENDADA" in status_atual: st.info(f"🔵 Status: {status_exibicao}")
        elif "PREPARANDO" in status_atual: st.info(f"🟡 Status Atual: {status_exibicao} desde {hora_atual}{timer_str}")
        elif "SEQUÊNCIA" in status_atual: st.info(f"🟣 Status Atual: {status_exibicao} desde {hora_atual}{timer_str}")
        elif "PRODUZINDO" in status_atual: st.success(f"🟢 Status Atual: {status_exibicao}")
        elif "PARADA" in status_atual: st.error(f"🔴 Status Atual: Paralisada desde {hora_atual}")
        elif "MANUTENÇÃO" in status_atual: st.warning(f"🛠️ Status Atual: Em Manutenção desde {hora_atual}{timer_str}")
        else: st.warning(f"🟡 Status Atual: {status_exibicao} desde {hora_atual}{timer_str}")
            
        flow_key = f"flow_{maq_id}"
        is_setup_ativo = "PREPARANDO" in status_atual or "SEQUÊNCIA" in status_atual
        is_espera = "AGUARDANDO PREPARADOR" in status_atual or "AGENDADO" in status_atual or "AGENDADA" in status_atual
        
        if flow_key not in st.session_state:
            if is_espera: st.session_state[flow_key] = "acoes_espera"
            else: st.session_state[flow_key] = "pergunta"
            
        st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        
        if is_setup_ativo and st.session_state[flow_key] == "pergunta":
            is_troca_adiantada = "TROCA DE REBOLO ADIANTADA" in status_atual.upper()
            
            with st.form(f"form_fast_track_{maq_id}"):
                if is_troca_adiantada:
                    st.markdown(f"<p style='text-align: center; font-weight: 600;'>A troca de rebolo adiantada foi concluída?</p>", unsafe_allow_html=True)
                    obs_fast = st.text_input("Observação (Opcional):", placeholder="Ex: Rebolo pronto...")
                    
                    c1, c2, c3 = st.columns(3)
                    btn_concluir = c1.form_submit_button("✅ Concluir Troca")
                    btn_assumir = c2.form_submit_button("🔄 Assumir")
                    btn_alt = c3.form_submit_button("⚠️ Alterar")
                    
                    if btn_concluir:
                        hora_atual_dt = datetime.now(FUSO_BR)
                        hora_br_str = hora_atual_dt.strftime("%H:%M")
                        
                        info_atual = obter_info_maquina(maq_id, setor)
                        st_atual_raw = str(info_atual['Status']) if info_atual else ""
                        hora_inicio_str = str(info_atual['Hora']) if info_atual else hora_br_str
                        
                        minutos_decorridos = 0
                        try:
                            t_inicio = datetime.strptime(hora_inicio_str, "%H:%M")
                            t_fim = datetime.strptime(hora_br_str, "%H:%M")
                            if t_fim < t_inicio: t_fim += timedelta(days=1)
                            minutos_decorridos = int((t_fim - t_inicio).total_seconds() / 60)
                        except: pass
                        
                        st_fechamento = "PRODUZINDO [Troca de Rebolo Concluída]"
                        if obs_fast.strip(): st_fechamento += f" [Obs: {obs_fast.strip()}]"
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_fechamento, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        
                        h_alvo = ""
                        if "[AGENDADO:" in st_atual_raw:
                            try: 
                                h_alvo = st_atual_raw.split("[AGENDADO:")[1].split("]")[0].strip()
                                t_alvo = datetime.strptime(h_alvo, "%H:%M")
                                t_alvo_novo = t_alvo + timedelta(minutes=minutos_decorridos)
                                h_alvo = t_alvo_novo.strftime("%H:%M")
                            except: pass
                        
                        tags_prod = extrair_tags_producao(st_atual_raw)
                        st_volta = f"SEQUÊNCIA"
                        if h_alvo: st_volta += f" [AGENDADO:{h_alvo}]"
                        st_volta += f" {tags_prod}"
                        
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_volta.strip(), "Hora": hora_br_str}, ARQUIVO_DADOS)
                        
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success(f"✅ Troca concluída em {minutos_decorridos} min! Novo agendamento: {h_alvo if h_alvo else '--'}")
                        st.rerun()

                else:
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
                    
                    if "[Ordem:" in st_atual and "GUIA" not in st_atual.upper():
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
                
                tags_prod = extrair_tags_producao(st_atual)
                
                if "[Ordem:" not in tags_prod:
                    try:
                        df_temp = pd.read_csv(ARQUIVO_DADOS)
                        df_temp_maq = df_temp[df_temp['Maquina'] == f"{setor} {maq_id}"]
                        for idx in reversed(df_temp_maq.index):
                            st_hist = str(df_temp_maq.loc[idx, 'Status'])
                            if "[Ordem:" in st_hist:
                                tags_prod = extrair_tags_producao(st_hist)
                                break
                    except: pass
                
                if "[Ordem:" in tags_prod:
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
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
                    
            st.button("🟡 PREPARAÇÃO / SEQUÊNCIA", key=f"st_prep_{maq_id}", use_container_width=True, on_click=definir_estado, args=(flow_key, "detalhe_prep"))
            st.button("🛠️ MANUTENÇÃO", key=f"st_man_{maq_id}", use_container_width=True, on_click=definir_estado, args=(flow_key, "detalhe_man"))
            st.button("🔴 PARADA", key=f"st_par_{maq_id}", use_container_width=True, on_click=definir_estado, args=(flow_key, "detalhe_parada"))

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
                
                if not op_pre and op_armario: op_pre = op_armario
                if not item_pre and item_armario: item_pre = item_armario
                
                ordem = st.text_input("Ordem de Produção (OP):", value=op_pre, placeholder="Ex: 987654")
                item = st.text_input("Item:", value=item_pre, placeholder="Ex: 313324")
                
                if op_armario and (op_pre == op_armario or item_pre == item_armario):
                    st.success("📦 Dados puxados automaticamente da gaveta do armário!")
                    
                pcs_hora = st.text_input("Produção (Pçs/Hora) - Opcional:", placeholder="Ex: 150")
                obs = st.text_input("Observação / Justificativa (Opcional):", placeholder="Ex: Ajuste fino demorado...")
                
                if st.form_submit_button("🚀 INICIAR PRODUÇÃO", type="primary"):
                    if not ordem.strip() or not item.strip():
                        st.error("⚠️ A Ordem e o Item são obrigatórios!")
                    else:
                        hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                        item_limpo = item.strip().upper().replace(".0", "").lstrip("0")
                        ordem_limpa = ordem.strip().upper().replace(".0", "").lstrip("0")
                        st_final = f"PRODUZINDO [Ordem: {ordem_limpa}] [Item: {item_limpo}]"
                        if pcs_hora.strip(): st_final += f" [Pçs/Hora: {pcs_hora.strip()}]"
                        if obs.strip(): st_final += f" [Obs: {obs.strip()}]"
                        
                        if "GUIA" not in st_atual.upper():
                            dar_baixa_armario(ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Apontamento registrado! Máquina em Produção.")
                        st.rerun()

        elif st.session_state[flow_key] == "detalhe_parada":
            with st.form(f"form_par_{maq_id}"):
                st.markdown("🔴 **Registro de Máquina Parada**")
                motivo = st.selectbox("Motivo da Parada:", ["Falta de Operador", "Falta de Material", "Ajuste de Processo", "Manutenção Corretiva", "Outros"])
                op_faltante = st.text_input("Nome do Operador Faltante (Se aplicável):", placeholder="Ex: João Silva")
                detalhe = st.text_input("Outros Detalhes (Opcional):")
                
                if st.form_submit_button("💾 Registrar Parada", type="primary"):
                    if not detalhe.strip() and motivo == "Outros":
                        st.error("⚠️ Forneça os detalhes da parada.")
                    else:
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
                        st.rerun()

        elif st.session_state[flow_key] == "detalhe_prep":
            with st.form(f"form_prep_{maq_id}"):
                st.markdown("⚙️ **Configuração de Preparação / Agendamento**")
                info_atual = obter_info_maquina(maq_id, setor)
                st_atual = str(info_atual['Status']) if info_atual else ""
                
                hora_pre_fill = ""
                if "AGENDADA PARA" in st_atual.upper():
                    try: hora_pre_fill = st_atual.upper().split("AGENDADA PARA")[1].strip().split(" ")[0]
                    except: pass
                elif "[AGENDADO:" in st_atual.upper():
                    try: hora_pre_fill = st_atual.upper().split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "[Fim Previsto:" in st_atual:
                    try: hora_pre_fill = st_atual.split("[Fim Previsto:")[1].split("]")[0].strip()
                    except: pass
                    
                hora_relatorio = st.text_input("⏰ Horário Alvo (Aparecerá no Relatório):", value=hora_pre_fill, placeholder="Ex: 12:30")
                is_agendado = st.toggle("Marcar como Agendamento Futuro", value=True)
                
                prep_sugerido = st.text_input("🧑‍🔧 Sugerir Preparador (Opcional):", placeholder="Ex: Lucas")
                
                if setor == "AFC":
                    tipo_setup = st.radio("Selecione o Status:", ["PREPARAÇÃO", "SEQUÊNCIA"], horizontal=True)
                    troca_rebolo = st.toggle("Troca de Rebolo")
                else:
                    tipo_setup = st.radio("Setup:", ["HASTE", "GUIA"], horizontal=True)
                    troca_diametro = False
                    if tipo_setup == "HASTE": troca_diametro = st.toggle("Troca de Diâmetro")
                    troca_rebolo = st.toggle("Troca de Rebolo")
                
                is_guia = (setor != "AFC" and tipo_setup == "GUIA") or "GUIA" in st_atual.upper()
                
                op_pre, item_pre = "", ""
                if "[Ordem:" in st_atual: op_pre = st_atual.split("[Ordem:")[1].split("]")[0].strip()
                if "[Item Atual:" in st_atual: item_pre = st_atual.split("[Item Atual:")[1].split("]")[0].strip()
                elif "[Novo Item:" in st_atual: item_pre = st_atual.split("[Novo Item:")[1].split("]")[0].strip()
                elif "[Item:" in st_atual: item_pre = st_atual.split("[Item:")[1].split("]")[0].strip()

                if not is_guia:
                    if "[PROG: OK" in st_atual.upper():
                        st.markdown("💻 **Validação do Programa CNC**")
                        st.success("✅ Programa já enviado para a máquina pelo Programador!")
                        prog_status_prep = "SIM (Programa OK)"
                    else:
                        st.markdown("💻 **Validação do Programa CNC**")
                        prog_status_prep = st.selectbox("O programa da peça está OK na máquina?", ["-- Vá até a máquina e verifique --", "SIM (Programa OK)", "NÃO (Falta/Erro de Programa)"])
                    
                    st.markdown("📦 **Dados do Item**")
                    ordem_atual = st.text_input("Ordem Atual (OP):", value=op_pre, placeholder="Ex: 987654")
                    item_atual = st.text_input("Item Atual (Na Máquina):", value=item_pre, placeholder="Ex: 313324")
                else:
                    prog_status_prep = "SIM (Programa OK)"
                    ordem_atual = op_pre
                    item_atual = item_pre
                    st.info("ℹ️ Setup de GUIA: O Programa, a OP e o Item da haste atual serão mantidos automaticamente.")
                
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                
                if st.form_submit_button("💾 Salvar Registro", type="primary"):
                    if not hora_relatorio.strip():
                        st.error("⚠️ O campo de horário é obrigatório!")
                    elif prep_sugerido.strip() and not is_guia and prog_status_prep == "-- Vá até a máquina e verifique --":
                        st.error("⚠️ Como você sugeriu um preparador, é OBRIGATÓRIO verificar na máquina se o Programa está OK!")
                    else:
                        if setor == "AFC":
                            detalhe_setup = tipo_setup
                            if troca_rebolo: detalhe_setup += " (C/ Rebolo)"
                        else:
                            detalhe_setup = f"PREPARAÇÃO - {tipo_setup}"
                            if tipo_setup == "HASTE" and troca_diametro: detalhe_setup += " (C/ Diâmetro)"
                            if troca_rebolo: detalhe_setup += " (C/ Rebolo)"
                            
                        if prep_sugerido.strip(): 
                            detalhe_setup += f" [Prep. Sugerido: {prep_sugerido.strip().upper()}]"
                            val_prog = "OK" if "SIM" in prog_status_prep else "NOK"
                            detalhe_setup += f" [Prog: {val_prog}]"
                            
                        if is_agendado and hora_relatorio.strip(): 
                            st_final = f"{detalhe_setup} [AGENDADO:{hora_relatorio.strip()}]"
                        else: 
                            st_final = f"AGUARDANDO PREPARADOR - {detalhe_setup}"
                        
                        ordem_limpa = ordem_atual.strip().upper().replace(".0", "").lstrip("0")
                        item_limpa = item_atual.strip().upper().replace(".0", "").lstrip("0")
                        if ordem_limpa: st_final += f" [Ordem: {ordem_limpa}]"
                        if item_limpa: st_final += f" [Item Atual: {item_limpa}]"
                        
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_relatorio.strip()}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Registro salvo com sucesso!")
                        st.rerun()

        elif st.session_state[flow_key] == "acoes_espera":
            with st.form(f"form_espera_{maq_id}"):
                st.markdown("🧑‍🔧 **Assumir ou Sugerir Preparador**")
                sug_nome = ""
                if "[Prep. Sugerido:" in status_atual:
                    try: sug_nome = status_atual.split("[Prep. Sugerido:")[1].split("]")[0].strip()
                    except: pass
                    
                nome_input = st.text_input("Nome do Preparador:", value=sug_nome if sug_nome else "")
                
                is_guia = "GUIA" in status_atual.upper()
                is_seq = "SEQUÊNCIA" in status_atual.upper() or "SEQUENCIA" in status_atual.upper()
                is_comum = not is_guia and not is_seq
                
                if is_guia:
                    prog_status_espera = "SIM (Programa OK)"
                elif "[PROG: OK" in status_atual.upper():
                    st.markdown("💻 **Validação do Programa CNC**")
                    st.success("✅ Programa já enviado para a máquina pelo Programador!")
                    prog_status_espera = "SIM (Programa OK)"
                else:
                    st.markdown("💻 **Validação do Programa CNC**")
                    prog_status_espera = st.selectbox("O programa da peça está OK na máquina?", ["-- Vá até a máquina e verifique --", "SIM (Programa OK)", "NÃO (Falta/Erro de Programa)"])
                
                st.markdown("📦 **Dados da Preparação**")
                nova_ordem_input = ""
                
                if is_comum:
                    nova_ordem_input = st.text_input("Nova Ordem (OP) Entrando:", value=op_armario, placeholder="Ex: 987654")
                    if op_armario:
                        st.success(f"📦 OP {op_armario} puxada automaticamente do armário! (Item: {item_armario})")
                    else:
                        st.info("ℹ️ O Item da peça será puxado automaticamente do armário baseado nesta OP.")
                elif is_seq:
                    nova_ordem_input = st.text_input("Nova Ordem (OP) Entrando:", value=op_armario, placeholder="Ex: 987654")
                    if op_armario:
                        st.success(f"📦 OP {op_armario} puxada automaticamente do armário!")
                    else:
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
                if "[AGENDADO:" in status_atual.upper() or "AGENDADA PARA" in status_atual.upper():
                    try:
                        hora_agend = status_atual.split("AGENDADA PARA")[1].strip().split(" ")[0] if "AGENDADA PARA" in status_atual else status_atual.split("[AGENDADO:")[1].split("]")[0].strip()
                        turno_agend = obter_turno_por_horario(hora_agend)
                        if turno_agend != st.session_state.get('turno') and st.session_state.get('perfil') != 'adm':
                            bloquear_inicio = True
                            msg_bloqueio = f"⚠️ Setup programado para o {turno_agend}. Apenas operadores daquele turno podem iniciar."
                    except: pass

                if bloquear_inicio: st.warning(msg_bloqueio)
                
                is_afc_seq = (setor == "AFC" and is_seq)
                
                if is_afc_seq:
                    c1, c2, c3, c4 = st.columns(4)
                    btn_sugerir = c1.form_submit_button("💡 Sugerir")
                    btn_iniciar = c2.form_submit_button("🚀 INICIAR", type="primary", disabled=bloquear_inicio)
                    btn_rebolo_adiantado = c3.form_submit_button("🛞 Trocar Rebolo")
                    btn_alterar = c4.form_submit_button("⚠️ Alterar")
                else:
                    c1, c2, c3 = st.columns(3)
                    btn_sugerir = c1.form_submit_button("💡 Apenas Sugerir")
                    btn_iniciar = c2.form_submit_button("🚀 INICIAR", type="primary", disabled=bloquear_inicio)
                    btn_rebolo_adiantado = False
                    btn_alterar = c3.form_submit_button("⚠️ Alterar Status")
                
                if btn_alterar: st.session_state[flow_key] = "mudanca_status"; st.rerun()

                if btn_rebolo_adiantado:
                    nome_final = nome_input if nome_input.strip() else st.session_state['operador']
                    hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                    info_atual = obter_info_maquina(maq_id, setor)
                    tags_prod = extrair_tags_producao(str(info_atual['Status'])) if info_atual else ""
                    
                    tags_prod = re.sub(r' \[Ordem:.*?\]', '', tags_prod)
                    tags_prod = re.sub(r' \[Novo Item:.*?\]', '', tags_prod)
                    
                    h_alvo = ""
                    st_atual_raw = str(info_atual['Status']) if info_atual else ""
                    if "AGENDADA PARA" in st_atual_raw.upper():
                        try: h_alvo = st_atual_raw.upper().split('AGENDADA PARA')[1].strip().split(" ")[0]
                        except: pass
                    elif "[AGENDADO:" in st_atual_raw.upper():
                        try: h_alvo = st_atual_raw.upper().split('[AGENDADO:')[1].split(']')[0].strip()
                        except: pass
                        
                    st_andamento = f"PREPARANDO - TROCA DE REBOLO ADIANTADA [Prep: {nome_final.strip().upper()}]"
                    if h_alvo: st_andamento += f" [AGENDADO:{h_alvo}]"
                    st_andamento += f" {tags_prod}"
                    
                    salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_andamento.strip(), "Hora": hora_br_str}, ARQUIVO_DADOS)
                    st.session_state['maq_ativa'] = None
                    del st.session_state[flow_key]
                    st.success("✅ Troca de rebolo iniciada! O tempo já está contando.")
                    st.rerun()

                if btn_adiar:
                    if novo_horario_adiar.strip():
                        info_atual = obter_info_maquina(maq_id, setor)
                        if info_atual:
                            raw_st = str(info_atual['Status'])
                            raw_st = re.sub(r'AGENDADA PARA \d{2}:\d{2}', '', raw_st, flags=re.IGNORECASE)
                            raw_st = re.sub(r'\[AGENDADO:\d{2}:\d{2}\]', '', raw_st, flags=re.IGNORECASE)
                            raw_st = raw_st.strip()
                            raw_st += f" [AGENDADO:{novo_horario_adiar.strip()}]"
                            
                            salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": novo_horario_adiar.strip()}, ARQUIVO_DADOS)
                            st.session_state['maq_ativa'] = None
                            del st.session_state[flow_key]
                            st.success(f"✅ Agendamento adiado para {novo_horario_adiar.strip()}!")
                            st.rerun()
                    else: st.error("⚠️ Informe o novo horário para adiar!")
                    
                if btn_sugerir:
                    if not nome_input.strip():
                        st.error("⚠️ Informe um nome para sugerir!")
                    elif not is_guia and prog_status_espera == "-- Vá até a máquina e verifique --":
                        st.error("⚠️ É obrigatório verificar se o programa está OK antes de sugerir um preparador!")
                    else:
                        info_atual = obter_info_maquina(maq_id, setor)
                        if info_atual:
                            raw_st = str(info_atual['Status'])
                            raw_st = re.sub(r' \[Prep\. Sugerido:.*?\]', '', raw_st, flags=re.IGNORECASE)
                            raw_st = re.sub(r' \[Prog:.*?\]', '', raw_st, flags=re.IGNORECASE)
                            
                            val_prog = "OK" if "SIM" in prog_status_espera else "NOK"
                            tag_prog = f" [Prog: {val_prog}]"
                            
                            if "AGENDADA PARA" in raw_st.upper():
                                hora_agend = raw_st.upper().split("AGENDADA PARA")[1].strip().split(" ")[0]
                                st_base = raw_st.upper().split(" AGENDADA PARA")[0]
                                raw_st = f"{st_base} [Prep. Sugerido: {nome_input.strip().upper()}]{tag_prog} [AGENDADO:{hora_agend}]"
                            elif "[AGENDADO:" in raw_st.upper(): 
                                raw_st = raw_st.replace(" [AGENDADO:", f" [Prep. Sugerido: {nome_input.strip().upper()}]{tag_prog} [AGENDADO:")
                            else: 
                                raw_st += f" [Prep. Sugerido: {nome_input.strip().upper()}]{tag_prog}"
                            
                            hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                            salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": hora_br_str}, ARQUIVO_DADOS)
                            st.session_state['maq_ativa'] = None
                            del st.session_state[flow_key]
                            st.success("✅ Sugestão e validação do programa atualizadas!")
                            st.rerun()
                            
                if btn_iniciar:
                    if is_comum and not nova_ordem_input.strip(): st.error("⚠️ Para INICIAR a preparação, informe a Nova Ordem (OP)!")
                    elif is_seq and not nova_ordem_input.strip(): st.error("⚠️ Para INICIAR a Sequência, informe a Nova Ordem (OP)!")
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
                        nova_ordem_limpa = nova_ordem_input.strip().upper().replace(".0", "").lstrip("0")

                        if not is_guia:
                            if is_comum:
                                item_buscado = buscar_item_por_ordem(nova_ordem_limpa)
                                st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                                st_andamento += f" [Novo Item: {item_buscado}]"
                                dar_baixa_armario(nova_ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                            elif is_seq:
                                st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                                dar_baixa_armario(nova_ordem_limpa, st.session_state.get('operador', 'SISTEMA'))
                        else:
                            if nova_ordem_limpa:
                                st_andamento += f" [Ordem: {nova_ordem_limpa}]"
                            
                        salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_id}", "Operador": st.session_state['operador'], "Status": st_andamento, "Hora": hora_br_str}, ARQUIVO_DADOS)
                        st.session_state['maq_ativa'] = None
                        del st.session_state[flow_key]
                        st.success("✅ Preparação iniciada!")
                        st.rerun()

        elif st.session_state[flow_key] == "detalhe_man":
            with st.form(f"form_man_{maq_id}"):
                st.markdown("🛠 **Registro de Manutenção**")
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
                        st.rerun()

def _buscar_maquina_topbar():
    """Busca uma máquina sem trocar de URL nem reiniciar a sessão do Streamlit."""
    busca = str(st.session_state.get('topbar_busca_maquina', '') or '').strip()
    if not busca:
        return

    termo = busca.upper().replace('MÁQUINA', '').replace('MAQUINA', '').strip()
    termo = termo.replace('AFC ', '').replace('RTF ', '').strip()
    perfil = st.session_state.get('perfil', '')
    setor_user = st.session_state.get('setor_usuario', '')

    setor_encontrado = None
    if termo in TODAS_AFC:
        setor_encontrado = 'AFC'
    elif termo in TODAS_RTF:
        setor_encontrado = 'RTF'

    pode_abrir = (
        perfil == 'adm' or
        (perfil == 'preparador' and setor_user in [setor_encontrado, 'TECNICO'])
    )

    if setor_encontrado and pode_abrir:
        st.session_state['maq_ativa'] = termo
        st.session_state['setor_ativo'] = setor_encontrado
        st.session_state['celula_selecionada'] = None
        st.session_state['tela_atual'] = 'afc' if setor_encontrado == 'AFC' else 'rtf'
    elif setor_encontrado:
        st.session_state['tela_atual'] = 'visao_geral'
        st.session_state['_busca_msg'] = f"Máquina {termo} encontrada em {setor_encontrado}. Seu perfil possui acesso de consulta pela Visão Geral."
    else:
        st.session_state['_busca_msg'] = f"Máquina '{busca}' não encontrada."

    st.session_state['topbar_busca_maquina'] = ''


def _links_topo_por_perfil():
    perfil = st.session_state.get('perfil', '')
    links = [
        ('menu', '⌂', 'Início'),
        ('visao_geral', '▦', 'Máquinas'),
        ('checkup', '◷', 'Programação'),
        ('hub_relatorios', '▤', 'Relatórios'),
    ]
    if perfil in ['adm', 'preset', 'preparador']:
        links.append(('armarios', '▣', 'Armários'))
    if perfil in ['adm', 'programador', 'preparador']:
        links.append(('equipe', '◎', 'Equipe'))
    if perfil == 'adm':
        links.append(('historico', '↗', 'Histórico'))
    return links


def renderizar_topbar(tela_atual):
    """Barra nativa do Streamlit: não recarrega a página nem perde a sessão."""
    perfil = st.session_state.get('perfil', '')
    setor = st.session_state.get('setor_usuario', '')
    turno = st.session_state.get('turno', '')
    nome_raw = str(st.session_state.get('operador', 'Usuário'))
    nome = html.escape(nome_raw)

    aliases_ativos = {
        'afc': 'visao_geral', 'rtf': 'visao_geral',
        'minhas_incidencias': 'checkup',
        'relatorio': 'hub_relatorios', 'lirs': 'hub_relatorios',
    }
    ativo = aliases_ativos.get(tela_atual, tela_atual)
    setor_txt = 'Geral' if setor in ['GERAL', 'GERÊNCIA'] else setor.title() if setor else perfil.title()
    inicial = html.escape(nome_raw[:1].upper() if nome_raw else 'U')

    with st.container(key='topbar_native'):
        c_brand, c_search, c_user = st.columns([2.1, 2.0, 1.25])

        c_brand.markdown(
            f'''<div class="native-brand">
<div class="native-brand-icon">⚙</div>
<div><div class="native-brand-name">AFIAÇÃO DIGITAL</div><div class="native-brand-sub">Operação em tempo real</div></div>
</div>''',
            unsafe_allow_html=True
        )

        with c_search:
            st.text_input(
                'Buscar máquina',
                key='topbar_busca_maquina',
                placeholder='⌕  Buscar máquina e pressionar Enter...',
                label_visibility='collapsed',
                on_change=_buscar_maquina_topbar,
            )

        c_user.markdown(
            f'''<div class="native-user">
<div><div class="native-user-name">{nome}</div><div class="native-user-meta">{html.escape(turno)} · {html.escape(setor_txt)}</div></div>
<div class="native-user-avatar">{inicial}</div>
</div>''',
            unsafe_allow_html=True
        )

    links = _links_topo_por_perfil()
    with st.container(key='topbar_nav_native'):
        cols = st.columns(len(links))
        for i, (destino, icone, rotulo) in enumerate(links):
            cols[i].button(
                f'{icone}  {rotulo}',
                key=f'topnav_{destino}',
                use_container_width=True,
                type='primary' if ativo == destino else 'secondary',
                on_click=mudar_tela,
                args=(destino,),
            )

    msg = st.session_state.pop('_busca_msg', None)
    if msg:
        st.info(msg)


def _classificar_preparacao_home(status):
    """Separa preparação EXECUTANDO de preparação apenas PROGRAMADA/AGUARDANDO."""
    up = str(status).strip().upper()
    if up.startswith('PREPARANDO'):
        return 'ativa'
    if (
        up.startswith('PREPARAÇÃO') or up.startswith('PREPARACAO') or
        up.startswith('SEQUÊNCIA') or up.startswith('SEQUENCIA') or
        up.startswith('AGUARDANDO') or 'AGUARDANDO PREPARADOR' in up
    ):
        return 'aguardando'
    return None


def _eh_aguardando_setup_home(status):
    """True quando existe setup programado/aguardando, mas ainda não está PREPARANDO."""
    return _classificar_preparacao_home(status) == 'aguardando'


def _classificar_status_home(status):
    up = str(status).upper()
    if 'MANUTENÇÃO' in up or 'MANUTENCAO' in up:
        return 'manutencao'
    if up.startswith('PARADA') or ' PARADA' in up:
        return 'parada'
    if _classificar_preparacao_home(status):
        return 'preparacao'
    if 'PRODUZINDO' in up:
        return 'producao'
    return 'outros'


def _resumo_setor_home(status_dict, setor, maquinas):
    """Resumo operacional da Home.

    Preparação aguardando é programação futura: a máquina continua em produção.
    Ela só sai do KPI de produção em PREPARANDO, PARADA ou MANUTENÇÃO.
    """
    r = {
        'producao':0, 'preparacao':0, 'prep_ativa':0, 'prep_aguardando':0,
        'parada':0, 'manutencao':0, 'outros':0, 'total':len(maquinas)
    }
    for m in maquinas:
        st_val = status_dict.get(f'{setor} {m}', 'PRODUZINDO')
        up = str(st_val).upper()
        prep = _classificar_preparacao_home(st_val)

        if 'MANUTENÇÃO' in up or 'MANUTENCAO' in up:
            r['manutencao'] += 1
            continue
        if up.startswith('PARADA') or ' PARADA' in up:
            r['parada'] += 1
            continue
        if prep == 'ativa':
            r['preparacao'] += 1
            r['prep_ativa'] += 1
            continue
        if prep == 'aguardando':
            r['preparacao'] += 1
            r['prep_aguardando'] += 1
            r['producao'] += 1
            continue

        r['producao'] += 1
        if 'PRODUZINDO' not in up:
            r['outros'] += 1
    return r


def _render_kpi(label, valor, icone, cor, detalhe):
    return f'''<div class="kpi-card" style="--kpi-color:{cor}">
<div class="kpi-head"><div class="kpi-label">{label}</div><div class="kpi-icon">{icone}</div></div>
<div class="kpi-value">{valor}</div>
<div class="kpi-foot"><span class="kpi-dot"></span>{detalhe}</div>
</div>'''


def _render_prep_kpi(ativas, aguardando):
    total = ativas + aguardando
    return f'''<div class="kpi-card" style="--kpi-color:#F59E0B">
<div class="kpi-head"><div class="kpi-label">Preparações</div><div class="kpi-icon">⚙</div></div>
<div class="kpi-value">{total}</div>
<div class="prep-kpi-breakdown">
<div class="prep-kpi-mini active"><div class="prep-kpi-mini-label">Ativas</div><div class="prep-kpi-mini-value">{ativas}</div></div>
<div class="prep-kpi-mini waiting"><div class="prep-kpi-mini-label">Aguardando</div><div class="prep-kpi-mini-value">{aguardando}</div></div>
</div>
</div>'''


def _render_setor_bar(nome, resumo):
    total = max(1, resumo['total'])
    prod = resumo['producao']
    pct = round((prod / total) * 100)
    return f'''<div class="sector-row">
<div class="sector-name">{nome}</div>
<div class="sector-track"><div class="sector-fill" style="width:{pct}%"></div></div>
<div class="sector-pct">{pct}%</div>
</div>
<div class="sector-mini">
<span>Produção <b>{prod}</b></span>
<span>Prep. ativa <b>{resumo['prep_ativa']}</b></span>
<span>Aguard. <b>{resumo['prep_aguardando']}</b></span>
<span>Parada <b>{resumo['parada']}</b></span>
<span>Manut. <b>{resumo['manutencao']}</b></span>
</div>'''


def _estado_atual_home():
    """Metadados do último apontamento de cada máquina, usados apenas no dashboard."""
    try:
        df = _carregar_ultimos_apontamentos().copy()
    except Exception:
        return {}
    saida = {}
    if df.empty:
        return saida
    for _, row in df.iterrows():
        chave = str(row.get('Maquina', '')).strip()
        if not chave:
            continue
        saida[chave] = {
            'hora': str(row.get('Hora', '') or '').strip(),
            'operador': str(row.get('Operador', '') or '').strip(),
            'status': str(row.get('Status', '') or '').strip(),
        }
    return saida


def _minutos_status_home(hora_inicio):
    """Calcula há quanto tempo um estado ATIVO começou usando HH:MM."""
    try:
        h = datetime.strptime(str(hora_inicio).strip(), '%H:%M').time()
        agora = datetime.now(FUSO_BR)
        inicio = datetime.combine(agora.date(), h, tzinfo=FUSO_BR)
        if inicio > agora:
            inicio -= timedelta(days=1)
        return max(0, int((agora - inicio).total_seconds() // 60))
    except Exception:
        return 0


def _tempo_curto_home(mins):
    mins = max(0, int(mins or 0))
    if mins < 1:
        return 'agora'
    if mins < 60:
        return f'{mins} min'
    h, m = divmod(mins, 60)
    return f'{h}h {m:02d}m' if m else f'{h}h'


def _extrair_hora_programada_home(status):
    """Lê a hora PROGRAMADA do status. Não usa a hora em que o status foi salvo."""
    txt = str(status or '')
    for padrao in (
        r'\[AGENDADO:\s*(\d{1,2}:\d{2})\]',
        r'AGENDADA\s+PARA\s+(\d{1,2}:\d{2})',
    ):
        m = re.search(padrao, txt, flags=re.IGNORECASE)
        if m:
            try:
                return datetime.strptime(m.group(1), '%H:%M').strftime('%H:%M')
            except Exception:
                pass
    return ''


def _info_programacao_home(status, agora=None):
    """Retorna a programação como 'em X' ou 'atrasada X'.

    A referência é o DIA LÓGICO do turno do app. Assim 06:30/14:30/22:30 são
    posicionados no dia correto, inclusive durante o 3º turno após meia-noite.
    """
    hora = _extrair_hora_programada_home(status)
    if not hora:
        return {'hora':'', 'prefixo':'', 'tempo':'Sem horário', 'delta':None, 'ordem':10**9}
    try:
        agora = agora or datetime.now(FUSO_BR)
        h = datetime.strptime(hora, '%H:%M').time()
        data_logica_str, _ = get_turno_logico(agora)
        data_logica = datetime.strptime(data_logica_str, '%d/%m/%Y').date()
        alvo = datetime.combine(data_logica, h, tzinfo=FUSO_BR)

        # Horários da madrugada pertencem ao 3º turno iniciado no dia lógico.
        turno_prog = obter_turno_por_horario(hora)
        if turno_prog == '3° TURNO' and h < dtime(6, 30):
            alvo += timedelta(days=1)

        delta = int((alvo - agora).total_seconds() // 60)
        # Se ficou mais de 12h para trás, trata como a próxima ocorrência do
        # horário. É apenas uma proteção porque o status não guarda a data.
        if delta < -(12 * 60):
            alvo += timedelta(days=1)
            delta = int((alvo - agora).total_seconds() // 60)

        if delta > 0:
            return {'hora':hora, 'prefixo':f'programada {hora}', 'tempo':f'em {_tempo_curto_home(delta)}', 'delta':delta, 'ordem':delta}
        if delta < 0:
            atraso = abs(delta)
            return {'hora':hora, 'prefixo':f'programada {hora}', 'tempo':f'atrasada {_tempo_curto_home(atraso)}', 'delta':delta, 'ordem':-100000-atraso}
        return {'hora':hora, 'prefixo':f'programada {hora}', 'tempo':'agora', 'delta':0, 'ordem':-100000}
    except Exception:
        return {'hora':hora, 'prefixo':f'programada {hora}', 'tempo':'—', 'delta':None, 'ordem':10**9}


def _inicios_preparacao_ativa_home():
    """Primeiro PREPARANDO do ciclo ativo, sem reiniciar ao trocar preparador."""
    try:
        df = pd.read_csv(ARQUIVO_DADOS)
    except Exception:
        return {}
    if df.empty or 'Maquina' not in df.columns:
        return {}
    saida = {}
    for maq, dfm in df.groupby('Maquina', sort=False):
        inicio = ''
        ativo = False
        for _, row in dfm.iterrows():
            st_up = str(row.get('Status', '')).strip().upper()
            if st_up.startswith('PREPARANDO'):
                if not ativo:
                    inicio = str(row.get('Hora', '') or '').strip()
                    ativo = True
            elif (
                st_up.startswith('PRODUZINDO') or st_up.startswith('PARADA') or
                st_up.startswith('MANUTENÇÃO') or st_up.startswith('MANUTENCAO')
            ):
                inicio = ''
                ativo = False
        if ativo and inicio:
            saida[str(maq).strip()] = inicio
    return saida


def _render_prep_item(setor, maq, status, hora_inicio, operador, tipo, tempo_info=None):
    if tipo == 'ativa':
        tempo = _tempo_curto_home(_minutos_status_home(hora_inicio))
        prefixo = 'há'
    else:
        info = tempo_info or _info_programacao_home(status)
        tempo = info.get('tempo', 'Sem horário')
        prefixo = info.get('prefixo', '')
    status_curto = html.escape(str(status).split('[')[0].strip())
    op = html.escape(str(operador).strip()) if operador else ''
    meta = html.escape(setor)
    if op:
        meta += f' · {op}'
    classe = 'active' if tipo == 'ativa' else 'waiting'
    icone = '▶' if tipo == 'ativa' else '◷'
    return f"""<div class="prep-item {classe}">
<div class="prep-ico">{icone}</div>
<div style="min-width:0">
<div class="prep-machine">Máquina {html.escape(maq)}</div>
<div class="prep-status">{status_curto}</div>
<div class="prep-meta">{meta}</div>
</div>
<div class="prep-time"><span>{html.escape(str(prefixo))}</span>{html.escape(str(tempo))}</div>
</div>"""


def _normalizar_setup_home(txt):
    return unicodedata.normalize('NFKD', str(txt or '').upper()).encode('ASCII', 'ignore').decode('ASCII')


def _categoria_setup_home(setor, status):
    """Classificação pedida para o desempenho mensal."""
    up = _normalizar_setup_home(status)
    setor = str(setor or '').upper()
    if setor == 'RTF':
        if 'GUIA' in up:
            return 'rtf_guia'
        if 'HASTE' in up:
            return 'rtf_haste'
    elif setor == 'AFC':
        if 'SEQUENCIA' in up:
            return 'afc_sequencia'
        if 'PREPARACAO' in up:
            return 'afc_preparacao'
    return None


def _resultado_turso_df(result):
    cols = [c.get('name') for c in result.get('cols', [])]
    rows = [[_turso_decode(v) for v in row] for row in result.get('rows', [])]
    return pd.DataFrame(rows, columns=cols)


def _datetime_evento_setup_home(data_str, hora_str, turno=''):
    try:
        base = datetime.strptime(str(data_str).strip(), '%d/%m/%Y')
        h = datetime.strptime(str(hora_str).strip(), '%H:%M')
        dt = datetime(base.year, base.month, base.day, h.hour, h.minute, tzinfo=FUSO_BR)
        if str(turno).strip() == '3° TURNO' and h.hour < 7:
            dt += timedelta(days=1)
        return dt
    except Exception:
        return None


def _metricas_setups_mes_home(agora=None):
    """Quantidade e tempo médio dos SETUPS CONCLUÍDOS no mês atual."""
    agora = agora or datetime.now(FUSO_BR)
    primeiro_mes = datetime(agora.year, agora.month, 1, tzinfo=FUSO_BR)
    mes_anterior = (primeiro_mes - timedelta(days=1)).strftime('%m/%Y')
    mes_atual = primeiro_mes.strftime('%m/%Y')
    partes = []
    try:
        if tabela_existe(ARQUIVO_HISTORICO_EVENTOS):
            tab = _quote_identifier(ARQUIVO_HISTORICO_EVENTOS)
            result = turso_request(
                f"""SELECT rowid AS "_ord", "Setor", "Maquina", "Status", "Hora", "Data_Registro", "Turno_Registro"
                    FROM {tab}
                    WHERE substr("Data_Registro", 4, 7) IN (?, ?)""",
                [mes_anterior, mes_atual], True
            )
            dfh = _resultado_turso_df(result)
            if not dfh.empty:
                dfh['_fonte'] = 'hist'
                partes.append(dfh)
    except Exception:
        pass
    try:
        if tabela_existe(ARQUIVO_DADOS):
            tab = _quote_identifier(ARQUIVO_DADOS)
            result = turso_request(
                f"""SELECT rowid AS "_ord", "Setor", "Maquina", "Status", "Hora" FROM {tab} ORDER BY rowid""",
                want_rows=True
            )
            dfc = _resultado_turso_df(result)
            if not dfc.empty:
                data_logica, turno_logico = get_turno_logico()
                dfc['Data_Registro'] = data_logica
                dfc['Turno_Registro'] = turno_logico
                dfc['_fonte'] = 'atual'
                partes.append(dfc)
    except Exception:
        pass
    chaves = ['rtf_guia','rtf_haste','afc_preparacao','afc_sequencia']
    saida = {k:{'qtd':0, 'media':0, 'duracoes':[]} for k in chaves}
    if not partes:
        return saida
    df = pd.concat(partes, ignore_index=True, sort=False)
    for c in ['Setor','Maquina','Status','Hora','Data_Registro','Turno_Registro']:
        if c not in df.columns:
            df[c] = ''
        df[c] = df[c].fillna('').astype(str)
    df = df.drop_duplicates(subset=['Setor','Maquina','Status','Hora','Data_Registro'], keep='last').copy()
    df['_dt'] = [
        _datetime_evento_setup_home(d, h, t)
        for d, h, t in zip(df['Data_Registro'], df['Hora'], df['Turno_Registro'])
    ]
    df = df[df['_dt'].notna()].copy()
    if df.empty:
        return saida
    if '_ord' not in df.columns:
        df['_ord'] = 0
    df['_ord'] = pd.to_numeric(df['_ord'], errors='coerce').fillna(0)
    df = df.sort_values(['Maquina','_dt','_ord'], kind='stable')
    registros = []
    for maq, dfm in df.groupby('Maquina', sort=False):
        categoria_pendente = None
        categoria_ativa = None
        inicio_ativo = None
        for _, row in dfm.iterrows():
            setor = str(row['Setor']).upper().strip()
            status = str(row['Status'])
            up = _normalizar_setup_home(status).strip()
            dt = row['_dt']
            if up.startswith('PREPARACAO') or up.startswith('SEQUENCIA') or up.startswith('AGUARDANDO'):
                cat = _categoria_setup_home(setor, status)
                if cat:
                    categoria_pendente = cat
                continue
            if up.startswith('PREPARANDO'):
                if 'TROCA DE REBOLO ADIANTADA' in up:
                    continue
                if inicio_ativo is None:
                    inicio_ativo = dt
                    categoria_ativa = categoria_pendente or _categoria_setup_home(setor, status)
                continue
            if up.startswith('PRODUZINDO'):
                if inicio_ativo is not None and categoria_ativa in saida:
                    dur = int((dt - inicio_ativo).total_seconds() // 60)
                    if 0 <= dur <= 12 * 60 and dt.year == agora.year and dt.month == agora.month:
                        registros.append((categoria_ativa, dur))
                inicio_ativo = None
                categoria_ativa = None
                categoria_pendente = None
                continue
            if up.startswith('PARADA') or up.startswith('MANUTENCAO'):
                inicio_ativo = None
                categoria_ativa = None
                categoria_pendente = None
    for cat, dur in registros:
        saida[cat]['duracoes'].append(dur)
    for cat in chaves:
        durs = saida[cat]['duracoes']
        saida[cat]['qtd'] = len(durs)
        saida[cat]['media'] = round(sum(durs) / len(durs)) if durs else 0
    return saida


def _render_setup_metric_card(titulo, dados, icone, cor):
    qtd = int(dados.get('qtd', 0))
    media = int(dados.get('media', 0))
    tempo = _tempo_curto_home(media) if qtd else '—'
    return f"""<div class="setup-metric-card" style="--setup-color:{cor}">
<div class="setup-metric-head"><span>{html.escape(titulo)}</span><b>{icone}</b></div>
<div class="setup-metric-main"><strong>{qtd}</strong><span>setups concluídos</span></div>
<div class="setup-metric-average"><span>Tempo médio no mês</span><b>{tempo}</b></div>
</div>"""


def _media_setor_setup_home(metricas, chaves):
    durs = []
    for chave in chaves:
        durs.extend(metricas.get(chave, {}).get('duracoes', []))
    return (len(durs), round(sum(durs)/len(durs)) if durs else 0)


def _acoes_rapidas_home(perfil):
    itens = []
    if perfil == 'adm':
        itens = [
            ('💻 Painel do Programador', 'programador'), ('⚙️ Módulo Afiação', 'afc'),
            ('⚙️ Módulo Retífica', 'rtf'), ('✏️ Banco de Dados', 'editar')
        ]
    elif perfil == 'preset':
        itens = [('💻 Painel do Programador', 'programador')]
    elif perfil == 'programador':
        itens = [('💻 Painel do Programador', 'programador')]
    elif perfil == 'preparador':
        setor = st.session_state.get('setor_usuario')
        if setor in ['AFC', 'TECNICO']:
            itens.append(('⚙️ Módulo Afiação', 'afc'))
        if setor in ['RTF', 'TECNICO']:
            itens.append(('⚙️ Módulo Retífica', 'rtf'))
        itens.extend([('⚡ Minhas Incidências', 'minhas_incidencias'), ('✏️ Corrigir Apontamentos', 'editar')])
    else:
        itens = [('✏️ Corrigir Apontamentos', 'editar')]
    return itens


def tela_login():
    st.markdown(textwrap.dedent("""
    <div class="login-hero">
        <div class="login-logo">⚙️</div>
        <div class="login-title">AFIAÇÃO DIGITAL</div>
        <p class="login-subtitle">Controle operacional de produção, preparação e ocorrências em uma única experiência.</p>
        <div class="login-pill">● Sistema operacional online</div>
    </div>
    """), unsafe_allow_html=True)
    with st.container():
        cod = st.text_input("Digite seu codigo de Acesso:", type="password", placeholder="Digite aqui...")
        nome = st.text_input("Nome do Colaborador / RE:", placeholder="Digite seu nome...")
        salvar_acesso = st.checkbox(
            "💾 Salvar acesso neste dispositivo",
            value=False,
            help="Quando marcado, este navegador entrará automaticamente nas próximas vezes. Não use em computador compartilhado."
        )
        st.caption("🔒 O código de acesso não é armazenado. O app salva apenas o acesso já validado neste navegador.")
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        if st.button("ACESSAR SISTEMA", use_container_width=True, type="primary"):
            codigos_validos = {
                "9999": ("GERAL", "GERÊNCIA", "adm"),
                "7777": ("GERAL", "PROGRAMACAO", "programador"),
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
                
                # Persistência opcional do login.
                # Usamos UM único cookie assinado para evitar corrida entre vários
                # componentes CookieManager e tornar o auto-login confiável.
                if salvar_acesso:
                    expiracao = datetime.now() + timedelta(days=365)
                    token_login = gerar_token_login(nome_formatado, turno_val, setor_val, perfil_val, dias=365)
                    cookie_manager.set(
                        COOKIE_LOGIN,
                        token_login,
                        key="set_auto_login_v2",
                        path="/",
                        expires_at=expiracao,
                        same_site="lax",
                    )
                    # O CookieManager grava no navegador pelo componente JS.
                    # Esta pequena espera acontece SOMENTE no login e evita que o
                    # rerun interrompa a gravação antes de o browser receber o cookie.
                    time.sleep(0.35)
                else:
                    try:
                        if COOKIE_LOGIN in cookies_salvos:
                            cookie_manager.delete(COOKIE_LOGIN, key="del_auto_login_v2")
                    except Exception:
                        pass

                mudar_tela('menu', forcar_rerun=True)
            else: st.error("⚠️ Credenciais inválidas.")

def tela_hub_relatorios():
    botao_navegar("⬅ Voltar ao Menu Principal", 'menu')
    st.markdown("#### 📋 Central de Relatórios e Auditorias")
    st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Selecione qual módulo você deseja acessar.</p>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div style='background-color: #121214; padding: 15px; border: 1px solid #27272A; border-radius: 8px; text-align: center; margin-bottom: 10px;'>
            <h1 style='margin:0;'>📄</h1>
            <h4 style='color: #2DD4BF; margin-top: 10px;'>Relatório de Turno</h4>
            <p style='font-size: 12px; color: #A1A1AA;'>Gerar fechamentos e repasses.</p>
        </div>
        """, unsafe_allow_html=True)
        botao_navegar("ACESSAR RELATÓRIOS", 'relatorio', use_container_width=True, type="primary")
    with col2:
        st.markdown("""
        <div style='background-color: #121214; padding: 15px; border: 1px solid #27272A; border-radius: 8px; text-align: center; margin-bottom: 10px;'>
            <h1 style='margin:0;'>🧹</h1>
            <h4 style='color: #2DD4BF; margin-top: 10px;'>Auditoria LIRS</h4>
            <p style='font-size: 12px; color: #A1A1AA;'>Limpeza e liberação de linha.</p>
        </div>
        """, unsafe_allow_html=True)
        botao_navegar("ACESSAR LIRS", 'lirs', use_container_width=True, type="primary")
def _tela_menu_dashboard_9999():
    exibir_alertas_preset()
    exibir_alertas_preparador()

    status_dict = ler_status_atual()
    estado_meta = _estado_atual_home()
    resumo_afc = _resumo_setor_home(status_dict, 'AFC', TODAS_AFC)
    resumo_rtf = _resumo_setor_home(status_dict, 'RTF', TODAS_RTF)
    chaves_total = ['producao','preparacao','prep_ativa','prep_aguardando','parada','manutencao','outros']
    totais = {chave: resumo_afc[chave] + resumo_rtf[chave] for chave in chaves_total}
    total_maquinas = len(TODAS_AFC) + len(TODAS_RTF)

    agora = datetime.now(FUSO_BR)
    metricas_mes = _metricas_setups_mes_home(agora)
    inicios_ativos = _inicios_preparacao_ativa_home()
    hora = agora.hour
    saudacao = 'Bom dia' if 5 <= hora < 12 else ('Boa tarde' if 12 <= hora < 18 else 'Boa noite')
    nome_raw = str(st.session_state.get('operador', '')).strip()
    primeiro_nome = html.escape(nome_raw.split()[0] if nome_raw else 'Usuário')

    st.markdown(textwrap.dedent(f'''
    <div class="dash-welcome">
        <div>
            <div class="dash-eyebrow">Painel operacional · {html.escape(st.session_state.get('turno',''))}</div>
            <div class="dash-title">{saudacao}, {primeiro_nome}.</div>
            <div class="dash-subtitle">Aqui está o panorama atual da Afiação e Retífica.</div>
        </div>
        <div class="dash-date">{agora.strftime('%d/%m/%Y')} · {agora.strftime('%H:%M')}</div>
    </div>
    <div class="kpi-grid">
        {_render_kpi('Produzindo', totais['producao'], '▶', '#2DD4BF', f'de {total_maquinas} máquinas')}
        {_render_prep_kpi(totais['prep_ativa'], totais['prep_aguardando'])}
        {_render_kpi('Paradas', totais['parada'], '■', '#EF4444', 'requerem acompanhamento')}
        {_render_kpi('Manutenção', totais['manutencao'], '⌁', '#8B5CF6', 'máquinas em manutenção')}
    </div>
    '''), unsafe_allow_html=True)

    preparacoes = {'ativa': [], 'aguardando': []}
    for setor, maquinas in [('AFC', TODAS_AFC), ('RTF', TODAS_RTF)]:
        for maq in maquinas:
            chave = f'{setor} {maq}'
            st_val = status_dict.get(chave, 'PRODUZINDO')
            tipo = _classificar_preparacao_home(st_val)
            if not tipo:
                continue
            meta = estado_meta.get(chave, {})
            if tipo == 'ativa':
                hora_inicio = inicios_ativos.get(chave) or meta.get('hora', '')
                mins = _minutos_status_home(hora_inicio)
                tempo_info = None
                ordem = -mins  # mais antigas primeiro
            else:
                hora_inicio = ''
                mins = 0
                tempo_info = _info_programacao_home(st_val, agora)
                ordem = tempo_info.get('ordem', 10**9)
            preparacoes[tipo].append({
                'setor': setor,
                'maq': maq,
                'status': st_val,
                'hora': hora_inicio,
                'operador': meta.get('operador', ''),
                'mins': mins,
                'tempo_info': tempo_info,
                'ordem': ordem,
            })

    preparacoes['ativa'].sort(key=lambda x: (x['ordem'], x['setor'], x['maq']))
    # Atrasadas primeiro; depois as próximas programações; sem horário ficam no fim.
    preparacoes['aguardando'].sort(key=lambda x: (x['ordem'], x['setor'], x['maq']))

    def contar_prep_setor(tipo, setor):
        return sum(1 for x in preparacoes[tipo] if x['setor'] == setor)

    def montar_lista_setor(tipo, setor, limite=5):
        itens = [x for x in preparacoes[tipo] if x['setor'] == setor]
        if not itens:
            setor_nome = 'Afiação' if setor == 'AFC' else 'Retífica'
            txt = f'Nenhuma preparação de {setor_nome} nesta condição.'
            return f'<div class="prep-empty">{txt}</div>'
        html_itens = ''.join(
            _render_prep_item(
                x['setor'], x['maq'], x['status'], x['hora'], x['operador'], tipo,
                tempo_info=x.get('tempo_info')
            )
            for x in itens[:limite]
        )
        if len(itens) > limite:
            html_itens += f'<div class="prep-more">+ {len(itens)-limite} outra(s) máquina(s) de {setor}</div>'
        return html_itens

    meses_pt = {
        1:'Janeiro',2:'Fevereiro',3:'Março',4:'Abril',5:'Maio',6:'Junho',
        7:'Julho',8:'Agosto',9:'Setembro',10:'Outubro',11:'Novembro',12:'Dezembro'
    }
    qtd_rtf, media_rtf = _media_setor_setup_home(metricas_mes, ['rtf_guia','rtf_haste'])
    qtd_afc, media_afc = _media_setor_setup_home(metricas_mes, ['afc_preparacao','afc_sequencia'])
    media_rtf_txt = _tempo_curto_home(media_rtf) if qtd_rtf else '—'
    media_afc_txt = _tempo_curto_home(media_afc) if qtd_afc else '—'

    # Renderização em blocos separados para evitar que o Markdown interprete o HTML como código.
    col_esq, col_dir = st.columns([0.92, 1.48], gap="medium")

    html_setor = (
        '<div class="dash-panel sector-panel">'
        '<div class="dash-panel-title">Produção por setor</div>'
        '<div class="dash-panel-sub">Máquinas aguardando setup continuam contabilizadas como produção</div>'
        + _render_setor_bar('Afiação', resumo_afc)
        + _render_setor_bar('Retífica', resumo_rtf)
        + '</div>'
    )

    html_medias = (
        '<div class="setup-month-panel setup-month-panel-compact">'
        '<div class="setup-month-top">'
        '<div><div class="setup-month-title">Médias de setup</div>'
        '<div class="setup-month-sub">Quantidade concluída e média do tempo ativo no mês</div></div>'
        f'<div class="setup-month-badge">{meses_pt.get(agora.month, agora.strftime("%m"))} / {agora.year}</div>'
        '</div>'
        '<div class="setup-month-grid setup-month-grid-2x2">'
        + _render_setup_metric_card('Retífica · Guia', metricas_mes['rtf_guia'], 'G', '#60A5FA')
        + _render_setup_metric_card('Retífica · Haste', metricas_mes['rtf_haste'], 'H', '#A78BFA')
        + _render_setup_metric_card('Afiação · Preparação', metricas_mes['afc_preparacao'], 'P', '#2DD4BF')
        + _render_setup_metric_card('Afiação · Sequência', metricas_mes['afc_sequencia'], 'S', '#F59E0B')
        + '</div></div>'
    )

    at_afc = contar_prep_setor('ativa', 'AFC')
    at_rtf = contar_prep_setor('ativa', 'RTF')
    ag_afc = contar_prep_setor('aguardando', 'AFC')
    ag_rtf = contar_prep_setor('aguardando', 'RTF')

    html_preparacoes = (
        '<div class="dash-panel">'
        '<div class="dash-panel-title">Preparações agora</div>'
        '<div class="dash-panel-sub">Afiação e Retífica separadas por situação</div>'
        '<div class="prep-summary">'
        f'<div class="prep-chip active">● Ativas AFC <b>{at_afc}</b></div>'
        f'<div class="prep-chip active">● Ativas RTF <b>{at_rtf}</b></div>'
        f'<div class="prep-chip waiting">◷ Aguard. AFC <b>{ag_afc}</b></div>'
        f'<div class="prep-chip waiting">◷ Aguard. RTF <b>{ag_rtf}</b></div>'
        '</div>'
        f'<div class="prep-section-title"><span>▶ Preparação ativa</span><span class="prep-section-count">{totais["prep_ativa"]}</span></div>'
        '<div class="prep-sector-block">'
        f'<div class="prep-sector-head"><span class="prep-sector-name afc">Afiação · AFC</span><span class="prep-sector-count">{at_afc}</span></div>'
        f'<div class="prep-list">{montar_lista_setor("ativa", "AFC")}</div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name rtf">Retífica · RTF</span><span class="prep-sector-count">{at_rtf}</span></div>'
        f'<div class="prep-list">{montar_lista_setor("ativa", "RTF")}</div>'
        '</div>'
        f'<div class="prep-section-title"><span>◷ Aguardando preparação</span><span class="prep-section-count">{totais["prep_aguardando"]}</span></div>'
        '<div class="prep-sector-block">'
        f'<div class="prep-sector-head"><span class="prep-sector-name afc">Afiação · AFC</span><span class="prep-sector-count">{ag_afc}</span></div>'
        f'<div class="prep-list">{montar_lista_setor("aguardando", "AFC")}</div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name rtf">Retífica · RTF</span><span class="prep-sector-count">{ag_rtf}</span></div>'
        f'<div class="prep-list">{montar_lista_setor("aguardando", "RTF")}</div>'
        '</div>'
        '</div>'
    )

    with col_esq:
        st.markdown(html_setor, unsafe_allow_html=True)
        st.markdown(html_medias, unsafe_allow_html=True)

    with col_dir:
        st.markdown(html_preparacoes, unsafe_allow_html=True)

    perfil = st.session_state.get('perfil', '')
    acoes = _acoes_rapidas_home(perfil)
    if acoes:
        st.markdown('<div class="quick-title">Acessos rápidos</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(acoes),4))
        for i, (rotulo, destino) in enumerate(acoes):
            cols[i % len(cols)].button(
                rotulo,
                key=f'home_quick_{destino}',
                use_container_width=True,
                on_click=mudar_tela,
                args=(destino,)
            )

    st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)
    if st.button("🚪 Encerrar sessão", key='logout_home', use_container_width=True):
        st.session_state['logout_realizado'] = True
        st.session_state['operador'], st.session_state['turno'], st.session_state['setor_usuario'], st.session_state['perfil'] = '', '', '', ''
        try:
            if COOKIE_LOGIN in (cookie_manager.cookies or {}):
                cookie_manager.delete(COOKIE_LOGIN, key="del_auto_login_logout")
            for nome_cookie, chave in [
                ("salvar_acesso", "del_salvar_acesso_antigo"),
                ("user_logado", "del_logado_antigo"),
                ("user_turno", "del_turno_antigo"),
                ("user_setor", "del_setor_antigo"),
                ("user_perfil", "del_perfil_antigo"),
            ]:
                try:
                    if nome_cookie in (cookie_manager.cookies or {}):
                        cookie_manager.delete(nome_cookie, key=chave)
                except Exception:
                    pass
        except Exception:
            pass
        mudar_tela('login', forcar_rerun=True)



def _tela_menu_classico():
    """Menu original para todos os acessos que não são o 9999/Gerência."""
    exibir_alertas_preset()
    exibir_alertas_preparador()
    perfil = st.session_state['perfil']
    if perfil == 'adm':
        setor_txt = "Gerência"
    elif st.session_state['setor_usuario'] == 'TECNICO':
        setor_txt = "Técnico (Geral)"
    elif perfil == 'preset':
        setor_txt = "Pré-Set"
    elif perfil == 'programador':
        setor_txt = "Programação CNC"
    else:
        setor_txt = 'Afiação' if st.session_state['setor_usuario'] == 'AFC' else 'Retífica'

    st.markdown(f"""
    <div class='classic-user-card'>
        <p class='classic-user-label'>Usuário logado</p>
        <p class='classic-user-name'>{html.escape(str(st.session_state['operador']))}</p>
        <p class='classic-user-meta'>{html.escape(str(st.session_state['turno']))} • {html.escape(setor_txt)}</p>
    </div>
    """, unsafe_allow_html=True)

    if perfil == 'adm':
        botao_navegar("📊 VISÃO GERAL DE FÁBRICA", 'visao_geral', use_container_width=True, type="primary")
        botao_navegar("💻 PAINEL DO PROGRAMADOR", 'programador', use_container_width=True)
        botao_navegar("⚙️ ACESSAR MÓDULO AFIAÇÃO", 'afc', use_container_width=True)
        botao_navegar("⚙ ACESSAR MÓDULO RETÍFICA", 'rtf', use_container_width=True)
        botao_navegar("🗄️ GERENCIAR ARMÁRIOS", 'armarios', use_container_width=True)
        botao_navegar("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", 'checkup', use_container_width=True)
        botao_navegar("👥 CONTROLE DE EQUIPE", 'equipe', use_container_width=True)
        botao_navegar("📋 RELATÓRIOS E LIRS", 'hub_relatorios', use_container_width=True)
        botao_navegar("📊 HISTÓRICOS E EXPORTAÇÕES", 'historico', use_container_width=True)
        botao_navegar("✏️ GERENCIAR BANCO DE DADOS", 'editar', use_container_width=True)
    elif perfil == 'preset':
        botao_navegar("📊 VISÃO GERAL DE FÁBRICA", 'visao_geral', use_container_width=True, type="primary")
        botao_navegar("💻 PAINEL DO PROGRAMADOR", 'programador', use_container_width=True)
        botao_navegar("🗄 GERENCIAR ARMÁRIOS", 'armarios', use_container_width=True)
        botao_navegar("🔍 PROGRAMAÇÃO DO SETOR", 'checkup', use_container_width=True)
    elif perfil == 'programador':
        botao_navegar("📊 VISÃO GERAL DE FÁBRICA", 'visao_geral', use_container_width=True, type="primary")
        botao_navegar("💻 PAINEL DO PROGRAMADOR", 'programador', use_container_width=True, type="primary")
        botao_navegar("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", 'checkup', use_container_width=True)
        botao_navegar("👥 CONTROLE DE EQUIPE", 'equipe', use_container_width=True)
    elif perfil == 'preparador':
        botao_navegar("📊 VISÃO GERAL DE FÁBRICA", 'visao_geral', use_container_width=True, type="primary")
        if st.session_state['setor_usuario'] in ['AFC', 'TECNICO']:
            botao_navegar("⚙️ ACESSAR MÓDULO AFIAÇÃO", 'afc', use_container_width=True)
        if st.session_state['setor_usuario'] in ['RTF', 'TECNICO']:
            botao_navegar("⚙ ACESSAR MÓDULO RETÍFICA", 'rtf', use_container_width=True)
        botao_navegar("🗄️ VISÃO DOS ARMÁRIOS", 'armarios', use_container_width=True)
        botao_navegar("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", 'checkup', use_container_width=True)
        botao_navegar("⚡ MINHAS INCIDÊNCIAS", 'minhas_incidencias', use_container_width=True)
        botao_navegar("👥 CONTROLE DE EQUIPE", 'equipe', use_container_width=True)
        botao_navegar("📋 RELATÓRIOS E LIRS", 'hub_relatorios', use_container_width=True)
        botao_navegar("✏️ CORREÇÃO DE APONTAMENTOS", 'editar', use_container_width=True)
    else:
        botao_navegar("📊 VISÃO GERAL DE FÁBRICA", 'visao_geral', use_container_width=True, type="primary")
        botao_navegar("🔍 PROGRAMAÇÃO E INCIDÊNCIAS", 'checkup', use_container_width=True)
        botao_navegar("📋 RELATÓRIOS E LIRS", 'hub_relatorios', use_container_width=True)
        botao_navegar("✏️ CORREÇÃO DE APONTAMENTOS", 'editar', use_container_width=True)

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    if st.button("🚪 Encerramento de Sessão (Logout)", use_container_width=True, key='logout_menu_classico'):
        st.session_state['logout_realizado'] = True
        st.session_state['operador'], st.session_state['turno'], st.session_state['setor_usuario'], st.session_state['perfil'] = '', '', '', ''
        try:
            if COOKIE_LOGIN in (cookie_manager.cookies or {}):
                cookie_manager.delete(COOKIE_LOGIN, key="del_auto_login_logout_classico")
            for nome_cookie, chave in [
                ("salvar_acesso", "del_salvar_acesso_antigo_classico"),
                ("user_logado", "del_logado_antigo_classico"),
                ("user_turno", "del_turno_antigo_classico"),
                ("user_setor", "del_setor_antigo_classico"),
                ("user_perfil", "del_perfil_antigo_classico"),
            ]:
                if nome_cookie in (cookie_manager.cookies or {}):
                    cookie_manager.delete(nome_cookie, key=chave)
        except Exception:
            pass
        mudar_tela('login', forcar_rerun=True)



def _tela_menu_dashboard_preset():
    # Dashboard operacional do Pré-Set (4040/5050/6060).
    # As médias/analytics gerenciais continuam exclusivas do 9999.
    exibir_alertas_preset()

    status_dict = ler_status_atual()
    estado_meta = _estado_atual_home()
    resumo_afc = _resumo_setor_home(status_dict, 'AFC', TODAS_AFC)
    resumo_rtf = _resumo_setor_home(status_dict, 'RTF', TODAS_RTF)
    totais = {
        chave: resumo_afc[chave] + resumo_rtf[chave]
        for chave in ['producao','preparacao','prep_ativa','prep_aguardando','parada','manutencao','outros']
    }

    agora = datetime.now(FUSO_BR)
    inicios_ativos = _inicios_preparacao_ativa_home()
    hora = agora.hour
    saudacao = 'Bom dia' if 5 <= hora < 12 else ('Boa tarde' if 12 <= hora < 18 else 'Boa noite')
    nome_raw = str(st.session_state.get('operador', '')).strip()
    primeiro_nome = html.escape(nome_raw.split()[0] if nome_raw else 'Pré-Set')

    com_rebolo = 0
    for setor, maquinas in [('AFC', TODAS_AFC), ('RTF', TODAS_RTF)]:
        for maq in maquinas:
            st_val = str(status_dict.get(f'{setor} {maq}', 'PRODUZINDO'))
            if '(C/ REBOLO)' in st_val.upper() and _classificar_preparacao_home(st_val):
                com_rebolo += 1

    arm_total = arm_ocup = arm_livres = 0
    arm_afc_total = arm_afc_ocup = 0
    arm_rtf_total = arm_rtf_ocup = 0
    try:
        inicializar_armarios()
        if os.path.exists(ARQUIVO_ARMARIOS):
            df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str).fillna('')
            if not df_arm.empty:
                status_arm = df_arm.get('Status', pd.Series('', index=df_arm.index)).astype(str).str.upper().str.strip()
                ocup_mask = status_arm.ne('VAZIO')
                arm_total = len(df_arm)
                arm_ocup = int(ocup_mask.sum())
                arm_livres = max(0, arm_total - arm_ocup)
                armario_col = df_arm.get('Armario', pd.Series('', index=df_arm.index)).astype(str)
                mask_afc = armario_col.str.contains('AFIADOR', case=False, na=False)
                mask_rtf = armario_col.str.contains('RETÍF', case=False, na=False) | armario_col.str.contains('RETIF', case=False, na=False)
                arm_afc_total = int(mask_afc.sum())
                arm_afc_ocup = int((mask_afc & ocup_mask).sum())
                arm_rtf_total = int(mask_rtf.sum())
                arm_rtf_ocup = int((mask_rtf & ocup_mask).sum())
    except Exception:
        pass

    st.markdown(textwrap.dedent(f'''
    <div class="dash-welcome">
        <div>
            <div class="dash-eyebrow">Painel Pré-Set · {html.escape(st.session_state.get('turno',''))}</div>
            <div class="dash-title">{saudacao}, {primeiro_nome}.</div>
            <div class="dash-subtitle">Preparações, rebolos e armários que precisam da sua atenção.</div>
        </div>
        <div class="dash-date">{agora.strftime('%d/%m/%Y')} · {agora.strftime('%H:%M')}</div>
    </div>
    <div class="kpi-grid">
        {_render_kpi('Prep. ativas', totais['prep_ativa'], '▶', '#2DD4BF', 'setup em execução')}
        {_render_kpi('Aguardando', totais['prep_aguardando'], '◷', '#F59E0B', 'máquinas ainda em produção')}
        {_render_kpi('Com rebolo', com_rebolo, '◉', '#60A5FA', 'setups atuais com troca de rebolo')}
        {_render_kpi('Armários ocupados', arm_ocup, '▣', '#A78BFA', f'{arm_livres} posições livres')}
    </div>
    '''), unsafe_allow_html=True)

    preparacoes = {'ativa': [], 'aguardando': []}
    for setor, maquinas in [('AFC', TODAS_AFC), ('RTF', TODAS_RTF)]:
        for maq in maquinas:
            chave = f'{setor} {maq}'
            st_val = status_dict.get(chave, 'PRODUZINDO')
            tipo = _classificar_preparacao_home(st_val)
            if not tipo:
                continue
            meta = estado_meta.get(chave, {})
            if tipo == 'ativa':
                hora_inicio = inicios_ativos.get(chave) or meta.get('hora', '')
                mins = _minutos_status_home(hora_inicio)
                tempo_info = None
                ordem = -mins
            else:
                hora_inicio = ''
                tempo_info = _info_programacao_home(st_val, agora)
                ordem = tempo_info.get('ordem', 10**9)
            preparacoes[tipo].append({
                'setor': setor,
                'maq': maq,
                'status': st_val,
                'hora': hora_inicio,
                'operador': meta.get('operador', ''),
                'tempo_info': tempo_info,
                'ordem': ordem,
            })

    preparacoes['ativa'].sort(key=lambda x: (x['ordem'], x['setor'], x['maq']))
    preparacoes['aguardando'].sort(key=lambda x: (x['ordem'], x['setor'], x['maq']))

    def contar_prep_setor_preset(tipo, setor):
        return sum(1 for x in preparacoes[tipo] if x['setor'] == setor)

    def montar_lista_preset_setor(tipo, setor, limite=6):
        itens = [x for x in preparacoes[tipo] if x['setor'] == setor]
        if not itens:
            setor_nome = 'Afiação' if setor == 'AFC' else 'Retífica'
            txt = f'Nenhuma preparação de {setor_nome} nesta condição.'
            return f'<div class="prep-empty">{txt}</div>'
        blocos = []
        for x in itens[:limite]:
            blocos.append(_render_prep_item(
                x['setor'], x['maq'], x['status'], x['hora'], x['operador'], tipo,
                tempo_info=x.get('tempo_info')
            ))
        if len(itens) > limite:
            blocos.append(f'<div class="prep-more">+ {len(itens)-limite} outra(s) máquina(s) de {setor}</div>')
        return ''.join(blocos)

    html_setor = (
        '<div class="dash-panel sector-panel">'
        '<div class="dash-panel-title">Produção por setor</div>'
        '<div class="dash-panel-sub">Máquinas aguardando setup continuam contabilizadas como produção</div>'
        + _render_setor_bar('Afiação', resumo_afc)
        + _render_setor_bar('Retífica', resumo_rtf)
        + '</div>'
    )

    pct_arm = round((arm_ocup / arm_total) * 100) if arm_total else 0
    pct_afc = round((arm_afc_ocup / max(1, arm_afc_total)) * 100)
    pct_rtf = round((arm_rtf_ocup / max(1, arm_rtf_total)) * 100)
    html_armarios = (
        '<div class="dash-panel">'
        '<div class="dash-panel-title">Situação dos armários</div>'
        '<div class="dash-panel-sub">Posições com setup/ferramental armazenado</div>'
        f'<div class="sector-row"><div class="sector-name">Afiadoras</div>'
        f'<div class="sector-track"><div class="sector-fill" style="width:{pct_afc}%"></div></div>'
        f'<div class="sector-pct">{arm_afc_ocup}/{arm_afc_total}</div></div>'
        f'<div class="sector-row"><div class="sector-name">Retíficas</div>'
        f'<div class="sector-track"><div class="sector-fill" style="width:{pct_rtf}%"></div></div>'
        f'<div class="sector-pct">{arm_rtf_ocup}/{arm_rtf_total}</div></div>'
        f'<div class="sector-mini" style="margin-left:0"><span>Ocupadas <b>{arm_ocup}</b></span><span>Livres <b>{arm_livres}</b></span><span>Uso <b>{pct_arm}%</b></span></div>'
        '</div>'
    )

    at_afc = contar_prep_setor_preset('ativa', 'AFC')
    at_rtf = contar_prep_setor_preset('ativa', 'RTF')
    ag_afc = contar_prep_setor_preset('aguardando', 'AFC')
    ag_rtf = contar_prep_setor_preset('aguardando', 'RTF')

    html_preparacoes = (
        '<div class="dash-panel">'
        '<div class="dash-panel-title">Preparações agora</div>'
        '<div class="dash-panel-sub">Prioridades do Pré-Set separadas por setor</div>'
        '<div class="prep-summary">'
        f'<div class="prep-chip active">● Ativas AFC <b>{at_afc}</b></div>'
        f'<div class="prep-chip active">● Ativas RTF <b>{at_rtf}</b></div>'
        f'<div class="prep-chip waiting">◷ Aguard. AFC <b>{ag_afc}</b></div>'
        f'<div class="prep-chip waiting">◷ Aguard. RTF <b>{ag_rtf}</b></div>'
        '</div>'
        f'<div class="prep-section-title"><span>▶ Preparação ativa</span><span class="prep-section-count">{totais["prep_ativa"]}</span></div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name afc">Afiação · AFC</span><span class="prep-sector-count">{at_afc}</span></div>'
        f'<div class="prep-list">{montar_lista_preset_setor("ativa", "AFC")}</div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name rtf">Retífica · RTF</span><span class="prep-sector-count">{at_rtf}</span></div>'
        f'<div class="prep-list">{montar_lista_preset_setor("ativa", "RTF")}</div>'
        f'<div class="prep-section-title"><span>◷ Aguardando preparação</span><span class="prep-section-count">{totais["prep_aguardando"]}</span></div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name afc">Afiação · AFC</span><span class="prep-sector-count">{ag_afc}</span></div>'
        f'<div class="prep-list">{montar_lista_preset_setor("aguardando", "AFC")}</div>'
        f'<div class="prep-sector-head"><span class="prep-sector-name rtf">Retífica · RTF</span><span class="prep-sector-count">{ag_rtf}</span></div>'
        f'<div class="prep-list">{montar_lista_preset_setor("aguardando", "RTF")}</div>'
        '</div>'
    )

    col_esq, col_dir = st.columns([0.92, 1.48], gap='medium')
    with col_esq:
        st.markdown(html_setor, unsafe_allow_html=True)
        st.markdown(html_armarios, unsafe_allow_html=True)
    with col_dir:
        st.markdown(html_preparacoes, unsafe_allow_html=True)

    st.markdown('<div class="quick-title">Acessos rápidos</div>', unsafe_allow_html=True)
    acoes = [
        ('🗄 Gerenciar armários', 'armarios'),
        ('🔍 Programação do setor', 'checkup'),
        ('💻 Painel do programador', 'programador'),
        ('📊 Visão geral', 'visao_geral'),
    ]
    cols = st.columns(4)
    for i, (rotulo, destino) in enumerate(acoes):
        cols[i].button(rotulo, key=f'preset_dash_quick_{destino}', use_container_width=True,
                       on_click=mudar_tela, args=(destino,))

    st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)
    if st.button('🚪 Encerrar sessão', key='logout_home_preset', use_container_width=True):
        st.session_state['logout_realizado'] = True
        st.session_state['operador'], st.session_state['turno'], st.session_state['setor_usuario'], st.session_state['perfil'] = '', '', '', ''
        try:
            if COOKIE_LOGIN in (cookie_manager.cookies or {}):
                cookie_manager.delete(COOKIE_LOGIN, key='del_auto_login_logout_preset')
        except Exception:
            pass
        mudar_tela('login', forcar_rerun=True)

def tela_menu():
    """Home por perfil: Gerência 9999, Pré-Set e menu clássico para os demais."""
    eh_9999 = (
        st.session_state.get('perfil') == 'adm'
        and str(st.session_state.get('setor_usuario', '')).upper() == 'GERÊNCIA'
    )
    if eh_9999:
        return _tela_menu_dashboard_9999()
    if st.session_state.get('perfil') == 'preset':
        return _tela_menu_dashboard_preset()
    return _tela_menu_classico()

def _extrair_op_item_gerencia(status):
    status = str(status or '')
    op = '-'
    item = '-'
    if '[Ordem:' in status:
        try: op = status.split('[Ordem:')[1].split(']')[0].strip() or '-'
        except Exception: pass
    for marcador in ['[Novo Item:', '[Item Atual:', '[Item:']:
        if marcador in status:
            try:
                valor = status.split(marcador)[1].split(']')[0].strip()
                if valor:
                    item = valor
                    break
            except Exception:
                pass
    return op, item


def _tipo_explicito_rtf(status):
    up = _normalizar_setup_home(status)
    if '[PROCESSO: GUIA]' in up or 'PREPARACAO - GUIA' in up or ' GUIA' in up:
        return 'GUIA'
    if '[PROCESSO: HASTE]' in up or 'PREPARACAO - HASTE' in up or ' HASTE' in up:
        return 'HASTE'
    return None


def _mapa_processo_rodando_rtf(status_dict):
    # Programação futura não troca o processo em execução. O grupo só muda quando PREPARANDO inicia.
    tipos_cnc = ler_tipos_cnc()
    ativo = {}
    pendente = {}

    for maq in TODAS_RTF:
        tipo_cnc = tipos_cnc.get(maq, 'RTF_CNC3')
        if tipo_cnc == 'RTF_CNC2':
            ativo[maq] = 'FACETADORA'
        elif tipo_cnc == 'RTF_CNC1':
            ativo[maq] = 'HASTE'

    def processar_eventos(df):
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            maq_full = str(row.get('Maquina', ''))
            if not maq_full.startswith('RTF '):
                continue
            maq = maq_full.replace('RTF ', '', 1).strip()
            if tipos_cnc.get(maq, 'RTF_CNC3') == 'RTF_CNC2':
                ativo[maq] = 'FACETADORA'
                continue
            st_raw = str(row.get('Status', ''))
            st_up = _normalizar_setup_home(st_raw)
            tipo = _tipo_explicito_rtf(st_raw)
            if tipo:
                pendente[maq] = tipo
                if st_up.startswith('PRODUZINDO') and '[PROCESSO:' in st_up:
                    ativo[maq] = tipo
            if st_up.startswith('PREPARANDO'):
                tipo_inicio = tipo or pendente.get(maq)
                if tipo_inicio:
                    ativo[maq] = tipo_inicio

    try:
        hist = _quote_identifier(ARQUIVO_HISTORICO_EVENTOS)
        if tabela_existe(ARQUIVO_HISTORICO_EVENTOS):
            sql_hist = f'''SELECT "Maquina", "Status", "Hora" FROM {hist}
                WHERE "Setor"='RTF'
                  AND (UPPER("Status") LIKE '%HASTE%'
                       OR UPPER("Status") LIKE '%GUIA%'
                       OR UPPER("Status") LIKE 'PREPARANDO%'
                       OR UPPER("Status") LIKE 'PRODUZINDO%')
                ORDER BY rowid DESC LIMIT 5000'''
            result = turso_request(sql_hist, want_rows=True, timeout=30)
            df_hist = _resultado_turso_df(result)
            if not df_hist.empty:
                processar_eventos(df_hist.iloc[::-1].reset_index(drop=True))
    except Exception:
        pass

    try:
        atual = _quote_identifier(ARQUIVO_DADOS)
        if tabela_existe(ARQUIVO_DADOS):
            sql_atual = f'''SELECT "Maquina", "Status", "Hora" FROM {atual}
                WHERE "Setor"='RTF' ORDER BY rowid ASC'''
            result = turso_request(sql_atual, want_rows=True, timeout=30)
            processar_eventos(_resultado_turso_df(result))
    except Exception:
        pass

    for maq in TODAS_RTF:
        if tipos_cnc.get(maq, 'RTF_CNC3') == 'RTF_CNC2':
            ativo[maq] = 'FACETADORA'
            continue
        if maq not in ativo:
            atual_st = status_dict.get(f'RTF {maq}', '')
            tipo_atual = _tipo_explicito_rtf(atual_st)
            if str(atual_st).upper().startswith('PREPARANDO') and tipo_atual:
                ativo[maq] = tipo_atual
            else:
                ativo[maq] = 'HASTE'
    return ativo


def _estado_gerencial_maquina(status):
    up = _normalizar_setup_home(status)
    if up.startswith('MANUTENCAO'):
        return 'MANUTENÇÃO', '#F97316'
    if up.startswith('PARADA'):
        return 'PARADA', '#EF4444'
    if up.startswith('PREPARANDO'):
        return 'SETUP ATIVO', '#2DD4BF'
    if _eh_aguardando_setup_home(status):
        return 'RODANDO · SETUP AGUARDANDO', '#F59E0B'
    return 'PRODUZINDO', '#22C55E'


def _proxima_programacao_gerencia(status):
    if not _eh_aguardando_setup_home(status):
        return ''
    tipo = _tipo_explicito_rtf(status)
    if not tipo:
        up = _normalizar_setup_home(status)
        if 'SEQUENCIA' in up: tipo = 'SEQUÊNCIA'
        elif 'PREPARACAO' in up: tipo = 'PREPARAÇÃO'
    hora = _extrair_hora_programada_home(status)
    partes = []
    if tipo: partes.append(tipo)
    if hora: partes.append(hora)
    return ' · '.join(partes)


def _render_grupo_gerencia(nome, maquinas, setor, status_dict, cor):
    cards = []
    for maq in ordenar_maquinas(maquinas):
        st_val = status_dict.get(f'{setor} {maq}', 'PRODUZINDO')
        op, item = _extrair_op_item_gerencia(st_val)
        estado, cor_estado = _estado_gerencial_maquina(st_val)
        prox = _proxima_programacao_gerencia(st_val)
        if prox:
            prox_html = f'<div class="mgr-next">Próximo setup: <b>{html.escape(prox)}</b></div>'
        else:
            prox_html = '<div class="mgr-next">Sem setup futuro programado</div>'
        cards.append(f'''<div class="mgr-machine" style="--state-color:{cor_estado}">
            <div class="mgr-machine-top">
                <div class="mgr-machine-name">Máquina {html.escape(str(maq))}</div>
                <div class="mgr-state">{html.escape(estado)}</div>
            </div>
            <div class="mgr-machine-data">
                <div class="mgr-data-box"><span>Item rodando</span><b>{html.escape(str(item))}</b></div>
                <div class="mgr-data-box"><span>OP</span><b>{html.escape(str(op))}</b></div>
            </div>
            {prox_html}
        </div>''')
    corpo = ''.join(cards) if cards else '<div class="mgr-empty">Nenhuma máquina nesta categoria.</div>'
    return f'''<div class="mgr-process" style="--mgr-color:{cor}">
        <div class="mgr-process-head">
            <div class="mgr-process-name"><span class="mgr-process-dot"></span>{html.escape(nome)}</div>
            <div class="mgr-process-count">{len(maquinas)} máquinas</div>
        </div>
        <div class="mgr-machine-grid">{corpo}</div>
    </div>'''


def tela_visao_geral():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
    status_dict = ler_status_atual()

    if (st.session_state.get('perfil') == 'adm' and str(st.session_state.get('setor_usuario', '')).upper() == 'GERÊNCIA'):
        mapa_rtf = _mapa_processo_rodando_rtf(status_dict)
        tipos_cnc = ler_tipos_cnc()
        afiadoras = list(TODAS_AFC)
        facetadoras = [m for m in TODAS_RTF if tipos_cnc.get(m, 'RTF_CNC3') == 'RTF_CNC2']
        ret_haste = [m for m in TODAS_RTF if m not in facetadoras and mapa_rtf.get(m) == 'HASTE']
        ret_guia = [m for m in TODAS_RTF if m not in facetadoras and mapa_rtf.get(m) == 'GUIA']

        grupos = [
            ('Afiadoras', afiadoras, 'AFC', '#8B5CF6'),
            ('Retífica Haste', ret_haste, 'RTF', '#A78BFA'),
            ('Retífica Guia', ret_guia, 'RTF', '#60A5FA'),
            ('Facetadoras', facetadoras, 'RTF', '#2DD4BF'),
        ]

        def resumo_status(lista, setor):
            prod = prep = espera = problema = 0
            for m in lista:
                s = status_dict.get(f'{setor} {m}', 'PRODUZINDO')
                up = _normalizar_setup_home(s)
                if up.startswith('PREPARANDO'):
                    prep += 1
                elif up.startswith('PARADA') or up.startswith('MANUTENCAO'):
                    problema += 1
                elif _eh_aguardando_setup_home(s):
                    espera += 1
                    prod += 1
                else:
                    prod += 1
            return prod, prep, espera, problema

        summary_html = []
        for nome, lista, setor, cor in grupos:
            prod, prep, espera, problema = resumo_status(lista, setor)
            summary_html.append(f'''<div class="mgr-summary-card" style="border-top:2px solid {cor}">
                <div class="mgr-summary-label">{html.escape(nome)}</div>
                <div class="mgr-summary-num">{len(lista)}</div>
                <div class="mgr-summary-meta">{prod} rodando · {prep} setup ativo · {espera} aguardando · {problema} parada/manut.</div>
            </div>''')

        conteudo = f'''
        <div class="mgr-intro">
            <div>
                <div class="mgr-title">Visão Geral da Fábrica</div>
                <div class="mgr-sub">Separado pelo processo que está realmente rodando. Uma programação futura não muda o grupo da máquina até o setup iniciar.</div>
            </div>
        </div>
        <div class="mgr-summary">{''.join(summary_html)}</div>
        {_render_grupo_gerencia('Afiadoras', afiadoras, 'AFC', status_dict, '#8B5CF6')}
        {_render_grupo_gerencia('Retífica Haste', ret_haste, 'RTF', status_dict, '#A78BFA')}
        {_render_grupo_gerencia('Retífica Guia', ret_guia, 'RTF', status_dict, '#60A5FA')}
        {_render_grupo_gerencia('Facetadoras', facetadoras, 'RTF', status_dict, '#2DD4BF')}
        '''
        st.markdown(textwrap.dedent(conteudo), unsafe_allow_html=True)
        return

    st.markdown("#### 📊 Visão Geral da Fábrica — Máquinas e OPs")
    st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Acompanhe em tempo real o status, os itens rodando e as ordens de produção em todas as máquinas da Afiação e Retífica.</p>", unsafe_allow_html=True)
    st.divider()
    setor_filtro = st.radio("Filtrar Setor:", ["Todos", "Afiação (AFC)", "Retífica (RTF)"], horizontal=True)
    listas_analise = []
    if setor_filtro in ["Todos", "Afiação (AFC)"]:
        listas_analise.append(("Afiação (AFC)", TODAS_AFC))
    if setor_filtro in ["Todos", "Retífica (RTF)"]:
        listas_analise.append(("Retífica (RTF)", TODAS_RTF))
    for nome_setor, lista_maq in listas_analise:
        st.markdown(f"##### 🏭 {nome_setor}")
        for m in ordenar_maquinas(lista_maq):
            prefixo = "AFC" if "Afiação" in nome_setor else "RTF"
            st_val = status_dict.get(f"{prefixo} {m}", "PRODUZINDO")
            icone = get_status_icon(st_val)
            op_rodando, item_rodando = _extrair_op_item_gerencia(st_val)
            bloco = f'''<div style="background-color:#18181B;padding:10px;border-radius:8px;margin-bottom:8px;border:1px solid #27272A;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:14px;font-weight:bold;color:#2DD4BF;">{icone} Máquina {m}</span>
                    <span style="font-size:12px;color:#A1A1AA;background:#27272A;padding:2px 8px;border-radius:4px;">{st_val.split('[')[0].strip()}</span>
                </div>
                <div style="margin-top:6px;font-size:13px;color:#F4F4F5;">📦 Item: <b>{item_rodando}</b> | 📋 OP: <b>{op_rodando}</b></div>
            </div>'''
            st.markdown(bloco, unsafe_allow_html=True)
        st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)

def render_grid_vertical(lista_maquinas, setor, status_dict):
    for maq in ordenar_maquinas(lista_maquinas):
        if maq != "":
            chave_busca = f"{setor} {maq}"
            status_atual = status_dict.get(chave_busca, "PRODUZINDO")
            icone = get_status_icon(status_atual)
            label_botao = f"{icone} Máquina {maq} — {status_atual}"
            st.button(label_botao, key=f"btn_vert_{setor}_{maq}", use_container_width=True, on_click=definir_estados, args=({'maq_ativa': maq, 'setor_ativo': setor},))

def tela_checkup():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
    st.markdown("#### 🔍 Programação e Incidências")
    st.divider()
    
    status_dict = ler_status_atual()
    perfil = st.session_state['perfil']
    setor_atual = st.session_state['setor_usuario']
    turno_vigente_real = turno_atual_horario()
    
    if setor_atual in ['TECNICO', 'GERAL', 'GERÊNCIA', 'PRESET', 'PROGRAMACAO'] or perfil == 'adm': 
        setores_alvo = [("AFC", TODAS_AFC), ("RTF", TODAS_RTF)]
    else: 
        setores_alvo = [(setor_atual, TODAS_AFC if setor_atual == "AFC" else TODAS_RTF)]
        
    incidencias_turno_atual = []
    preparacoes_futuras = {"1° TURNO": [], "2° TURNO": [], "3° TURNO": []}
    
    for s_nome, lista in setores_alvo:
        for m in lista:
            st_val = status_dict.get(f"{s_nome} {m}", "PRODUZINDO")
            if "PRODUZINDO" not in st_val or "AGENDADO" in st_val or "AGENDADA" in st_val or "AGUARDANDO" in st_val or "[Fim Previsto:" in st_val:
                turno_pendencia = turno_vigente_real 
                h_alvo = ""
                if "AGENDADA PARA" in st_val:
                    try: h_alvo = st_val.split("AGENDADA PARA")[1].strip().split(" ")[0]
                    except: pass
                elif "[AGENDADO:" in st_val:
                    try: h_alvo = st_val.split("[AGENDADO:")[1].split("]")[0].strip()
                    except: pass
                elif "[Fim Previsto:" in st_val:
                    try: h_alvo = st_val.split("[Fim Previsto:")[1].split("]")[0].strip()
                    except: pass
                    
                if h_alvo: turno_pendencia = obter_turno_por_horario(h_alvo)
                item_lista = (s_nome, m, st_val)
                is_agendamento_ou_prev = "AGENDADA PARA" in st_val or "[AGENDADO:" in st_val or "[Fim Previsto:" in st_val
                
                is_futuro_real = False
                if is_agendamento_ou_prev and h_alvo:
                    try:
                        agora_dt = datetime.now(FUSO_BR)
                        h_alvo_dt = datetime.strptime(h_alvo, "%H:%M").replace(year=agora_dt.year, month=agora_dt.month, day=agora_dt.day, tzinfo=FUSO_BR)
                        if h_alvo_dt < agora_dt and (agora_dt - h_alvo_dt).total_seconds() > 12 * 3600: h_alvo_dt += timedelta(days=1)
                        elif h_alvo_dt > agora_dt and (h_alvo_dt - agora_dt).total_seconds() > 12 * 3600: h_alvo_dt -= timedelta(days=1)
                        delta_mins = (h_alvo_dt - agora_dt).total_seconds() / 60
                        if delta_mins > -10 and turno_pendencia != turno_vigente_real: is_futuro_real = True
                    except: pass
                
                if is_futuro_real:
                    if turno_pendencia in preparacoes_futuras: preparacoes_futuras[turno_pendencia].append(item_lista)
                else:
                    if "PRODUZINDO" not in st_val or "[Fim Previsto:" in st_val: incidencias_turno_atual.append(item_lista)

    def renderizar_post_its_preset(lista_incidencias):
        if not lista_incidencias:
            st.success("✨ Nenhuma máquina na fila no momento.")
            return

        st.markdown("""
        <style>
            .postit-card, .postit-card div, .postit-card span, .postit-card strong, .postit-card p, .postit-card b {
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
            }
        </style>
        """, unsafe_allow_html=True)

        df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str) if os.path.exists(ARQUIVO_ARMARIOS) else pd.DataFrame()
        df_rebolos = pd.DataFrame()
        if os.path.exists(ARQUIVO_REBOLOS):
            try:
                df_rebolos = pd.read_excel(ARQUIVO_REBOLOS, sheet_name='Banco De Rebolos', engine='openpyxl')
                df_rebolos.columns = [unicodedata.normalize('NFKD', str(c).upper()).encode('ASCII', 'ignore').decode('ASCII').replace(" ", "").replace("\n", "").strip() for c in df_rebolos.columns]
                if 'ITEM' in df_rebolos.columns:
                    df_rebolos['ITEM_BUSCA'] = df_rebolos['ITEM'].astype(str).str.upper().apply(lambda x: re.sub(r'\.0$', '', x.strip()).lstrip("0"))
            except: pass

        lista_afc = [item for item in lista_incidencias if item[0] == "AFC"]
        lista_rtf = [item for item in lista_incidencias if item[0] == "RTF"]

        def render_grid_setor(lista_setor, titulo_setor):
            if not lista_setor: return
            
            st.markdown(f"<h5 style='color: #2DD4BF; margin-top: 20px; border-bottom: 2px solid #27272A; padding-bottom: 8px;'>🏭 {titulo_setor}</h5>", unsafe_allow_html=True)
            
            for i in range(0, len(lista_setor), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(lista_setor):
                        setor_m, maq_m, st_m = lista_setor[i + j]

                        is_seq = "SEQUÊNCIA" in st_m.upper() or "SEQUENCIA" in st_m.upper()
                        is_prep = "PREPARAÇÃO" in st_m.upper() or "PREPARACAO" in st_m.upper() or "PREPARANDO" in st_m.upper()
                        is_preparando = "PREPARANDO" in st_m.upper()
                        is_guia = "GUIA" in st_m.upper()
                        
                        tipo_setup = "Outro (Parada/Manut.)"
                        if is_seq:
                            tipo_setup = "Sequência"
                        elif is_prep:
                            if "HASTE" in st_m.upper(): tipo_setup = "Preparação - HASTE"
                            elif is_guia: tipo_setup = "Preparação - GUIA"
                            else: tipo_setup = "Preparação"
                            
                        tem_rebolo = "SIM" if "(C/ REBOLO)" in st_m.upper() else "NÃO"

                        h_alvo = "Imediato / Na Fila"
                        if "AGENDADA PARA" in st_m.upper():
                            try: h_alvo = st_m.upper().split('AGENDADA PARA')[1].strip().split(" ")[0]
                            except: pass
                        elif "[AGENDADO:" in st_m.upper():
                            try: h_alvo = st_m.upper().split('[AGENDADO:')[1].split(']')[0].strip()
                            except: pass
                        elif "[Fim Previsto:" in st_m:
                            try: h_alvo = st_m.split("[Fim Previsto:")[1].split("]")[0].strip()
                            except: pass

                        prog_status = "Não validado ⚠️"
                        is_prog_ok = "[PROG: OK" in st_m.upper()
                        is_prog_nok = "[PROG: NOK" in st_m.upper()
                        
                        if is_prog_ok: prog_status = "OK ✅"
                        elif is_prog_nok: prog_status = "NOK ❌"

                        op_maq, item_maq = "", ""
                        if "[Ordem:" in st_m:
                            try: op_maq = st_m.split("[Ordem:")[1].split("]")[0].strip()
                            except: pass
                        if "[Novo Item:" in st_m:
                            try: item_maq = st_m.split("[Novo Item:")[1].split("]")[0].strip()
                            except: pass
                        elif "[Item Atual:" in st_m:
                            try: item_maq = st_m.split("[Item Atual:")[1].split("]")[0].strip()
                            except: pass
                        elif "[Item:" in st_m:
                            try: item_maq = st_m.split("[Item:")[1].split("]")[0].strip()
                            except: pass

                        op_arm, item_arm = "", ""
                        if not df_arm.empty:
                            gaveta_num = maq_m.split("-")[0]
                            filtro_arm = "Afiadoras" if setor_m == "AFC" else "Retíficas"
                            gaveta_row = df_arm[(df_arm['Posicao'] == str(gaveta_num)) & (df_arm['Armario'].str.contains(filtro_arm))]
                            if not gaveta_row.empty and str(gaveta_row.iloc[0]['Status']).strip() != 'VAZIO':
                                op_arm = str(gaveta_row.iloc[0].get('Ordem', '')).replace('.0', '').replace('nan', '').strip()
                                item_arm = str(gaveta_row.iloc[0].get('Item', '')).replace('.0', '').replace('nan', '').strip()

                        # --- CORREÇÃO DE PRIORIDADE: ARMÁRIO TEM PRIORIDADE MÁXIMA ---
                        if is_guia:
                            item_guia = item_arm if item_arm else (item_maq if item_maq else obter_item_rodando_atual(f"{setor_m} {maq_m}"))
                            final_item = item_guia if item_guia else "-"
                            label_item_txt = "Item Rodando (Atual)"
                            final_op = op_arm if op_arm else (op_maq if op_maq else "Manter Atual")
                        else:
                            final_op = op_arm if op_arm else (op_maq if op_maq else "Nenhuma")
                            final_item = item_arm if item_arm else (item_maq if item_maq else "-")
                            label_item_txt = "Item"

                        reb1, reb2 = "-", "-"
                        if final_item != "-" and not df_rebolos.empty:
                            item_busca = final_item.upper()
                            match = df_rebolos[df_rebolos['ITEM_BUSCA'] == item_busca]
                            if match.empty: match = df_rebolos[df_rebolos['ITEM_BUSCA'].str.contains(item_busca, regex=False, na=False)]
                            if not match.empty:
                                reb1 = str(match.iloc[0].get('REBOLO', match.iloc[0].get('REBOLO1', ''))).strip()
                                reb2 = str(match.iloc[0].get('REBOLO2', '')).strip()
                                if reb1.lower() in ['nan', 'none', '']: reb1 = "-"
                                if reb2.lower() in ['nan', 'none', '']: reb2 = "-"

                        if tem_rebolo == "SIM" and reb1 == "-":
                            reb1 = "Não cadastrado"

                        titulo_tempo = "⏰ Agendado para:"
                        valor_tempo = h_alvo
                        cabecalho_maq = f"⚙️ {setor_m} {maq_m}"

                        if "MANUTENÇÃO" in st_m.upper():
                            bg_color, bd_color = "#FECACA", "#DC2626" 
                            cabecalho_maq = f"🛠 {setor_m} {maq_m} (MANUTENÇÃO)"
                        elif "PARADA" in st_m.upper():
                            bg_color, bd_color = "#FECACA", "#DC2626" 
                            cabecalho_maq = f"🔴 {setor_m} {maq_m} (PARADA)"
                        elif is_preparando:
                            bg_color, bd_color = "#F472B6", "#BE185D" 
                            cabecalho_maq = f"⚙ {setor_m} {maq_m} (PREPARANDO)"
                            titulo_tempo = "⏳ Tempo de Setup:"
                            valor_tempo = "0 min"
                            info_maq = obter_info_maquina(maq_m, setor_m)
                            if info_maq:
                                h_inicio = info_maq.get('Hora', '--:--')
                                if h_inicio != '--:--':
                                    try:
                                        dt_reg = datetime.strptime(f"{datetime.now(FUSO_BR).strftime('%Y-%m-%d')} {h_inicio}", "%Y-%m-%d %H:%M")
                                        t_decorrido = datetime.now(FUSO_BR) - dt_reg.replace(tzinfo=FUSO_BR)
                                        mins = int(t_decorrido.total_seconds() // 60)
                                        valor_tempo = f"{mins} min"
                                    except: pass
                        elif is_prog_ok:
                            bg_color, bd_color = "#D1FAE5", "#059669" 
                        else:
                            bg_color, bd_color = "#FFEDD5", "#EA580C" 

                        html_rebolo = ""
                        if tem_rebolo == "SIM":
                            html_rebolo = f"<div style='margin: 0 0 2px 0;'><strong style='font-size: 13px;'>🛞 Reb 1:</strong> <span style='font-size: 13px;'>{reb1}</span></div><div style='margin: 0;'><strong style='font-size: 13px;'>🛞 Reb 2:</strong> <span style='font-size: 13px;'>{reb2}</span></div>"

                        html = f"<div class='postit-card' style='background-color: {bg_color}; padding: 15px; border-radius: 6px; box-shadow: 2px 4px 8px rgba(0,0,0,0.3); margin-bottom: 20px; min-height: 250px;'><div style='margin: 0 0 10px 0; border-bottom: 2px solid {bd_color}; padding-bottom: 5px;'><strong style='font-size: 16px;'>{cabecalho_maq}</strong></div><div style='margin: 0 0 4px 0;'><strong style='font-size: 14px;'>{titulo_tempo}</strong> <span style='font-size: 14px;'>{valor_tempo}</span></div><div style='margin: 0 0 4px 0;'><strong style='font-size: 14px;'>📋 Setup:</strong> <span style='font-size: 14px;'>{tipo_setup}</span></div><div style='margin: 0 0 8px 0;'><strong style='font-size: 14px;'>💻 Programa:</strong> <span style='font-size: 14px;'>{prog_status}</span></div><div style='margin: 0 0 8px 0;'><strong style='font-size: 14px;'>🔄 Troca Rebolo:</strong> <span style='font-size: 14px;'>{tem_rebolo}</span></div><div style='background: rgba(255,255,255,0.6); padding: 8px; border-radius: 6px; margin-bottom: 8px;'><div style='margin: 0 0 2px 0;'><strong style='font-size: 13px;'>Ordem:</strong> <span style='font-size: 13px;'>{final_op}</span></div><div style='margin: 0;'><strong style='font-size: 13px;'>{label_item_txt}:</strong> <span style='font-size: 13px;'>{final_item}</span></div></div>{html_rebolo}</div>"
                        
                        cols[j].markdown(html, unsafe_allow_html=True)

        render_grid_setor(lista_afc, "SETOR DE AFIAÇÃO (AFC)")
        render_grid_setor(lista_rtf, "SETOR DE RETÍFICA (RTF)")

    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] and perfil != 'preset':
        painel_controle_maquina(st.session_state['maq_ativa'], st.session_state['setor_ativo'])
        st.divider()

    aba_atual, aba_futuro, aba_previsao = st.tabs(["🚨 Turno Vigente", "🔮 Preparações Futuras", "⏱️ Lançar Previsões"])

    with aba_atual:
        st.markdown(f"**Exibindo incidências e paradas previstas para o {turno_vigente_real}**")
        if not incidencias_turno_atual: st.success("✨ Ótimo! Nenhuma incidência ou parada prevista para o momento.")
        else:
            if perfil == 'preset':
                renderizar_post_its_preset(incidencias_turno_atual)
            else:
                for setor_m, maq_m, st_m in incidencias_turno_atual:
                    icone = get_status_icon(st_m)
                    st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"chk_at_{setor_m}_{maq_m}", use_container_width=True, on_click=definir_estados, args=({'maq_ativa': maq_m, 'setor_ativo': setor_m},))

    with aba_futuro:
        st.markdown("**Programação de Setups e Paradas por Turno**")
        filtro_turno = st.radio("Selecione o Turno para visualizar:", ["1° TURNO", "2° TURNO", "3° TURNO"], horizontal=True)
        lista_futura = preparacoes_futuras[filtro_turno]
        if not lista_futura: st.info(f"Nenhum setup ou parada programada futuramente para o {filtro_turno}.")
        else:
            if perfil == 'preset':
                renderizar_post_its_preset(lista_futura)
            else:
                for setor_m, maq_m, st_m in lista_futura:
                    icone = get_status_icon(st_m)
                    st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"chk_fut_{setor_m}_{maq_m}", use_container_width=True, on_click=definir_estados, args=({'maq_ativa': maq_m, 'setor_ativo': setor_m},))

    with aba_previsao:
        st.markdown("#### ⏱️ Lançar Previsão de Parada por Fila")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Selecione a fila e digite o horário (HH:MM) previsto para as máquinas pararem.</p>", unsafe_allow_html=True)

        if setor_atual in ['TECNICO', 'GERAL', 'GERÊNCIA', 'PRESET', 'PROGRAMACAO'] or perfil == 'adm':
            c_s1, c_s2 = st.columns(2)
            c_s1.button("Setor: AFIAÇÃO", use_container_width=True, on_click=definir_estados, args=({'setor_prev_sel': 'AFC', 'fila_prev_sel': None},))
            c_s2.button("Setor: RETÍFICA", use_container_width=True, on_click=definir_estados, args=({'setor_prev_sel': 'RTF', 'fila_prev_sel': None},))
            setor_foco = st.session_state.get('setor_prev_sel', 'AFC')
        else:
            setor_foco = "AFC" if setor_atual == "AFC" else "RTF"
            
        st.markdown(f"**Lançando previsões para: {setor_foco}**")
        st.markdown("<hr style='margin: 5px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        
        if st.session_state.get('fila_prev_sel') is None:
            st.button("📍 Fila 1", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'fila_1'))
            st.button("📍 Fila 2", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'fila_2'))
            st.button("📍 Fila 3", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'fila_3'))
            st.button("📍 Fila 4", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'fila_4'))
            if setor_foco == 'RTF':
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                st.button("⚫ Centerless (CNC1)", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'centerless'))
                st.button("🟤 Facetadoras (CNC2)", use_container_width=True, on_click=definir_estado, args=('fila_prev_sel', 'facetadoras'))
        else:
            st.button("⬅️ Voltar para seleção de Fila", key="voltar_fila_prev", on_click=definir_estado, args=('fila_prev_sel', None))
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
                    maquinas_produzindo.append({"Setor": setor_foco, "Maquina": m, "OP": op_atual, "HoraAntiga": hora_prevista, "StatusRaw": st_val})

            if not maquinas_produzindo: st.info(f"Nenhuma máquina em produção nesta fila no momento.")
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
                        inputs_previsao[f"{obj['Setor']} {obj['Maquina']}"] = {"nova": nova_hora, "antiga": obj['HoraAntiga'], "setor": obj['Setor'], "maq": obj['Maquina'], "st_raw": obj['StatusRaw']}
                        
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
                                if "[Fim Previsto:" in st_val: st_val = re.sub(r' \[Fim Previsto:.*?\]', '', st_val)
                                st_final = f"{st_val} [Fim Previsto: {hora_nova}]".strip() if hora_nova else st_val.strip()
                                novas_linhas.append({"Setor": dados['setor'], "Maquina": key_maq, "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str})
                                
                        if novas_linhas:
                            df_dados = pd.read_csv(ARQUIVO_DADOS) if os.path.exists(ARQUIVO_DADOS) else pd.DataFrame(columns=["Setor", "Maquina", "Operador", "Status", "Hora"])
                            df_dados = pd.concat([df_dados, pd.DataFrame(novas_linhas)], ignore_index=True)
                            df_dados.to_csv(ARQUIVO_DADOS, index=False)
                            st.success("✅ Previsões atualizadas com sucesso!")
                            st.rerun()
                        else: st.info("Nenhuma alteração de horário detectada.")

def tela_minhas_incidencias():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
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
            st.button(f"{icone} {setor_m} {maq_m} — {st_m}", key=f"min_{setor_m}_{maq_m}", use_container_width=True, on_click=definir_estados, args=({'maq_ativa': maq_m, 'setor_ativo': setor_m},))

def tela_afc():
    botao_navegar("⬅ Voltar ao Menu", 'menu')
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
        st.rerun()
    if col_em2.button("🔄 Restaurar Status", use_container_width=True):
        restaurar_queda_energia("AFC")
        st.success("✅ Status das afiadoras restaurado!")
        st.rerun()
        
    status_dict = ler_status_atual()
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'AFC': painel_controle_maquina(st.session_state['maq_ativa'], 'AFC')
    
    if st.session_state['celula_selecionada'] is None:
        st.button("📍 Fila 1", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_1'))
        st.button("📍 Fila 2", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_2'))
        st.button("📍 Fila 3", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_3'))
        st.button("📍 Fila 4", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_4'))
    else:
        st.button("⬅️ Trocar de Fila", on_click=definir_estados, args=({'celula_selecionada': None, 'maq_ativa': None},))
        st.divider()
        if st.session_state['celula_selecionada'] == 'fila_1': render_grid_vertical(["6-868", "9-088", "7-743", "11-365", "13-964", "15-973", "17-140", "19-760", "21-206", "23-165", "25-209", "27-431"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_2': render_grid_vertical(["8-247", "4-427", "10-812", "12-367", "14-967", "16-975", "18-957", "20-774", "22-813", "24-761", "26-635", "28-432"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_3': render_grid_vertical(["29-078", "31-969", "33-160", "35-131", "37-892", "39-905", "41-141"], "AFC", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_4': render_grid_vertical(["30-161", "32-081", "34-132", "36-084", "38-596", "40-142"], "AFC", status_dict)

def tela_rtf():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
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
        st.rerun()
    if col_em2.button("🔄 Restaurar Status", use_container_width=True):
        restaurar_queda_energia("RTF")
        st.success("✅ Status das retíficas restaurado!")
        st.rerun()

    status_dict = ler_status_atual()
    if st.session_state['maq_ativa'] and st.session_state['setor_ativo'] == 'RTF': painel_controle_maquina(st.session_state['maq_ativa'], 'RTF')
    
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
        st.button("📍 Fila 1", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_1'))
        st.button("📍 Fila 2", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_2'))
        st.button("📍 Fila 3", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_3'))
        st.button("📍 Fila 4", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_4'))
        st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
        st.button("⚫ Centerless (CNC1)", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'centerless'))
        st.button("🟤 Facetadoras (CNC2)", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'facetadoras'))
    else:
        st.button("⬅️ Trocar de Fila / Setor", on_click=definir_estados, args=({'celula_selecionada': None, 'maq_ativa': None},))
        st.divider()
        if st.session_state['celula_selecionada'] == 'fila_1': render_grid_vertical(f1_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_2': render_grid_vertical(f2_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_3': render_grid_vertical(f3_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'fila_4': render_grid_vertical(f4_atual, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'centerless': render_grid_vertical(todas_cnc1, "RTF", status_dict)
        elif st.session_state['celula_selecionada'] == 'facetadoras': render_grid_vertical(todas_cnc2, "RTF", status_dict)

def tela_equipe():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
    st.markdown("#### 👥 Gestão de Equipe")
    with st.container():
        with st.form("form_equipe", clear_on_submit=True):
            tipo = st.radio("Selecione o Motivo:", ["Ausência / Falta", "Treinamento", "Férias / Atestado"], horizontal=True)
            nome = st.text_input("Nome do Colaborador:")
            if st.form_submit_button("💾 REGISTRAR COLABORADOR", type="primary"):
                if nome:
                    salvar_csv({"Tipo": tipo, "Nome": nome.upper()}, ARQUIVO_EQUIPE)
                    st.success(f"✅ {nome.upper()} registrado como {tipo}!")
                    st.rerun()
    st.divider()
    if os.path.exists(ARQUIVO_EQUIPE):
        df_eq = pd.read_csv(ARQUIVO_EQUIPE)
        if not df_eq.empty: st.dataframe(df_eq, use_container_width=True, hide_index=True)

def _normalizar_hora_edicao(valor):
    """Normaliza valores vindos do data_editor para HH:MM."""
    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass
    if isinstance(valor, dtime):
        return valor.strftime("%H:%M")
    txt = str(valor).strip()
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?!\d)", txt)
    if m:
        try:
            h = int(m.group(1)); minuto = int(m.group(2))
            if 0 <= h <= 23 and 0 <= minuto <= 59:
                return f"{h:02d}:{minuto:02d}"
        except Exception:
            pass
    return txt


def _agendamento_unico_status(status, hora_forcada=None):
    """Garante no máximo UM horário de agendamento no texto do Status.

    Aceita tanto ``AGENDADA PARA HH:MM`` quanto ``[AGENDADO:HH:MM]``.
    Quando ``hora_forcada`` é informada, todos os agendamentos antigos são
    removidos e apenas ``[AGENDADO:hora_forcada]`` é gravado. Sem hora forçada,
    só mexe no texto quando encontra duplicidade, preservando o horário mais
    recente (última ocorrência no Status).
    """
    txt = str(status or "")
    padrao = re.compile(
        r"(?i)\[AGENDADO:\s*(\d{1,2}:\d{2})\s*\]|AGENDADA\s+PARA\s+(\d{1,2}:\d{2})"
    )
    encontrados = list(padrao.finditer(txt))
    if not encontrados:
        return txt

    hora = _normalizar_hora_edicao(hora_forcada) if hora_forcada is not None else ""
    if not re.fullmatch(r"\d{2}:\d{2}", hora or ""):
        ultimo = encontrados[-1]
        hora = _normalizar_hora_edicao(ultimo.group(1) or ultimo.group(2) or "")

    if not re.fullmatch(r"\d{2}:\d{2}", hora or ""):
        return txt

    # Sem alteração explícita e sem duplicidade, preserva o texto exatamente.
    if hora_forcada is None and len(encontrados) == 1:
        return txt

    # Remove TODAS as formas antigas antes de escrever a canônica.
    txt = re.sub(r"(?i)\s*\[AGENDADO:\s*\d{1,2}:\d{2}\s*\]", "", txt)
    txt = re.sub(r"(?i)\s*AGENDADA\s+PARA\s+\d{1,2}:\d{2}", "", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt).strip()
    return f"{txt} [AGENDADO:{hora}]".strip()


def _sincronizar_hora_escrita_status(status, hora_nova):
    """Sincroniza a coluna Hora com a hora escrita dentro do Status.

    Para uma programação aguardando, remove qualquer agendamento antigo/duplicado
    e grava somente um ``[AGENDADO:HH:MM]``. Em PREPARANDO, a coluna Hora é o
    início real do setup; nesse caso apenas limpamos eventuais duplicidades sem
    trocar a programação original.
    """
    status = str(status or "")
    hora_nova = _normalizar_hora_edicao(hora_nova)
    if not re.fullmatch(r"\d{2}:\d{2}", hora_nova or ""):
        return _agendamento_unico_status(status)

    if _normalizar_setup_home(status).startswith("PREPARANDO"):
        return _agendamento_unico_status(status)

    # Se existe agendamento escrito, substitui TODOS por apenas um novo.
    if re.search(r"(?i)\[AGENDADO:|AGENDADA\s+PARA", status):
        status = _agendamento_unico_status(status, hora_nova)

    # Fim Previsto é outra informação; caso exista, também evita duplicidade.
    if re.search(r"(?i)\[FIM\s+PREVISTO:", status):
        status = re.sub(r"(?i)\s*\[FIM\s+PREVISTO:\s*\d{1,2}:\d{2}\s*\]", "", status)
        status = re.sub(r"[ \t]{2,}", " ", status).strip()
        status += f" [Fim Previsto:{hora_nova}]"

    return status.strip()


def tela_editar():
    botao_navegar("⬅️️ Voltar ao Menu", 'menu')
    st.markdown("#### ✏️ Correção de Apontamentos")
    perfil = st.session_state['perfil']
    setor_usuario = st.session_state['setor_usuario']
    
    if perfil == 'adm':
        col_salvar, col_apagar = st.columns([2, 1])
        if col_apagar.button("🗑️ ZERAR DADOS DO TURNO", use_container_width=True):
            if os.path.exists(ARQUIVO_DADOS): os.remove(ARQUIVO_DADOS)
            if os.path.exists(ARQUIVO_EQUIPE): os.remove(ARQUIVO_EQUIPE)
            st.success("✅ Banco de dados apagado com sucesso!")
            st.rerun()
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
                hora_nova = _normalizar_hora_edicao(row.get('Hora', ''))
                status_novo = str(row.get('Status', ''))

                if idx in df_maq.index:
                    hora_antiga = _normalizar_hora_edicao(df_maq.at[idx, 'Hora'])
                    # Se o usuário mudou a coluna Hora, sincroniza também qualquer
                    # horário programado que esteja escrito dentro do Status.
                    if hora_nova != hora_antiga:
                        status_novo = _sincronizar_hora_escrita_status(status_novo, hora_nova)
                    else:
                        status_novo = _agendamento_unico_status(status_novo)
                    df_maq.at[idx, 'Status'] = status_novo
                    df_maq.at[idx, 'Hora'] = hora_nova
                else:
                    status_novo = _sincronizar_hora_escrita_status(status_novo, hora_nova)
                    nova_linha = pd.DataFrame([{
                        "Setor": row.get('Setor', ''),
                        "Maquina": row.get('Maquina', ''),
                        "Operador": row.get('Operador', ''),
                        "Status": status_novo,
                        "Hora": hora_nova,
                    }])
                    df_maq = pd.concat([df_maq, nova_linha], ignore_index=True)
            df_maq.to_csv(ARQUIVO_DADOS, index=False)
            st.success("✨ Banco de dados atualizado com sucesso!")
            st.rerun()
    else: st.info("Nenhum apontamento encontrado no sistema.")

def tela_historico():
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
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
    botao_navegar("⬅️ Voltar à Central", 'hub_relatorios')
    st.markdown("#### 📋 Fechamento e Relatório de Turno")
    col1, col2 = st.columns(2)
    gerar = col1.button("👁 Visualizar", use_container_width=True)
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
            st.rerun()


# =============================================================
# REDESIGN V10.6 — ARMÁRIOS LIMPOS COM POSIÇÕES FÍSICAS FIXAS
# Somente apresentação. A persistência e as regras existentes continuam iguais.
# =============================================================
CSS_ARMARIOS_V104 = r"""
<style>
    /* V10.5 — Armários mais limpos e legíveis */
    .armario-hero {
        display:flex;align-items:center;justify-content:space-between;gap:18px;
        padding:20px 22px;margin:6px 0 18px;border-radius:19px;
        background:linear-gradient(135deg,rgba(139,92,246,.12),rgba(45,212,191,.055));
        border:1px solid rgba(139,92,246,.20);box-shadow:0 14px 38px rgba(0,0,0,.15);
    }
    .armario-hero-kicker {
        font-size:11px;font-weight:900;letter-spacing:.8px;text-transform:uppercase;color:#A78BFA;
    }
    .armario-hero-title {
        font-size:27px;font-weight:950;color:#F4F4F5;margin-top:4px;letter-spacing:-.55px;
    }
    .armario-hero-sub {
        font-size:13px;font-weight:700;color:#9A9AA5;margin-top:7px;line-height:1.45;
    }
    .armario-hero-live {
        font-size:11px;font-weight:900;color:#5EEAD4;padding:8px 11px;border-radius:999px;
        background:rgba(45,212,191,.08);border:1px solid rgba(45,212,191,.16);white-space:nowrap;
    }

    /* Resumo reduzido: só o que importa */
    .armario-summary-grid {
        display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 18px;
    }
    .armario-summary-card {
        padding:16px 17px;border-radius:15px;background:rgba(24,24,33,.94);
        border:1px solid rgba(255,255,255,.075);box-shadow:0 8px 22px rgba(0,0,0,.12);
    }
    .armario-summary-label {
        font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.6px;color:#92929D;
    }
    .armario-summary-value {
        font-size:30px;line-height:1;font-weight:950;color:#F4F4F5;margin-top:9px;
    }
    .armario-summary-foot {
        font-size:11px;font-weight:750;color:#858590;margin-top:7px;
    }
    .armario-summary-card.ok {border-top:3px solid #2DD4BF;}
    .armario-summary-card.free {border-top:3px solid #EF4444;}
    .armario-summary-card.wait {border-top:3px solid #F59E0B;}

    /* Cabeçalho de cada armário */
    .armario-panel-head {
        padding:16px 17px 14px;margin:9px 0 13px;border-radius:15px;
        background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.07);
    }
    .armario-panel-top {
        display:flex;align-items:center;justify-content:space-between;gap:14px;
    }
    .armario-panel-name {
        font-size:16px;font-weight:950;color:#F1F1F4;
    }
    .armario-panel-count {
        font-size:13px;font-weight:900;color:#C3C3CB;white-space:nowrap;
    }
    .armario-progress {
        height:8px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden;margin-top:12px;
    }
    .armario-progress-fill {
        height:100%;border-radius:999px;background:linear-gradient(90deg,#8B5CF6,#2DD4BF);
    }

    .armario-legend {
        display:flex;gap:9px;flex-wrap:wrap;margin:13px 0 19px;
    }
    .armario-legend span {
        display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:850;color:#A4A4AE;
        padding:7px 9px;border-radius:999px;background:rgba(255,255,255,.028);
        border:1px solid rgba(255,255,255,.06);
    }

    /* Cartões: 3 linhas de informação, fonte maior */
    [class*="st-key-armcard_"] div[data-testid="stButton"] > button,
    [class*="st-key-armcard_"] button {
        min-height:118px !important;height:118px !important;
        padding:16px 15px !important;border-radius:15px !important;
        white-space:pre-line !important;line-height:1.48 !important;
        text-align:left !important;justify-content:flex-start !important;align-items:flex-start !important;
        font-size:14px !important;font-weight:850 !important;
        box-shadow:0 8px 20px rgba(0,0,0,.13) !important;
        overflow:hidden !important;
    }
    [class*="st-key-armcard_"] button p {
        white-space:pre-line !important;text-align:left !important;line-height:1.48 !important;width:100% !important;
        font-size:14px !important;
    }

    [class*="st-key-armcard_vazio_"] button {
        background:rgba(239,68,68,.055)!important;border:1px solid rgba(239,68,68,.24)!important;color:#FCA5A5!important;
    }
    [class*="st-key-armcard_op_"] button,
    [class*="st-key-armcard_ocupado_"] button {
        background:rgba(45,212,191,.055)!important;border:1px solid rgba(45,212,191,.22)!important;color:#D5FFFA!important;
    }
    [class*="st-key-armcard_jagura_"] button {
        background:rgba(245,158,11,.07)!important;border:1px solid rgba(245,158,11,.26)!important;color:#FCD34D!important;
    }
    [class*="st-key-armcard_almox_"] button {
        background:rgba(96,165,250,.07)!important;border:1px solid rgba(96,165,250,.26)!important;color:#BFDBFE!important;
    }
    [class*="st-key-armcard_pcp_"] button {
        background:rgba(167,139,250,.07)!important;border:1px solid rgba(167,139,250,.26)!important;color:#DDD6FE!important;
    }
    [class*="st-key-armcard_prep_"] button {
        background:rgba(249,115,22,.07)!important;border:1px solid rgba(249,115,22,.26)!important;color:#FED7AA!important;
    }
    [class*="st-key-armcard_seq_"] button {
        background:rgba(217,119,6,.075)!important;border:1px solid rgba(217,119,6,.28)!important;color:#FDE68A!important;
    }
    [class*="st-key-armcard_"] button:hover {
        transform:translateY(-2px)!important;filter:brightness(1.07);
    }

    /* Detalhe aparece só depois do clique */
    .armario-selected {
        padding:19px 20px;margin:6px 0 18px;border-radius:17px;
        background:linear-gradient(135deg,rgba(45,212,191,.08),rgba(139,92,246,.07));
        border:1px solid rgba(45,212,191,.17);
    }
    .armario-selected-top {
        display:flex;align-items:center;justify-content:space-between;gap:14px;
    }
    .armario-selected-title {
        font-size:20px;font-weight:950;color:#F4F4F5;
    }
    .armario-selected-sub {
        font-size:12px;color:#9898A3;font-weight:750;margin-top:5px;
    }
    .armario-selected-status {
        font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.5px;color:#5EEAD4;
        border:1px solid rgba(45,212,191,.18);background:rgba(45,212,191,.06);
        padding:7px 10px;border-radius:999px;
    }
    .armario-selected-grid {
        display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px;
    }
    .armario-selected-box {
        padding:12px 13px;border-radius:11px;background:rgba(0,0,0,.16);border:1px solid rgba(255,255,255,.055);
    }
    .armario-selected-box span {
        display:block;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.55px;color:#81818C;
    }
    .armario-selected-box b {
        display:block;font-size:14px;color:#E4E4E8;margin-top:5px;white-space:normal;overflow-wrap:anywhere;
    }

    /* MATRIZ FÍSICA: sempre 4 posições por linha */
    [class*="st-key-armgrid_"] {
        overflow-x:auto !important;
        overflow-y:hidden !important;
        padding-bottom:5px;
        scrollbar-width:thin;
    }
    [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] {
        gap:.9rem!important;
        flex-wrap:nowrap!important;
        min-width:760px!important;
    }
    [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        min-width:175px!important;
        flex:1 1 0!important;
    }

    @media (max-width:1050px) {
        .armario-summary-grid {grid-template-columns:1fr 1fr 1fr;}
        [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] {
            min-width:720px!important;
        }
        [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width:165px!important;
        }
    }

    @media (max-width:650px) {
        .armario-summary-grid {grid-template-columns:1fr;gap:9px;}
        .armario-hero {align-items:flex-start;padding:17px;}
        .armario-hero-title {font-size:23px;}
        .armario-hero-sub {font-size:13px;}
        .armario-hero-live {display:none;}
        .armario-panel-name {font-size:15px;}
        .armario-panel-count {font-size:12px;}
        .armario-selected-grid {grid-template-columns:1fr;}

        /* No celular não reordena: mantém as 4 posições e permite deslizar para os lados. */
        [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] {
            min-width:700px!important;
            gap:.7rem!important;
            flex-wrap:nowrap!important;
        }
        [class*="st-key-armgrid_"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width:160px!important;
            flex:0 0 160px!important;
        }
        [class*="st-key-armcard_"] div[data-testid="stButton"] > button,
        [class*="st-key-armcard_"] button {
            min-height:112px!important;height:112px!important;
            font-size:14px!important;padding:14px!important;
        }
        [class*="st-key-armcard_"] button p {font-size:14px!important;}
    }
</style>
"""
st.markdown(CSS_ARMARIOS_V104, unsafe_allow_html=True)

def tela_armarios():
    exibir_alertas_preset()
    botao_navegar("⬅️ Voltar ao Menu", 'menu')
    st.markdown("#### 🗄️ Gestão de Armários (Pré-Set)")
    
    inicializar_armarios()
    df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype={'Ordem': str, 'Item': str, 'Status': str, 'Data_Hora': str, 'Posicao': str, 'Armario': str, 'Observacao': str, 'Rebolo': str})
    if 'Item' not in df_arm.columns: df_arm['Item'] = ""
    if 'Observacao' not in df_arm.columns: df_arm['Observacao'] = ""
    if 'Rebolo' not in df_arm.columns: df_arm['Rebolo'] = ""

    gaveta = st.session_state.get('gaveta_selecionada', None)
    if gaveta:
        arm_sel = gaveta['armario']
        pos_sel = gaveta['posicao']
        status_sel = gaveta['status']
        op_sel = gaveta['ordem']
        item_sel = gaveta['item']
        obs_sel = gaveta.get('observacao', '')
        rebolo_sel = gaveta.get('rebolo', '')
        
        _op_vis = str(op_sel).replace('nan', '').replace('.0', '').strip() or '—'
        _item_vis = str(item_sel).replace('nan', '').replace('.0', '').strip() or '—'
        _reb_vis = str(rebolo_sel).replace('nan', '').strip() or '—'
        _status_vis = 'LIVRE' if str(status_sel).upper() == 'VAZIO' else str(status_sel).upper()
        st.markdown(f"""
        <div class='armario-selected'>
            <div class='armario-selected-top'>
                <div>
                    <div class='armario-selected-title'>Gaveta da máquina {html.escape(str(pos_sel))}</div>
                    <div class='armario-selected-sub'>{html.escape(str(arm_sel))}</div>
                </div>
                <div class='armario-selected-status'>{html.escape(_status_vis)}</div>
            </div>
            <div class='armario-selected-grid'>
                <div class='armario-selected-box'><span>OP</span><b>{html.escape(_op_vis)}</b></div>
                <div class='armario-selected-box'><span>Item</span><b>{html.escape(_item_vis)}</b></div>
                <div class='armario-selected-box'><span>Rebolo</span><b>{html.escape(_reb_vis)}</b></div>
                <div class='armario-selected-box'><span>Observação</span><b>{html.escape(str(obs_sel).replace('nan','').strip() or '—')}</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if status_sel == 'VAZIO':
            with st.form("form_alimentar"):
                st.info("🟥 Esta gaveta está VAZIA. Insira os dados para guardar o setup ou selecione o motivo rápido.")
                
                motivos_rapidos = [
                    "-- Selecione um Motivo Rápido (Opcional) --",
                    "Aguardando Jagura",
                    "Aguardando Almoxarifado",
                    "Aguardando PCP",
                    "Em Preparação",
                    "Em Sequência"
                ]
                motivo_select = st.selectbox("Motivo / Caminho Rápido:", motivos_rapidos, key="top_motivo_vazio")
                
                c_op, c_it = st.columns(2)
                ordem_in = c_op.text_input("Ordem de Produção (OP):", placeholder="Ex: 987654", key="top_op_vazio")
                item_in = c_it.text_input("Item / Peça:", placeholder="Ex: 313324", key="top_item_vazio")
                rebolo_in = st.text_input("Rebolo(s) Alocado (Opcional):", placeholder="Ex: REB 1234", key="top_rebolo_vazio")
                obs_in = st.text_input("Observação Adicional / Detalhes:", placeholder="Detalhes opcionais...", key="top_obs_vazio")
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("📥 GUARDAR SETUP", type="primary", use_container_width=True):
                    obs_final = motivo_select if motivo_select != motivos_rapidos[0] else ""
                    if obs_in.strip():
                        obs_final = f"{obs_final} - {obs_in.strip()}" if obs_final else obs_in.strip()

                    if not ordem_in.strip() and not obs_final.strip(): 
                        st.error("⚠️ Preencha a Ordem (OP) ou selecione um Motivo Rápido!")
                    else:
                        ordem_limpo = ordem_in.strip().upper().replace(".0", "").lstrip("0")
                        item_limpo = item_in.strip().upper().replace(".0", "").lstrip("0")
                        
                        novo_status = "AGUARDANDO MÁQUINA" if ordem_limpo else "VAZIO"
                        
                        idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao', 'Rebolo']] = [ordem_limpo, item_limpo, novo_status, datetime.now(FUSO_BR).strftime("%H:%M"), obs_final, rebolo_in.strip()]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.session_state['gaveta_selecionada'] = None
                            st.success(f"✅ Setup guardado na gaveta da MÁQUINA {pos_sel}!")
                            st.rerun()
                if c2.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        else:
            with st.form("form_editar_excluir"):
                st.warning("🟩 Gaveta OCUPADA - Altere os dados abaixo para corrigir ou exclua o registro.")
                
                motivos_rapidos = [
                    "-- Selecione um Motivo Rápido (Opcional) --",
                    "Aguardando Jagura",
                    "Aguardando Almoxarifado",
                    "Aguardando PCP",
                    "Em Preparação",
                    "Em Sequência"
                ]
                motivo_select = st.selectbox("Motivo / Caminho Rápido:", motivos_rapidos, key="top_motivo_ocupado")

                c_op, c_it = st.columns(2)
                nova_op = c_op.text_input("Ordem de Produção (OP):", value=op_sel, key="top_op_ocupado")
                novo_item = c_it.text_input("Item / Peça:", value=item_sel, key="top_item_ocupado")
                novo_rebolo = st.text_input("Rebolo(s) Alocado:", value=str(rebolo_sel).replace('nan', ''), key="top_reb_ocupado")
                nova_obs = st.text_input("Observação / Justificativa:", value=str(obs_sel).replace('nan', ''), key="top_obs_ocupado")
                
                c1, c2, c3 = st.columns(3)
                if c1.form_submit_button("💾 Atualizar", type="primary", use_container_width=True):
                    obs_final = motivo_select if motivo_select != motivos_rapidos[0] else ""
                    if nova_obs.strip():
                        obs_final = f"{obs_final} - {nova_obs.strip()}" if obs_final else nova_obs.strip()
                    else:
                        obs_final = nova_obs.strip() if nova_obs.strip() else str(obs_sel)

                    if not nova_op.strip() and not obs_final.strip(): 
                        st.error("⚠️ É obrigatório possuir uma Ordem (OP) ou uma Observação!")
                    else:
                        ordem_limpa_upd = nova_op.strip().upper().replace(".0", "").lstrip("0")
                        item_limpo_upd = novo_item.strip().upper().replace(".0", "").lstrip("0")
                        
                        novo_status_upd = "AGUARDANDO MÁQUINA" if ordem_limpa_upd else "VAZIO"

                        idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Observacao', 'Rebolo']] = [ordem_limpa_upd, item_limpo_upd, novo_status_upd, obs_final, novo_rebolo.strip()]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.session_state['gaveta_selecionada'] = None
                            st.success("✅ Gaveta atualizada com sucesso!")
                            st.rerun()
                if c2.form_submit_button("🗑️ Excluir", use_container_width=True):
                    idx = df_arm[(df_arm['Armario'] == arm_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                    if not idx.empty:
                        df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao', 'Rebolo']] = ["", "", "VAZIO", datetime.now(FUSO_BR).strftime("%H:%M"), "", ""]
                        df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                        st.session_state['gaveta_selecionada'] = None
                        st.success("✅ Gaveta liberada com sucesso!")
                        st.rerun()
                if c3.form_submit_button("❌ Cancelar", use_container_width=True):
                    st.session_state['gaveta_selecionada'] = None
                    st.rerun()
        st.divider()

    aba1, aba2, aba3, aba4, aba5, aba6 = st.tabs(["👁️ Visão Física", "➕ Alimentar", "🔔 Histórico", "🔄 Troca de Rebolo", "🔙 Devoluções", "✏️ Edição Lote"])

    with aba1:
        # ---------------------- VISÃO FÍSICA REDESENHADA ----------------------
        df_vis = df_arm.fillna('').copy()
        for _c in ['Ordem','Item','Status','Observacao','Rebolo','Armario','Posicao','Data_Hora']:
            if _c not in df_vis.columns:
                df_vis[_c] = ''
            df_vis[_c] = df_vis[_c].astype(str).replace('nan', '')

        status_norm = df_vis['Status'].str.strip().str.upper()
        obs_norm = df_vis['Observacao'].str.upper()
        op_norm = df_vis['Ordem'].str.replace('.0', '', regex=False).str.strip()
        ocupadas_total = int((status_norm != 'VAZIO').sum())
        livres_total = int((status_norm == 'VAZIO').sum())
        com_op_total = int((op_norm != '').sum())
        pendencias_total = int(obs_norm.str.contains('JAGURA|ALMOXARIFADO|PCP|PREPARA|SEQU', regex=True, na=False).sum())
        total_total = max(1, len(df_vis))

        st.markdown(f"""
        <div class='armario-hero'>
            <div>
                <div class='armario-hero-kicker'>Pré-Set · controle visual</div>
                <div class='armario-hero-title'>Armários de ordens e setups</div>
                <div class='armario-hero-sub'>Clique em uma gaveta para consultar, alimentar ou corrigir. As cores mostram a situação de cada posição.</div>
            </div>
            <div class='armario-hero-live'>● DADOS ATUAIS</div>
        </div>
        <div class='armario-summary-grid'>
            <div class='armario-summary-card ok'><div class='armario-summary-label'>Ocupadas</div><div class='armario-summary-value'>{ocupadas_total}</div><div class='armario-summary-foot'>de {len(df_vis)} posições</div></div>
            <div class='armario-summary-card free'><div class='armario-summary-label'>Livres</div><div class='armario-summary-value'>{livres_total}</div><div class='armario-summary-foot'>disponíveis agora</div></div>
            <div class='armario-summary-card wait'><div class='armario-summary-label'>Pendências</div><div class='armario-summary-value'>{pendencias_total}</div><div class='armario-summary-foot'>itens que precisam de atenção</div></div>
        </div>
        """, unsafe_allow_html=True)

        cf1, cf2 = st.columns([1, 1.65])
        filtro_arm = cf1.radio('Visualizar:', ['Todos', 'Afiadoras', 'Retíficas'], horizontal=True, key='arm_visual_filtro')
        busca_arm = cf2.text_input('Buscar no armário:', placeholder='Máquina, OP ou item...', key='arm_visual_busca')

        st.markdown("""
        <div class='armario-legend'>
            <span>🟩 OP / ocupado</span><span>🟥 livre</span><span>🟨 Jagura</span>
            <span>🟦 Almoxarifado</span><span>🟪 PCP</span><span>🟧 Preparação</span><span>🟫 Sequência</span>
        </div>
        """, unsafe_allow_html=True)

        armarios_lista = ['Afiadoras 04 a 28', 'Afiadoras 29 a 41', 'Retíficas 05 a 28', 'Retíficas 29 a 42']
        if filtro_arm == 'Afiadoras':
            armarios_lista = [a for a in armarios_lista if a.startswith('Afiadoras')]
        elif filtro_arm == 'Retíficas':
            armarios_lista = [a for a in armarios_lista if a.startswith('Retíficas')]

        busca_limpa = str(busca_arm or '').strip().lower()

        def _visual_gaveta(gav):
            status = str(gav.get('Status', '') or '').strip().upper()
            obs = str(gav.get('Observacao', '') or '').strip().upper()
            op = str(gav.get('Ordem', '') or '').replace('.0','').replace('nan','').strip()
            item = str(gav.get('Item', '') or '').replace('.0','').replace('nan','').strip()
            if 'JAGURA' in obs:
                return 'jagura', '🟨', 'AG. JAGURA'
            if 'ALMOXARIFADO' in obs:
                return 'almox', '🟦', 'ALMOXARIFADO'
            if 'PCP' in obs:
                return 'pcp', '🟪', 'AG. PCP'
            if 'PREPARAÇÃO' in obs or 'PREPARACAO' in obs:
                return 'prep', '🟧', 'EM PREPARAÇÃO'
            if 'SEQUÊNCIA' in obs or 'SEQUENCIA' in obs:
                return 'seq', '🟫', 'EM SEQUÊNCIA'
            if status == 'VAZIO':
                return 'vazio', '🟥', 'LIVRE'
            if op:
                return 'op', '🟩', 'AG. MÁQUINA' if status == 'AGUARDANDO MÁQUINA' else 'COM OP'
            return 'ocupado', '🟩', status if status else 'OCUPADO'

        for arm_idx, arm in enumerate(armarios_lista):
            df_filtrado = df_vis[df_vis['Armario'] == arm].copy()
            df_filtrado['Posicao_Int'] = pd.to_numeric(df_filtrado['Posicao'], errors='coerce')
            df_filtrado = df_filtrado.sort_values(by='Posicao_Int')

            if busca_limpa:
                mask_busca = (
                    df_filtrado['Posicao'].str.lower().str.contains(busca_limpa, regex=False, na=False) |
                    df_filtrado['Ordem'].str.lower().str.contains(busca_limpa, regex=False, na=False) |
                    df_filtrado['Item'].str.lower().str.contains(busca_limpa, regex=False, na=False)
                )
                df_exibir_arm = df_filtrado[mask_busca].copy()
            else:
                df_exibir_arm = df_filtrado.copy()

            if df_exibir_arm.empty and busca_limpa:
                continue

            total_gavetas = len(df_filtrado)
            ocupados = int((df_filtrado['Status'].str.strip().str.upper() != 'VAZIO').sum())
            com_op = int((df_filtrado['Ordem'].str.strip() != '').sum())
            pend = int(df_filtrado['Observacao'].str.upper().str.contains('JAGURA|ALMOXARIFADO|PCP|PREPARA|SEQU', regex=True, na=False).sum())
            pct = round((ocupados / max(1,total_gavetas)) * 100)

            st.markdown(f"""
            <div class='armario-panel-head'>
                <div class='armario-panel-top'>
                    <div class='armario-panel-name'>📦 {html.escape(arm)}</div>
                    <div class='armario-panel-count'>{ocupados} de {total_gavetas} ocupadas</div>
                </div>
                <div class='armario-progress'><div class='armario-progress-fill' style='width:{pct}%'></div></div>
            </div>
            """, unsafe_allow_html=True)

            gavetas = df_exibir_arm.to_dict('records')
            # IMPORTANTE: mantém a disposição física original do armário.
            # Não alterar para 3/2/1 colunas, pois isso muda a posição visual das gavetas.
            for linha in range(0, len(gavetas), 4):
                with st.container(key=f'armgrid_{arm_idx}_{linha}'):
                    cols_gaveta = st.columns(4)
                    for c in range(4):
                        if linha + c >= len(gavetas):
                            continue
                        gav = gavetas[linha + c]
                        num = str(gav.get('Posicao','')).replace('.0','')
                        op_f = str(gav.get('Ordem','')).replace('.0','').replace('nan','').strip()
                        item_f = str(gav.get('Item','')).replace('.0','').replace('nan','').strip()
                        status = str(gav.get('Status',''))
                        visual_key, ico, situacao = _visual_gaveta(gav)
                        linha_op = f'OP {op_f}' if op_f else 'SEM OP'
                        btn_label = f'{ico}  MÁQ {num}\n{linha_op}\n{situacao}'
                        if cols_gaveta[c].button(
                            btn_label,
                            key=f'armcard_{visual_key}_{arm_idx}_{linha}_{c}',
                            use_container_width=True,
                        ):
                            if st.session_state['perfil'] in ['preset', 'adm']:
                                st.session_state['gaveta_selecionada'] = {
                                    'armario': arm,
                                    'posicao': num,
                                    'status': status,
                                    'ordem': gav.get('Ordem', ''),
                                    'item': gav.get('Item', ''),
                                    'observacao': gav.get('Observacao', ''),
                                    'rebolo': gav.get('Rebolo', '')
                                }
                                st.rerun()
                            else:
                                st.error('⚠ Apenas Pré-Set e ADM podem gerenciar gavetas!')

        if busca_limpa and not any(
            (
                df_vis[df_vis['Armario'] == arm]['Posicao'].str.lower().str.contains(busca_limpa, regex=False, na=False) |
                df_vis[df_vis['Armario'] == arm]['Ordem'].str.lower().str.contains(busca_limpa, regex=False, na=False) |
                df_vis[df_vis['Armario'] == arm]['Item'].str.lower().str.contains(busca_limpa, regex=False, na=False)
            ).any() for arm in armarios_lista
        ):
            st.info('Nenhuma gaveta encontrada para essa busca.')

    with aba2:
        if st.session_state['perfil'] in ['preset', 'adm']:
            st.markdown("📥 **Guardar Ferramental / Setup**")
            
            c1, c2 = st.columns(2)
            armario_sel = c1.selectbox("Selecione o Armário:", ["Afiadoras 04 a 28", "Afiadoras 29 a 41", "Retíficas 05 a 28", "Retíficas 29 a 42"], key="aba2_arm_sel")
            
            pos_vazias = df_arm[(df_arm['Armario'] == armario_sel) & (df_arm['Status'] == 'VAZIO')]
            pos_vazias_lista = pos_vazias['Posicao'].tolist()
            
            if not pos_vazias_lista:
                st.warning(f"O {armario_sel} está cheio!")
                pos_sel = None
            else:
                pos_vazias_sorted = sorted([int(x) for x in pos_vazias_lista])
                pos_sel = c2.selectbox("Máquina Alvo:", [str(x) for x in pos_vazias_sorted], key="aba2_pos_sel")

            with st.form("form_alimentar_lista", clear_on_submit=True):
                motivos_rapidos = [
                    "-- Selecione um Motivo Rápido (Opcional) --",
                    "Aguardando Jagura",
                    "Aguardando Almoxarifado",
                    "Aguardando PCP",
                    "Em Preparação",
                    "Em Sequência"
                ]
                motivo_select = st.selectbox("Motivo / Caminho Rápido:", motivos_rapidos, key="aba2_motivo")

                c_op, c_it = st.columns(2)
                ordem_in = c_op.text_input("Ordem de Produção (OP):", placeholder="Ex: 987654", key="aba2_op")
                item_in = c_it.text_input("Item / Peça:", placeholder="Ex: 313324", key="aba2_item")
                rebolo_in = st.text_input("Rebolo(s) Alocado (Opcional):", placeholder="Ex: REB 123", key="aba2_reb")
                obs_in = st.text_input("Observação Adicional:", placeholder="Detalhes...", key="aba2_obs")

                if st.form_submit_button("📥 GUARDAR NO ARMÁRIO", type="primary"):
                    obs_final = motivo_select if motivo_select != motivos_rapidos[0] else ""
                    if obs_in.strip():
                        obs_final = f"{obs_final} - {obs_in.strip()}" if obs_final else obs_in.strip()

                    if not ordem_in.strip() and not obs_final.strip(): 
                        st.error("⚠️ A Ordem (OP) ou um Motivo Rápido são obrigatórios!")
                    elif pos_sel is None: 
                        st.error("⚠️ Não há posições disponíveis selecionadas!")
                    else:
                        ordem_limpa = ordem_in.strip().upper().replace(".0", "").lstrip("0")
                        item_limpa = item_in.strip().upper().replace(".0", "").lstrip("0")
                        
                        novo_status = "AGUARDANDO MÁQUINA" if ordem_limpa else "VAZIO"
                        
                        idx = df_arm[(df_arm['Armario'] == armario_sel) & (df_arm['Posicao'] == str(pos_sel))].index
                        if not idx.empty:
                            df_arm.loc[idx, ['Ordem', 'Item', 'Status', 'Data_Hora', 'Observacao', 'Rebolo']] = [
                                ordem_limpa, item_limpa, novo_status, datetime.now(FUSO_BR).strftime("%H:%M"), obs_final, rebolo_in.strip()
                            ]
                            df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                            st.success(f"✅ Ferramental guardado para a MAQ {pos_sel} do {armario_sel}!")
                            st.rerun()
        else: 
            st.info("ℹ️ Apenas o perfil do Pré-Set e Administração pode inserir ou remover itens nos armários.")

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
            else: st.info("Nenhum alerta registrado ainda.")
        else: st.info("Nenhum alerta registrado ainda.")
            
    with aba4:
        st.markdown("#### 🔄 Alertas e Detalhamento de Rebolos")
        if st.session_state.get('perfil') in ['preset', 'adm']:
            st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Máquinas agendadas ou em andamento que necessitam de troca de rebolo.</p>", unsafe_allow_html=True)

            df_rebolos = pd.DataFrame()
            if os.path.exists(ARQUIVO_REBOLOS):
                try:
                    df_rebolos = pd.read_excel(ARQUIVO_REBOLOS, sheet_name='Banco De Rebolos', engine='openpyxl')
                    df_rebolos.columns = [unicodedata.normalize('NFKD', str(c).upper()).encode('ASCII', 'ignore').decode('ASCII').replace(" ", "").replace("\n", "").strip() for c in df_rebolos.columns]
                    if 'ITEM' in df_rebolos.columns:
                        df_rebolos['ITEM_BUSCA'] = df_rebolos['ITEM'].astype(str).str.upper().apply(lambda x: re.sub(r'\.0$', '', x.strip()).lstrip("0"))
                except: pass

            status_dict = ler_status_atual()
            alertas_rebolo = []
            
            for maq, st_val in status_dict.items():
                if "(C/ REBOLO)" in st_val.upper() and "PRODUZINDO" not in st_val.upper():
                    hora_alvo = ""
                    if "AGENDADA PARA" in st_val.upper():
                        try: hora_alvo = st_val.upper().split("AGENDADA PARA")[1].strip().split(" ")[0]
                        except: pass
                    elif "[AGENDADO:" in st_val.upper():
                        try: hora_alvo = st_val.upper().split("[AGENDADO:")[1].split("]")[0].strip()
                        except: pass
                    
                    st_limpo = st_val.split("[")[0].strip()
                    item_alvo, rebolo_gaveta = "", ""
                    try:
                        setor_maq, maq_num = maq.split(" ", 1)
                        gaveta_num = maq_num.split("-")[0]
                        filtro_armario = "Afiadoras" if setor_maq == "AFC" else "Retíficas"
                        gaveta_row = df_arm[(df_arm['Posicao'] == gaveta_num) & (df_arm['Armario'].str.contains(filtro_armario))]
                        if not gaveta_row.empty:
                            item_alvo = str(gaveta_row.iloc[0]['Item']).strip().replace('.0', '').replace('nan', '').lstrip("0")
                            rebolo_gaveta = str(gaveta_row.iloc[0].get('Rebolo', '')).replace('nan', '').strip()
                    except: pass
                        
                    if not item_alvo:
                        if "[Novo Item:" in st_val: item_alvo = st_val.split("[Novo Item:")[1].split("]")[0].strip()
                        elif "[Item Atual:" in st_val: item_alvo = st_val.split("[Item Atual:")[1].split("]")[0].strip()
                        elif "[Item:" in st_val: item_alvo = st_val.split("[Item:")[1].split("]")[0].strip()

                    reb1_db, reb2_db = "-", "-"
                    if item_alvo and not df_rebolos.empty:
                        item_busca = item_alvo.upper()
                        match = df_rebolos[df_rebolos['ITEM_BUSCA'] == item_busca]
                        if match.empty: match = df_rebolos[df_rebolos['ITEM_BUSCA'].str.contains(item_busca, regex=False, na=False)]
                        if not match.empty:
                            reb1_db = str(match.iloc[0].get('REBOLO', match.iloc[0].get('REBOLO1', ''))).strip()
                            reb2_db = str(match.iloc[0].get('REBOLO2', '')).strip()
                            if reb1_db.lower() in ['nan', 'none', '']: reb1_db = "-"
                            if reb2_db.lower() in ['nan', 'none', '']: reb2_db = "-"

                    alertas_rebolo.append((maq, hora_alvo, st_limpo, item_alvo, rebolo_gaveta, reb1_db, reb2_db))
                    
            if alertas_rebolo:
                for maq, hora, st_limpo, item_alvo, rebolo_gaveta, reb1_db, reb2_db in alertas_rebolo:
                    h_txt = f"⏰ Agendado para as {hora}" if hora else "🔴 Em Andamento / Imediato"
                    
                    reb_txt = rebolo_gaveta if rebolo_gaveta else "Não preenchido na gaveta."
                    
                    if item_alvo:
                        info_reb = f"""
                        <div style='background-color: #27272A; padding: 10px; border-radius: 6px; margin-top: 10px; border: 1px solid #3F3F46;'>
                            <p style='margin: 0; font-size: 13px; color: #A1A1AA;'>📦 Item na Gaveta/Máquina: <b style='color: #F4F4F5;'>{item_alvo}</b></p>
                            <p style='margin: 4px 0 0 0; font-size: 13px; color: #A1A1AA;'>🛞 Rebolo(s) Padrão (Excel): <b style='color: #38BDF8;'>{reb1_db} {f' / {reb2_db}' if reb2_db != '-' else ''}</b></p>
                            <p style='margin: 4px 0 0 0; font-size: 13px; color: #A1A1AA;'>🔄 Rebolo Cadastrado (Armário): <b style='color: #2DD4BF;'>{reb_txt}</b></p>
                        </div>"""
                    else:
                        info_reb = f"""<div style='background-color: #27272A; padding: 10px; border-radius: 6px; margin-top: 10px; border: 1px solid #3F3F46;'><p style='margin: 0; font-size: 13px; color: #ef4444;'>⚠️ Gaveta vazia e item não informado na máquina.</p></div>"""

                    st.markdown(f"""<div style='background-color: #422006; padding: 15px; border-radius: 8px; border-left: 5px solid #f59e0b; margin-bottom: 10px;'><h5 style='margin-top:0; margin-bottom:5px; color: #fbbf24;'>⚙️ Máquina {maq} irá trocar o rebolo</h5><p style='color: #fef3c7; margin-bottom:0; font-size:14px;'>{h_txt} <br><span style='font-size:13px; color:#d97706;'>Status Atual: {st_limpo}</span></p>{info_reb}</div>""", unsafe_allow_html=True)
            else: st.success("✅ Nenhuma máquina com troca de rebolo prevista no momento.")
        else: st.info("ℹ️ Aba restrita para os perfis de Pré-Set e Administração.")

    with aba5:
        st.markdown("#### 🔙 Registro de Devolução de Rebolo")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Registre rebolos que foram solicitados mas acabaram sendo devolvidos sem uso pelo preparador.</p>", unsafe_allow_html=True)
        
        if st.session_state['perfil'] in ['preset', 'adm']:
            with st.form("form_devolucao", clear_on_submit=True):
                col_d1, col_d2 = st.columns(2)
                prep_dev = col_d1.text_input("Nome do Preparador:", placeholder="Ex: Lucas", key="dev_prep")
                reb_dev = col_d2.text_input("Rebolo Devolvido:", placeholder="Ex: REB 123", key="dev_reb")
                motivo_dev = st.text_input("Motivo da Devolução:", placeholder="Ex: Peça já estava no dimensional, não precisou trocar...", key="dev_mot")
                
                if st.form_submit_button("💾 Registrar Devolução", type="primary"):
                    if not prep_dev.strip() or not reb_dev.strip() or not motivo_dev.strip():
                        st.error("⚠️ Preencha todos os campos (Preparador, Rebolo e Motivo)!")
                    else:
                        hora_br_str = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")
                        nova_dev = {"Data_Hora": hora_br_str, "Preparador": prep_dev.strip().upper(), "Rebolo": reb_dev.strip().upper(), "Motivo": motivo_dev.strip()}
                        ARQUIVO_DEVOLUCOES = "historico_devolucoes.csv"
                        
                        if os.path.exists(ARQUIVO_DEVOLUCOES):
                            df_dev = pd.read_csv(ARQUIVO_DEVOLUCOES)
                            df_dev = pd.concat([df_dev, pd.DataFrame([nova_dev])], ignore_index=True)
                            df_dev.to_csv(ARQUIVO_DEVOLUCOES, index=False)
                        else:
                            pd.DataFrame([nova_dev]).to_csv(ARQUIVO_DEVOLUCOES, index=False)
                            
                        st.success("✅ Devolução registrada com sucesso!")

                        st.rerun()
            
            st.divider()
            st.markdown("##### 📜 Histórico de Devoluções")
            ARQUIVO_DEVOLUCOES = "historico_devolucoes.csv"
            if os.path.exists(ARQUIVO_DEVOLUCOES):
                df_dev = pd.read_csv(ARQUIVO_DEVOLUCOES)
                if not df_dev.empty:
                    st.dataframe(df_dev.sort_values(by="Data_Hora", ascending=False), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma devolução registrada no histórico.")
            else:
                st.info("Nenhuma devolução registrada no histórico.")
        else:
            st.info("ℹ️ Apenas o perfil do Pré-Set e Administração pode registrar devoluções.")

    with aba6:
        st.markdown("#### ✏️ Edição de Armários em Lote")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Edite as gavetas diretamente na tabela, simulando um Excel. Ótimo para correções rápidas.</p>", unsafe_allow_html=True)
        if st.session_state['perfil'] in ['preset', 'adm']:
            df_arm_edit = df_arm.fillna("").copy()
            
            filtro_arm_lote = st.selectbox("Filtrar Armário (Tabela):", ["Todos", "Afiadoras 04 a 28", "Afiadoras 29 a 41", "Retíficas 05 a 28", "Retíficas 29 a 42"], key="aba6_filtro")
            if filtro_arm_lote != "Todos":
                df_exibir = df_arm_edit[df_arm_edit['Armario'] == filtro_arm_lote].copy()
            else:
                df_exibir = df_arm_edit.copy()
                
            config_colunas = {
                "Armario": st.column_config.TextColumn("Armário", disabled=True),
                "Posicao": st.column_config.TextColumn("Gaveta", disabled=True),
                "Ordem": st.column_config.TextColumn("OP"),
                "Item": st.column_config.TextColumn("Item"),
                "Status": st.column_config.SelectboxColumn("Status", options=["VAZIO", "OCUPADO", "SEPARADO", "AGUARDANDO MÁQUINA"]),
                "Rebolo": st.column_config.TextColumn("Rebolo"),
                "Data_Hora": st.column_config.TextColumn("Hora"),
                "Observacao": st.column_config.TextColumn("Observação")
            }
            
            df_editado = st.data_editor(df_exibir, column_config=config_colunas, use_container_width=True, hide_index=True)
            
            if st.button("💾 Salvar Alterações em Lote", type="primary", use_container_width=True):
                for idx, row in df_editado.iterrows():
                    mask = (df_arm['Armario'] == row['Armario']) & (df_arm['Posicao'] == row['Posicao'])
                    df_arm.loc[mask, 'Ordem'] = str(row['Ordem']).strip()
                    df_arm.loc[mask, 'Item'] = str(row['Item']).strip()
                    df_arm.loc[mask, 'Rebolo'] = str(row['Rebolo']).strip()
                    df_arm.loc[mask, 'Status'] = str(row['Status']).strip()
                    df_arm.loc[mask, 'Data_Hora'] = str(row['Data_Hora']).strip()
                    df_arm.loc[mask, 'Observacao'] = str(row['Observacao']).strip()
                df_arm.to_csv(ARQUIVO_ARMARIOS, index=False)
                st.success("✅ Armários atualizados em lote com sucesso!")
                st.rerun()
        else:
            st.info("ℹ️ Apenas o perfil do Pré-Set e Administração pode editar as gavetas em lote.")

def tela_lirs():
    botao_navegar("⬅ Voltar à Central", 'hub_relatorios')
        
    st.markdown("#### 🧹 LIRS - Auditoria e Liberação de Linha")
    st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Processo padronizado de validação de setup e passagem de turno.</p>", unsafe_allow_html=True)
    
    turno_atual = st.session_state.get('turno', 'DESCONHECIDO')
    status_dict = ler_status_atual()
    
    aba_execucao, aba_relatorio = st.tabs(["📋 Painel de Auditoria", "📊 Relatório Consolidado"])
    
    with aba_execucao:
        c_s1, c_s2 = st.columns(2)
        c_s1.button("🏭 SETOR AFIAÇÃO", type="primary" if st.session_state['lirs_setor'] == 'AFC' else "secondary", use_container_width=True, on_click=definir_estados, args=({'lirs_setor': 'AFC', 'celula_selecionada': None, 'lirs_maq_ativa': None},))
        c_s2.button("🏭 SETOR RETÍFICA", type="primary" if st.session_state['lirs_setor'] == 'RTF' else "secondary", use_container_width=True, on_click=definir_estados, args=({'lirs_setor': 'RTF', 'celula_selecionada': None, 'lirs_maq_ativa': None},))

        setor = st.session_state['lirs_setor']
        st.divider()

        if st.session_state['celula_selecionada'] is None:
            st.button("📍 Fila 1", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_1'))
            st.button("📍 Fila 2", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_2'))
            st.button("📍 Fila 3", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_3'))
            st.button("📍 Fila 4", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'fila_4'))
            if setor == 'RTF':
                st.markdown("<hr style='margin: 10px 0px; border-color: #27272A;'>", unsafe_allow_html=True)
                st.button("⚫ Centerless (CNC1)", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'centerless'))
                st.button("🟤 Facetadoras (CNC2)", use_container_width=True, on_click=definir_estado, args=('celula_selecionada', 'facetadoras'))
        else:
            st.button("⬅️ Voltar à Seleção de Fila", on_click=definir_estados, args=({'celula_selecionada': None, 'lirs_maq_ativa': None},))
            
            maquinas_foco = []
            if setor == 'AFC':
                if st.session_state['celula_selecionada'] == 'fila_1': maquinas_foco = ["6-868", "9-088", "7-743", "11-365", "13-964", "15-973", "17-140", "19-760", "21-206", "23-165", "25-209", "27-431"]
                elif st.session_state['celula_selecionada'] == 'fila_2': maquinas_foco = ["8-247", "4-427", "10-812", "12-367", "14-967", "16-975", "18-957", "20-774", "22-813", "24-761", "26-635", "28-432"]
                elif st.session_state['celula_selecionada'] == 'fila_3': maquinas_foco = ["29-078", "31-969", "33-160", "35-131", "37-892", "39-905", "41-141"]
                elif st.session_state['celula_selecionada'] == 'fila_4': maquinas_foco = ["30-161", "32-081", "34-132", "36-084", "38-596", "40-142"]
            else:
                tipos_dict = ler_tipos_cnc()
                base_f1 = ["5-903", "8-086", "10-817", "12-962", "14-971", "16-183", "19-926", "21-270", "23-753", "25-258", "27-917"]
                base_f2 = ["7-267", "9-815", "11-363", "13-969", "15-977", "18-925", "20-927", "22-916", "24-259", "26-260", "28-954"]
                base_f3 = ["29-785", "31-806", "33-807", "35-885", "37-857", "39-856"]
                base_f4 = ["30-786", "32-918", "34-842", "36-854", "38-881", "40-912", "42-885"]
                todas_cnc1 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC1"]
                todas_cnc2 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC2"]
                todas_cnc3 = [m for m in TODAS_RTF if tipos_dict.get(m) == "RTF_CNC3"]
                
                if st.session_state['celula_selecionada'] == 'fila_1': maquinas_foco = [m for m in base_f1 if m in todas_cnc3]
                elif st.session_state['celula_selecionada'] == 'fila_2': maquinas_foco = [m for m in base_f2 if m in todas_cnc3]
                elif st.session_state['celula_selecionada'] == 'fila_3': maquinas_foco = [m for m in base_f3 if m in todas_cnc3]
                elif st.session_state['celula_selecionada'] == 'fila_4': 
                    nativos = set(base_f1 + base_f2 + base_f3 + base_f4)
                    extraviados = [m for m in todas_cnc3 if m not in nativos]
                    maquinas_foco = [m for m in base_f4 if m in todas_cnc3] + extraviados
                elif st.session_state['celula_selecionada'] == 'centerless': maquinas_foco = todas_cnc1
                elif st.session_state['celula_selecionada'] == 'facetadoras': maquinas_foco = todas_cnc2

            st.markdown(f"**Máquinas em Exibição: {str(st.session_state['celula_selecionada']).upper().replace('_', ' ')}**")
            
            maq_ativa = st.session_state.get('lirs_maq_ativa')
            if maq_ativa:
                st.markdown(f"""
                <div style='background-color: #121214; padding: 15px; border: 2px solid #14B8A6; border-radius: 8px; margin-bottom: 20px;'>
                    <h4 style='color: #5EEAD4; margin-top:0;'>📋 AUDITORIA MÁQUINA {maq_ativa}</h4>
                    <p style='color: #A1A1AA; font-size: 14px; margin-bottom: 0;'>Turno de Assunção: <b>{turno_atual}</b> | Auditor: <b>{st.session_state.get('operador', 'SISTEMA')}</b></p>
                </div>
                """, unsafe_allow_html=True)
                
                with st.form(f"form_checklist_{maq_ativa}"):
                    st.markdown("<p style='font-size: 14px; color: #E4E4E7; margin-bottom: 15px;'>Confirme os 4 pilares operacionais para efetivar a passagem de turno:</p>", unsafe_allow_html=True)
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("""
                        <div style='background-color: #18181B; padding: 12px; border-radius: 8px; border: 1px solid #27272A; margin-bottom: 10px;'>
                            <b style='color: #2DD4BF; font-size: 15px;'>🧹 L - Limpeza</b><br>
                            <span style='font-size: 12px; color: #A1A1AA;'>Posto de trabalho e máquina limpos, sem ferramentas soltas ou sujeira excessiva.</span>
                        </div>
                        """, unsafe_allow_html=True)
                        l_check = st.toggle("Confirmar Limpeza", key="l_chk")
                        
                        st.markdown("""
                        <div style='background-color: #18181B; padding: 12px; border-radius: 8px; border: 1px solid #27272A; margin-bottom: 10px; margin-top: 15px;'>
                            <b style='color: #2DD4BF; font-size: 15px;'>⚖️ R - Reconciliação</b><br>
                            <span style='font-size: 12px; color: #A1A1AA;'>Contagem física coerente com a OP e garantia total de ausência de peças de outros lotes.</span>
                        </div>
                        """, unsafe_allow_html=True)
                        r_check = st.toggle("Confirmar Reconciliação", key="r_chk")

                    with col2:
                        st.markdown("""
                        <div style='background-color: #18181B; padding: 12px; border-radius: 8px; border: 1px solid #27272A; margin-bottom: 10px;'>
                            <b style='color: #2DD4BF; font-size: 15px;'>🏷️ I - Identificação</b><br>
                            <span style='font-size: 12px; color: #A1A1AA;'>Caixas, lotes, gabaritos e OP devidamente sinalizados com as etiquetas corretas.</span>
                        </div>
                        """, unsafe_allow_html=True)
                        i_check = st.toggle("Confirmar Identificação", key="i_chk")
                        
                        st.markdown("""
                        <div style='background-color: #18181B; padding: 12px; border-radius: 8px; border: 1px solid #27272A; margin-bottom: 10px; margin-top: 15px;'>
                            <b style='color: #2DD4BF; font-size: 15px;'>🚧 S - Segregação</b><br>
                            <span style='font-size: 12px; color: #A1A1AA;'>Peças aprovadas, caixas de refugo (vermelhas) e retrabalho rigidamente separadas.</span>
                        </div>
                        """, unsafe_allow_html=True)
                        s_check = st.toggle("Confirmar Segregação", key="s_chk")

                    st.markdown("<hr style='border-color: #27272A; margin: 20px 0;'>", unsafe_allow_html=True)
                    obs_lirs = st.text_input("📝 Registro de Anomalias (Opcional):", placeholder="Relate qualquer desvio tratado durante a auditoria (ex: Faltou recolher sucata, caixa sem etiqueta...)")

                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.form_submit_button("✅ APROVAR AUDITORIA E LIBERAR EQUIPAMENTO", type="primary", use_container_width=True):
                        if not all([l_check, i_check, r_check, s_check]):
                            st.error("⚠️ Aprovação Bloqueada: É obrigatório acionar (validar) os 4 interruptores do LIRS para liberar a máquina.")
                        else:
                            info_atual = obter_info_maquina(maq_ativa, setor)
                            if info_atual:
                                st_atual = str(info_atual['Status'])
                                st_atual = re.sub(r' \[LIRS:.*?\]', '', st_atual) 
                                
                                obs_txt = f" - Obs: {obs_lirs.strip()}" if obs_lirs.strip() else ""
                                st_final = f"{st_atual} [LIRS: OK {turno_atual}{obs_txt}]"
                                
                                hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                                salvar_csv({"Setor": setor, "Maquina": f"{setor} {maq_ativa}", "Operador": st.session_state['operador'], "Status": st_final, "Hora": hora_br_str}, ARQUIVO_DADOS)
                                
                                st.session_state['lirs_maq_ativa'] = None
                                st.success(f"✅ Equipamento {maq_ativa} auditado e liberado para produção do {turno_atual}!")
                                st.rerun()

            for maq in ordenar_maquinas(maquinas_foco):
                st_val = status_dict.get(f"{setor} {maq}", "")
                tag_lirs_atual = f"[LIRS: OK {turno_atual}"
                
                if tag_lirs_atual in st_val: cor_btn = "🟢 VALIDADO"
                else: cor_btn = "🔴 PENDENTE"
                    
                label_botao = f"{cor_btn} - EQUIPAMENTO {maq}"
                if st.button(label_botao, key=f"lirs_btn_{maq}", use_container_width=True):
                    if tag_lirs_atual in st_val:
                        st.toast(f"A auditoria da máquina {maq} já foi efetivada neste turno!", icon="✅")
                    st.session_state['lirs_maq_ativa'] = maq
                    st.rerun()

    with aba_relatorio:
        st.markdown(f"#### 📊 Consolidado de Liberação de Linha - {turno_atual}")
        st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Painel atualizado em tempo real com o status de cumprimento da auditoria fabril.</p>", unsafe_allow_html=True)
        
        tag_busca = f"[LIRS: OK {turno_atual}"
        
        ok_afc = []
        pend_afc = []
        ok_rtf = []
        pend_rtf = []
        
        for m in TODAS_AFC:
            st_val = status_dict.get(f"AFC {m}", "")
            if tag_busca in st_val: ok_afc.append(m)
            else: pend_afc.append(m)
            
        for m in TODAS_RTF:
            st_val = status_dict.get(f"RTF {m}", "")
            if tag_busca in st_val: ok_rtf.append(m)
            else: pend_rtf.append(m)
            
        ok_afc = ordenar_maquinas(ok_afc)
        pend_afc = ordenar_maquinas(pend_afc)
        ok_rtf = ordenar_maquinas(ok_rtf)
        pend_rtf = ordenar_maquinas(pend_rtf)

        c_rel1, c_rel2 = st.columns(2)
        with c_rel1:
            st.markdown(f"##### 🏭 AFIAÇÃO")
            st.markdown(f"<span style='color: #2DD4BF; font-weight: bold;'>✅ LIBERADAS: {len(ok_afc)}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color: #ef4444; font-weight: bold;'>🔴 PENDENTES: {len(pend_afc)}</span>", unsafe_allow_html=True)
        
        with c_rel2:
            st.markdown(f"##### 🏭 RETÍFICA")
            st.markdown(f"<span style='color: #2DD4BF; font-weight: bold;'>✅ LIBERADAS: {len(ok_rtf)}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color: #ef4444; font-weight: bold;'>🔴 PENDENTES: {len(pend_rtf)}</span>", unsafe_allow_html=True)
            
        st.divider()
        st.markdown("**Copiar Relatório Executivo (WhatsApp/E-mail):**")
        
        texto_relatorio = f"*FECHAMENTO DE AUDITORIA LIRS - {turno_atual}*\n\n"
        
        texto_relatorio += f"*⚙️ SETOR DE AFIAÇÃO (AFC)*\n"
        texto_relatorio += f"✅ VALIDADAS ({len(ok_afc)}): {', '.join(ok_afc) if ok_afc else 'Nenhuma'}\n"
        texto_relatorio += f"🔴 PENDENTES ({len(pend_afc)}): {', '.join(pend_afc) if pend_afc else 'Nenhuma'}\n\n"
        
        texto_relatorio += f"*⚙️ SETOR DE RETÍFICA (RTF)*\n"
        texto_relatorio += f"✅ VALIDADAS ({len(ok_rtf)}): {', '.join(ok_rtf) if ok_rtf else 'Nenhuma'}\n"
        texto_relatorio += f"🔴 PENDENTES ({len(pend_rtf)}): {', '.join(pend_rtf) if pend_rtf else 'Nenhuma'}\n"
        
        st.code(texto_relatorio, language="text")

def tela_programador():
    botao_navegar("⬅ Voltar ao Menu", 'menu')
    st.markdown("#### 💻 Painel de Programação CNC")
    st.markdown("<p style='font-size: 13px; color: #A1A1AA;'>Visualize as preparações e confirme o envio dos programas para as máquinas.</p>", unsafe_allow_html=True)
    st.divider()

    status_dict = ler_status_atual()
    lista_incidencias = []
    
    df_arm = pd.read_csv(ARQUIVO_ARMARIOS, dtype=str) if os.path.exists(ARQUIVO_ARMARIOS) else pd.DataFrame()
    
    for m in TODAS_AFC + TODAS_RTF:
        prefixo = "AFC" if m in TODAS_AFC else "RTF"
        st_val = status_dict.get(f"{prefixo} {m}", "PRODUZINDO")
        
        if any(x in st_val.upper() for x in ["PREPARAÇÃO", "PREPARANDO", "AGUARDANDO", "SEQUÊNCIA", "AGENDADA", "AGENDADO", "MANUTENÇÃO"]):
            lista_incidencias.append((prefixo, m, st_val))

    if not lista_incidencias:
        st.success("✨ Nenhuma máquina em preparação ou agendada aguardando programa no momento.")
        return

    lista_afc = [item for item in lista_incidencias if item[0] == "AFC"]
    lista_rtf = [item for item in lista_incidencias if item[0] == "RTF"]

    def render_grid_setor_prog(lista_setor, titulo_setor):
        if not lista_setor: return
        st.markdown(f"<h5 style='color: #2DD4BF; margin-top: 20px; border-bottom: 2px solid #27272A; padding-bottom: 8px;'>🏭 {titulo_setor}</h5>", unsafe_allow_html=True)
        
        for i in range(0, len(lista_setor), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(lista_setor):
                    setor_m, maq_m, st_m = lista_setor[i + j]
                    
                    is_seq = "SEQUÊNCIA" in st_m.upper() or "SEQUENCIA" in st_m.upper()
                    is_prep = "PREPARAÇÃO" in st_m.upper() or "PREPARACAO" in st_m.upper() or "PREPARANDO" in st_m.upper()
                    is_guia = "GUIA" in st_m.upper()
                    is_preparando = "PREPARANDO" in st_m.upper()
                    is_manutencao = "MANUTENÇÃO" in st_m.upper()
                    is_prog_ok = "[PROG: OK" in st_m.upper()
                    
                    tipo_setup = "Outro"
                    if is_seq:
                        tipo_setup = "Sequência"
                    elif is_prep:
                        if "HASTE" in st_m.upper(): tipo_setup = "Preparação - HASTE"
                        elif is_guia: tipo_setup = "Preparação - GUIA"
                        else: tipo_setup = "Preparação"
                    elif is_manutencao:
                        tipo_setup = "Manutenção"
                    
                    if is_manutencao:
                        bg_color, bd_color = "#3F1515", "#EF4444" 
                        status_label_txt = "Em Manutenção"
                    elif is_preparando:
                        bg_color, bd_color = "#172554", "#3B82F6" 
                        status_label_txt = "Em Preparação (Executando)"
                    elif is_prog_ok:
                        bg_color, bd_color = "#022C22", "#10B981" 
                        status_label_txt = "Agendado / Programa OK"
                    else:
                        bg_color, bd_color = "#451A03", "#F59E0B" 
                        status_label_txt = "Agendado / Sem Programa"

                    preparador = "Sugerir / Aguardando..."
                    if "[Prep:" in st_m: preparador = st_m.split("[Prep:")[1].split("]")[0].strip()
                    elif "[Prep. Sugerido:" in st_m: preparador = st_m.split("[Prep. Sugerido:")[1].split("]")[0].strip()
                    elif "[PREP:" in st_m.upper(): preparador = st_m.upper().split("[PREP:")[1].split("]")[0].strip()

                    op_maq, item_maq = "", ""
                    if "[Ordem:" in st_m:
                        try: op_maq = st_m.split("[Ordem:")[1].split("]")[0].strip()
                        except: pass
                    if "[Novo Item:" in st_m:
                        try: item_maq = st_m.split("[Novo Item:")[1].split("]")[0].strip()
                        except: pass
                    elif "[Item Atual:" in st_m:
                        try: item_maq = st_m.split("[Item Atual:")[1].split("]")[0].strip()
                        except: pass

                    op_arm, item_arm = "", ""
                    if not df_arm.empty:
                        gaveta_num = maq_m.split("-")[0]
                        filtro_arm = "Afiadoras" if setor_m == "AFC" else "Retíficas"
                        gaveta_row = df_arm[(df_arm['Posicao'] == str(gaveta_num)) & (df_arm['Armario'].str.contains(filtro_arm))]
                        if not gaveta_row.empty and str(gaveta_row.iloc[0]['Status']).strip() != 'VAZIO':
                            op_arm = str(gaveta_row.iloc[0].get('Ordem', '')).replace('.0', '').replace('nan', '').strip()
                            item_arm = str(gaveta_row.iloc[0].get('Item', '')).replace('.0', '').replace('nan', '').strip()

                    # --- CORREÇÃO DE PRIORIDADE: ARMÁRIO TEM PRIORIDADE MÁXIMA ---
                    if is_guia:
                        item_guia = item_arm if item_arm else (item_maq if item_maq else obter_item_rodando_atual(f"{setor_m} {maq_m}"))
                        final_item = item_guia if item_guia else "-"
                        label_item_txt = "Item Rodando (Atual)"
                        final_op = op_arm if op_arm else (op_maq if op_maq else "Manter Atual")
                    else:
                        final_op = op_arm if op_arm else (op_maq if op_maq else "Nenhuma")
                        final_item = item_arm if item_arm else (item_maq if item_maq else "-")
                        label_item_txt = "Item"

                    h_alvo = ""
                    if "AGENDADA PARA" in st_m.upper():
                        try: h_alvo = st_m.upper().split('AGENDADA PARA')[1].strip().split(" ")[0]
                        except: pass
                    elif "[AGENDADO:" in st_m.upper():
                        try: h_alvo = st_m.upper().split('[AGENDADO:')[1].split(']')[0].strip()
                        except: pass

                    if h_alvo:
                        tempo_ou_status_html = f"<div style='margin: 0 0 4px 0;'><strong style='font-size: 14px; color: #A1A1AA;'>⏰ Agendado para:</strong> <span style='font-size: 14px; color: #E4E4E7;'>{h_alvo}</span></div>"
                    else:
                        tempo_ou_status_html = f"<div style='margin: 0 0 4px 0;'><strong style='font-size: 14px; color: #A1A1AA;'>📌 Status:</strong> <span style='font-size: 14px; color: #E4E4E7;'>{status_label_txt}</span></div>"
                    
                    html = f"""
                    <div class='postit-prog' style='background-color: {bg_color}; padding: 15px; border-radius: 8px; border: 1px solid #27272A; border-top: 4px solid {bd_color}; margin-bottom: 10px; min-height: 220px;'>
                        <div style='margin: 0 0 10px 0; border-bottom: 1px solid #27272A; padding-bottom: 5px;'>
                            <strong style='font-size: 16px; color: #F4F4F5;'>⚙️ {setor_m} {maq_m}</strong>
                        </div>
                        {tempo_ou_status_html}
                        <div style='margin: 0 0 4px 0;'><strong style='font-size: 14px; color: #A1A1AA;'>📋 Tipo Setup:</strong> <span style='font-size: 14px; color: #E4E4E7;'>{tipo_setup}</span></div>
                        <div style='margin: 0 0 8px 0;'><strong style='font-size: 14px; color: #A1A1AA;'>🧑‍🔧 Preparador:</strong> <span style='font-size: 14px; color: #E4E4E7;'>{preparador}</span></div>
                        <div style='background: #09090B; padding: 8px; border-radius: 6px; margin-bottom: 10px; border: 1px solid #27272A;'>
                            <div style='margin: 0 0 2px 0;'><strong style='font-size: 13px; color: #A1A1AA;'>OP:</strong> <span style='font-size: 13px; color: #2DD4BF;'>{final_op}</span></div>
                            <div style='margin: 0;'><strong style='font-size: 13px; color: #A1A1AA;'>{label_item_txt}:</strong> <span style='font-size: 13px; color: #2DD4BF;'>{final_item}</span></div>
                        </div>
                    </div>
                    """
                    cols[j].markdown(html, unsafe_allow_html=True)
                    
                    if is_prog_ok:
                        if cols[j].button("❌ Desmarcar Prog. OK", key=f"btn_unprog_{setor_m}_{maq_m}", use_container_width=True):
                            info_atual = obter_info_maquina(maq_m, setor_m)
                            if info_atual:
                                raw_st = str(info_atual['Status'])
                                raw_st = re.sub(r' \[Prog:.*?\]', '', raw_st, flags=re.IGNORECASE)
                                raw_st += " [Prog: NOK]"
                                hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                                salvar_csv({"Setor": setor_m, "Maquina": f"{setor_m} {maq_m}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": hora_br_str}, ARQUIVO_DADOS)
                                st.success("✅ Programa alterado para NOK!")
                                st.rerun()
                    else:
                        if cols[j].button("✅ Validar / Enviar Programa", key=f"btn_okprog_{setor_m}_{maq_m}", type="primary", use_container_width=True):
                            info_atual = obter_info_maquina(maq_m, setor_m)
                            if info_atual:
                                raw_st = str(info_atual['Status'])
                                raw_st = re.sub(r' \[Prog:.*?\]', '', raw_st, flags=re.IGNORECASE)
                                raw_st += " [Prog: OK]"
                                hora_br_str = datetime.now(FUSO_BR).strftime("%H:%M")
                                salvar_csv({"Setor": setor_m, "Maquina": f"{setor_m} {maq_m}", "Operador": st.session_state['operador'], "Status": raw_st, "Hora": hora_br_str}, ARQUIVO_DADOS)
                                st.success("✅ Programa validado como OK!")
                                st.rerun()

    render_grid_setor_prog(lista_afc, "AFIAÇÃO (AFC)")
    render_grid_setor_prog(lista_rtf, "RETÍFICA (RTF)")

# --- ROTEAMENTO DE TELAS ---
# Navegação nativa: sem query string e sem reload completo do navegador.
tela = st.session_state['tela_atual']

if tela != 'login' and st.session_state.get('operador'):
    renderizar_topbar(tela)

if tela == 'login': tela_login()
elif tela == 'menu': tela_menu()
elif tela == 'visao_geral': tela_visao_geral()
elif tela == 'checkup': tela_checkup()
elif tela == 'minhas_incidencias': tela_minhas_incidencias()
elif tela == 'afc': tela_afc()
elif tela == 'rtf': tela_rtf()
elif tela == 'armarios': tela_armarios()
elif tela == 'equipe': tela_equipe()
elif tela == 'editar': tela_editar()
elif tela == 'historico': tela_historico()
elif tela == 'hub_relatorios': tela_hub_relatorios()
elif tela == 'relatorio': tela_relatorio()
elif tela == 'lirs': tela_lirs()
elif tela == 'programador': tela_programador()