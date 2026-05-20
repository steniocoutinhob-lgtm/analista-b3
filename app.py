import streamlit as st
import json
import os
import hashlib
from datetime import datetime
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# ============================================
# CONFIGURAÇÃO
# ============================================
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
DRIVE_FOLDER_ID  = st.secrets["DRIVE_FOLDER_ID"]
ALLOWED_USERS    = st.secrets["ALLOWED_USERS"]

PASTA_ANUAIS  = st.secrets["PASTA_ANUAIS"]
PASTA_TRIM    = st.secrets["PASTA_TRIM"]
PASTA_FATOS   = st.secrets["PASTA_FATOS"]

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

# ============================================
# AUTENTICAÇÃO SIMPLES
# ============================================
def verificar_login(usuario, senha):
    usuarios = json.loads(st.secrets["USUARIOS"])
    return usuarios.get(usuario) == senha

def tela_login():
    st.set_page_config(page_title="Analista B3", page_icon="📊", layout="centered")
    st.title("📊 Analista de Investimentos B3")
    st.subheader("Login")
    usuario = st.text_input("Usuário")
    senha   = st.text_input("Senha", type="password")
    if st.button("Entrar", use_container_width=True):
        if verificar_login(usuario, senha):
            st.session_state["logado"] = True
            st.session_state["usuario"] = usuario
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos!")

# ============================================
# GOOGLE DRIVE
# ============================================
@st.cache_resource
def conectar_drive():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)

def listar_arquivos(service, folder_id):
    result = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name)",
        pageSize=500
    ).execute()
    return {f["name"]: f["id"] for f in result.get("files", [])}

def ler_arquivo_drive(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    try:
        return fh.read().decode("utf-8")
    except:
        return fh.read().decode("latin1")

@st.cache_data(ttl=300)
def carregar_indicadores(_service):
    arquivos = listar_arquivos(_service, DRIVE_FOLDER_ID)
    if "indicadores_mercado.txt" in arquivos:
        return ler_arquivo_drive(_service, arquivos["indicadores_mercado.txt"])
    return ""

@st.cache_data(ttl=300)
def carregar_tickers_json(_service):
    arquivos = listar_arquivos(_service, DRIVE_FOLDER_ID)
    if "tickers_b3.json" in arquivos:
        conteudo = ler_arquivo_drive(_service, arquivos["tickers_b3.json"])
        dados = json.loads(conteudo)
        result = {}
        if isinstance(dados, dict):
            for t, info in dados.items():
                if isinstance(info, dict):
                    result[t] = {"nome": info.get("empresa", t), "segmento": info.get("segmento", "")}
                else:
                    result[t] = {"nome": t, "segmento": ""}
        return result
    return {}

def buscar_arquivo_pasta(service, folder_id, termos):
    arquivos = listar_arquivos(service, folder_id)
    for termo in termos:
        t = termo.upper().replace(" ", "").replace("-", "").replace("_", "")
        for nome, fid in arquivos.items():
            n = nome.upper().replace(" ", "").replace("-", "").replace("_", "")
            if t[:10] in n or n.startswith(t[:10]):
                return ler_arquivo_drive(service, fid)
    return ""

# ============================================
# SYSTEM PROMPT
# ============================================
SYSTEM_PROMPT = """Você é um analista de investimentos sênior especializado no mercado brasileiro de capitais (B3).

REGRAS ABSOLUTAS:
1. Use APENAS os dados fornecidos no contexto. NUNCA use conhecimento externo.
2. NUNCA invente números. Se não tiver o dado, escreva "Não disponível no arquivo".
3. Nunca recomende compra ou venda.
4. Responda sempre em português brasileiro.
5. Os valores nos arquivos estão em R$ mil. Converta para bilhões dividindo por 1.000.000.

ESTRUTURA OBRIGATÓRIA:
1. VISÃO GERAL
2. DRE (Receita, Margens, Lucro)
3. BALANÇO PATRIMONIAL
4. INDICADORES CALCULADOS (tabela)
5. VALUATION DE MERCADO (tabela)
6. FATOS RELEVANTES (linha do tempo com impacto)
7. ANÁLISE INTEGRADA
8. GRAU DE RISCO (5 dimensões 1-5, média, classificação 🟢🟡🔴)
9. PONTOS FORTES ✅ e PONTOS DE ATENÇÃO ⚠️
10. TABELA RESUMO FINAL

⚠️ Esta análise é informativa e não constitui recomendação de investimento."""

# ============================================
# MAPEAMENTOS
# ============================================
NOMES = {
    "petrobras": "PETR4", "petrobrás": "PETR4",
    "vale": "VALE3",
    "itaú": "ITUB4", "itau": "ITUB4",
    "bradesco": "BBDC4",
    "banco do brasil": "BBAS3",
    "santander": "SANB11",
    "btg": "BPAC11", "btg pactual": "BPAC11",
    "weg": "WEGE3", "ambev": "ABEV3",
    "suzano": "SUZB3", "klabin": "KLBN11",
    "gerdau": "GGBR4", "usiminas": "USIM5",
    "csn mineração": "CMIN3", "csn mineracao": "CMIN3",
    "csn": "CSNA3", "prio": "PRIO3",
    "engie": "EGIE3", "equatorial": "EQTL3",
    "cemig": "CMIG4", "copel": "CPLE6",
    "taesa": "TAEE11", "alupar": "ALUP11",
    "eletrobras": "ELET3", "neoenergia": "NEOE3",
    "sabesp": "SBSP3", "copasa": "CSMG3",
    "sanepar": "SAPR11", "localiza": "RENT3",
    "rumo": "RAIL3", "embraer": "EMBJ3",
    "jbs": "JBSS3", "marfrig": "MRFG3",
    "totvs": "TOTS3", "magazine luiza": "MGLU3",
    "magalu": "MGLU3", "renner": "LREN3",
    "hypera": "HYPE3", "fleury": "FLRY3",
    "hapvida": "HAPV3", "multiplan": "MULT3",
    "cosan": "CSAN3", "ultrapar": "UGPA3",
    "vibra": "VBBR3", "cogna": "COGN3",
    "porto seguro": "PSSA3", "bb seguridade": "BBSE3",
    "caixa seguridade": "CXSE3", "irb": "IRBR3",
    "natura": "NTCO3", "azul": "AZUL4",
    "gol": "GOLL4", "braskem": "BRKM5",
}

SEGMENTOS = {
    "banco": "Bancos", "bancário": "Bancos", "bancos": "Bancos",
    "energia": "Energia Elétrica", "elétrico": "Energia Elétrica",
    "siderurgia": "Siderurgia", "aço": "Siderurgia",
    "mineração": "Mineração", "mineracao": "Mineração", "mineção": "Mineração",
    "petróleo": "Petróleo", "petroleo": "Petróleo",
    "papel": "Papel", "celulose": "Papel",
    "telecom": "Telecomunicações", "telefonia": "Telecomunicações",
    "educação": "Educação", "ensino": "Educação",
    "seguro": "Seguros", "seguros": "Seguros", "seguradora": "Seguros",
    "saneamento": "Saneamento",
    "alimento": "Alimentos", "alimentos": "Alimentos",
    "shopping": "Shopping Centers", "imóvel": "Shopping Centers",
    "rodovia": "Rodovias",
    "construção": "Construção", "incorporação": "Construção",
    "saúde": "Saúde", "hospital": "Saúde",
    "tecnologia": "Tecnologia", "software": "Tecnologia",
    "varejo": "Varejo", "vestuário": "Varejo",
    "calçado": "Calçados",
    "transporte": "Transporte", "logística": "Transporte",
    "agro": "Agricultura", "agrícola": "Agricultura",
    "farmacêutico": "Medicamentos", "farmácia": "Medicamentos",
    "açúcar": "Agricultura", "etanol": "Agricultura",
    "carne": "Alimentos", "frigorífico": "Alimentos",
}

MAPA_ARQUIVOS = {
    "PETR4": ["PETROLEO BRASILEIRO", "PETROBRAS"],
    "VALE3": ["VALE SA"], "ITUB4": ["ITAU UNIBANCO"],
    "BBDC4": ["BCO BRADESCO"], "BBAS3": ["BCO BRASIL"],
    "SANB11": ["BCO SANTANDER"], "BPAC11": ["BCO BTG PACTUAL"],
    "WEGE3": ["WEG SA"], "ABEV3": ["AMBEV SA"],
    "SUZB3": ["SUZANO SA"], "KLBN11": ["KLABIN SA"],
    "GGBR4": ["GERDAU SA"], "USIM5": ["USINAS SID"],
    "CMIN3": ["CSN MINERACAO"], "CSNA3": ["CIA SIDERURGICA NACIONAL"],
    "PRIO3": ["PETRO RIO"], "EGIE3": ["ENGIE BRASIL"],
    "EQTL3": ["EQUATORIAL SA"], "CMIG4": ["CIA ENERG MINAS"],
    "CPLE6": ["CIA PARANAENSE"], "TAEE11": ["TRANSMISSORA ALIANCA"],
    "ALUP11": ["ALUPAR INVESTIMENTO"], "ELET3": ["CENTRAIS ELET BRAS"],
    "NEOE3": ["NEOENERGIA SA"], "ENGI11": ["ENERGISA SA"],
    "SBSP3": ["CIA SANEAMENTO BASICO"], "CSMG3": ["CIA SANEAMENTO MINAS"],
    "SAPR11": ["CIA SANEAMENTO PARANA"], "RENT3": ["LOCALIZA RENT"],
    "RAIL3": ["RUMO SA"], "EMBJ3": ["EMBRAER SA"],
    "JBSS3": ["JBS SA"], "MRFG3": ["MARFRIG"],
    "TOTS3": ["TOTVS SA"], "MGLU3": ["MAGAZINE LUIZA"],
    "LREN3": ["LOJAS RENNER"], "RADL3": ["RAIA DROGASIL"],
    "HYPE3": ["HYPERA SA"], "FLRY3": ["FLEURY SA"],
    "RDOR3": ["REDE DOR"], "HAPV3": ["HAPVIDA"],
    "MULT3": ["MULTIPLAN"], "CSAN3": ["COSAN SA"],
    "UGPA3": ["ULTRAPAR"], "VBBR3": ["VIBRA ENERGIA"],
    "COGN3": ["COGNA EDUCACAO"], "PSSA3": ["PORTO SEGURO SA"],
    "BBSE3": ["BB SEGURIDADE"], "CXSE3": ["CAIXA SEGURIDADE"],
    "IRBR3": ["IRB BRASIL"], "NTCO3": ["NATURA COSMETICOS"],
    "BRKM5": ["BRASKEM SA"],
}

def gerar_termos(ticker, nome):
    termos = [nome, ticker]
    if ticker in MAPA_ARQUIVOS:
        termos.extend(MAPA_ARQUIVOS[ticker])
    return termos

def extrair_dre(conteudo):
    if not conteudo:
        return ""
    idx = conteudo.upper().find("DEMONSTRATIVO DE RESULTADO")
    if idx == -1:
        return ""
    return conteudo[idx:idx+4000]

def buscar_dados_empresa(service, ticker, nome):
    termos = gerar_termos(ticker, nome)
    
    conteudo_anual = buscar_arquivo_pasta(service, PASTA_ANUAIS, termos)
    bp = conteudo_anual[:6000] if conteudo_anual else ""
    dre = extrair_dre(conteudo_anual)
    bal_anual = bp + (f"\n\nDRE:\n{dre}" if dre else "")

    conteudo_trim = buscar_arquivo_pasta(service, PASTA_TRIM, termos)
    bal_trim = conteudo_trim[:3000] if conteudo_trim else ""
    dre_trim = extrair_dre(conteudo_trim)
    if dre_trim:
        bal_trim += f"\n\nDRE TRIMESTRAL:\n{dre_trim}"

    termos_fatos = [t + " fatos" for t in termos] + termos
    fatos = buscar_arquivo_pasta(service, PASTA_FATOS, termos_fatos)[:4000]

    ind = ""
    indicadores = carregar_indicadores(service)
    for linha in indicadores.split("\n"):
        if linha.strip().startswith(ticker.upper()):
            ind = linha.strip()
            break

    return bal_anual, bal_trim, fatos, ind

def detectar_intencao(pergunta, tickers_map):
    p = pergunta.lower()
    tickers = [t for t in tickers_map.keys() if t.lower() in p]
    if not tickers:
        for nome, ticker in sorted(NOMES.items(), key=lambda x: -len(x[0])):
            if nome in p and ticker in tickers_map:
                tickers.append(ticker)
    tickers = list(dict.fromkeys(tickers))
    segmento = None
    if not tickers:
        for kw, seg in sorted(SEGMENTOS.items(), key=lambda x: -len(x[0])):
            if kw in p:
                segmento = seg
                break
    return tickers, segmento

def chamar_deepseek(prompt):
    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=8000
    )
    return r.choices[0].message.content

# ============================================
# INTERFACE PRINCIPAL
# ============================================
def app_principal():
    st.set_page_config(
        page_title="Analista B3",
        page_icon="📊",
        layout="wide"
    )

    # Header
    col1, col2 = st.columns([4, 1])
    with col1:
        st.title("📊 Analista de Investimentos B3")
        st.caption(f"DeepSeek AI | Dados: Google Drive | Usuário: {st.session_state['usuario']}")
    with col2:
        if st.button("Sair", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # Conecta ao Drive
    try:
        service = conectar_drive()
        tickers_map = carregar_tickers_json(service)
        st.success(f"✅ Drive conectado | {len(tickers_map)} empresas")
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao Drive: {e}")
        return

    # Histórico de mensagens
    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    # Exibe histórico
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input
    pergunta = st.chat_input("Digite sua pergunta... (ex: Analisa a Petrobras, Setor bancário, Top 10)")

    if pergunta:
        # Exibe pergunta do usuário
        st.session_state.mensagens.append({"role": "user", "content": pergunta})
        with st.chat_message("user"):
            st.markdown(pergunta)

        # Processa resposta
        with st.chat_message("assistant"):
            with st.spinner("Buscando dados e analisando..."):
                try:
                    p = pergunta.lower()
                    tickers, segmento = detectar_intencao(pergunta, tickers_map)

                    if tickers:
                        ctx = ""
                        for ticker in tickers[:3]:
                            info = tickers_map.get(ticker, {"nome": ticker, "segmento": ""})
                            bal, trim, fatos, ind = buscar_dados_empresa(service, ticker, info["nome"])
                            ctx += f"\n{'='*50}\nTICKER: {ticker} | {info['nome']} | {info['segmento']}\n"
                            if bal:   ctx += f"\nBALANÇO:\n{bal}\n"
                            if trim:  ctx += f"\nTRIMESTRAL:\n{trim}\n"
                            if fatos: ctx += f"\nFATOS:\n{fatos}\n"
                            if ind:   ctx += f"\nINDICADORES: {ind}\n"
                            if not any([bal, trim, fatos]):
                                ctx += f"⚠️ Sem arquivos encontrados para {ticker}\n"

                        prompt = f"PERGUNTA: {pergunta}\n\nDADOS:\n{ctx}\n\nUse APENAS os dados acima."
                        resposta = chamar_deepseek(prompt)

                    elif segmento:
                        empresas = [(t, i["nome"], i["segmento"]) for t, i in tickers_map.items()
                                   if segmento.lower() in i.get("segmento", "").lower()]
                        if not empresas:
                            resposta = f"❌ Nenhuma empresa encontrada no segmento '{segmento}'."
                        else:
                            ctx = f"SEGMENTO: {segmento} | {len(empresas)} empresas\n\n"
                            for ticker, nome, seg in empresas[:5]:
                                bal, _, fatos, ind = buscar_dados_empresa(service, ticker, nome)
                                ctx += f"\n{ticker} | {nome}\n"
                                if bal: ctx += f"BALANÇO:\n{bal[:2000]}\n"
                                if ind: ctx += f"INDICADORES: {ind}\n"
                            prompt = f"PERGUNTA: {pergunta}\n\nDADOS:\n{ctx}\n\nCompare e ranqueie."
                            resposta = chamar_deepseek(prompt)

                    elif any(k in p for k in ["top 10", "melhores", "ranking"]):
                        indicadores = carregar_indicadores(service)
                        prompt = f"PERGUNTA: {pergunta}\n\nINDICADORES:\n{indicadores[:5000]}\n\nMonte um TOP 10."
                        resposta = chamar_deepseek(prompt)

                    elif any(k in p for k in ["fato", "notícia", "semana", "recente"]):
                        arquivos_fatos = listar_arquivos(service, PASTA_FATOS)
                        ctx = ""
                        for nome, fid in list(arquivos_fatos.items())[:10]:
                            conteudo = ler_arquivo_drive(service, fid)
                            ctx += f"\n--- {nome} ---\n{conteudo[:500]}\n"
                        prompt = f"PERGUNTA: {pergunta}\n\nFATOS:\n{ctx}\n\nListe por data."
                        resposta = chamar_deepseek(prompt)

                    else:
                        resposta = ("❌ Não identifiquei empresa ou setor.\n\n"
                                   "💡 Exemplos:\n"
                                   "• Analisa a Petrobras\n"
                                   "• Compara Vale e Gerdau\n"
                                   "• Setor bancário\n"
                                   "• Top 10 melhores empresas")

                    st.markdown(resposta)
                    st.session_state.mensagens.append({"role": "assistant", "content": resposta})

                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")

# ============================================
# MAIN
# ============================================
if "logado" not in st.session_state:
    tela_login()
else:
    app_principal()
