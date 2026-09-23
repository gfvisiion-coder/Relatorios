import pandas as pd
import sqlite3
import os

# 1. Cria ou conecta ao novo banco de dados SQLite
conexao = sqlite3.connect("banco_app.db")

# 2. Transfere o arquivo principal de dados (se existir)
if os.path.exists("banco_operacao.csv"):
    df_dados = pd.read_csv("banco_operacao.csv")
    # Salva dentro do SQLite numa tabela chamada 'operacoes'
    df_dados.to_sql("operacoes", conexao, if_exists="replace", index=False)
    print("banco_operacao.csv migrado com sucesso!")

# 3. Transfere os armários
if os.path.exists("banco_armarios.csv"):
    df_armarios = pd.read_csv("banco_armarios.csv")
    df_armarios.to_sql("armarios", conexao, if_exists="replace", index=False)
    print("banco_armarios.csv migrado com sucesso!")

conexao.close()
print("Migração concluída! Seus dados antigos estão seguros no banco_app.db")