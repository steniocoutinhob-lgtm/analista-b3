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
PASTA_NAO_RESP = "155EbX7uNLtjcYIDhElHAgnKCJRZXUTkH"

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

def salvar_pergunta_nao_respondida(service, pergunta):
    """Salva perguntas não respondidas no Drive"""
    from datetime import datetime
    try:
        hoje = datetime.now().strftime("%Y-%m-%d")
        nome_arquivo = f"perguntas_{hoje}.txt"
        hora = datetime.now().strftime("%H:%M:%S")
        linha = f"[{hora}] {pergunta}\n"
        
        # Verifica se já existe arquivo de hoje
        arquivos = listar_arquivos(service, PASTA_NAO_RESP)
        if nome_arquivo in arquivos:
            # Adiciona ao arquivo existente
            conteudo = ler_arquivo_drive(service, arquivos[nome_arquivo])
            novo_conteudo = conteudo + linha
        else:
            novo_conteudo = linha
        
        service.files().create(
            body={"name": nome_arquivo, "parents": [PASTA_NAO_RESP]},
            media_body=__import__("googleapiclient.http", fromlist=["MediaInMemoryUpload"]).MediaInMemoryUpload(
                novo_conteudo.encode("utf-8"), mimetype="text/plain"
            )
        ).execute()
    except Exception as e:
        pass  # Não interrompe o fluxo se falhar

def buscar_preco(ticker, indicadores):
    """Busca preço de um ticker no arquivo de indicadores"""
    for linha in indicadores.split("\n"):
        if linha.strip().startswith(ticker.upper() + " "):
            partes = linha.strip().split()
            if len(partes) >= 2:
                preco = partes[1].replace("R$", "").strip()
                return preco
    return None

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
    "3r petroleum": "BRAV3",
    "3tentos": "TTEN3",
    "abc brasil": "ABCB4",
    "aliansce sonae": "ALOS3",
    "alpargatas": "ALPA4",
    "alupar": "ALUP11",
    "amazonia": "BAZA3",
    "amazônia": "BAZA3",
    "ambev": "ABEV3",
    "americanas": "AMER3",
    "anima educacao": "ANIM3",
    "anima educação": "ANIM3",
    "assai": "ASAI3",
    "assaí": "ASAI3",
    "aura minerals": "AURA33",
    "azul": "AZUL4",
    "azzas": "AZZA3",
    "banco abc brasil": "ABCB4",
    "banco amazonia": "BAZA3",
    "banco bmg": "BMGB4",
    "banco do brasil": "BBAS3",
    "banrisul": "BRSR6",
    "bb seguridade": "BBSE3",
    "bemobi": "BMOB3",
    "blau farmaceutica": "BLAU3",
    "blau farmacêutica": "BLAU3",
    "bmg": "BMGB4",
    "boa safra": "SOJA3",
    "bradesco": "BBDC4",
    "bradespar": "BRAP4",
    "brasil agro": "AGRO3",
    "brasilagro": "AGRO3",
    "braskem": "BRKM5",
    "btg pactual": "BPAC11",
    "btg": "BPAC11",
    "c&a": "CEAB3",
    "caixa seguridade": "CXSE3",
    "camil": "CAML3",
    "casas bahia": "BHIA3",
    "cba": "CBAV3",
    "cemig": "CMIG4",
    "cogna": "COGN3",
    "comgas": "CGAS5",
    "comgás": "CGAS5",
    "copasa": "CSMG3",
    "copel": "CPLE6",
    "cosan": "CSAN3",
    "cpfl": "CPFE3",
    "cruzeiro do sul": "CSED3",
    "csn": "CSNA3",
    "csn mineracao": "CMIN3",
    "csn mineração": "CMIN3",
    "cury": "CURY3",
    "cyrela": "CYRE3",
    "dasa": "DASA3",
    "desktop": "DESK3",
    "dexco": "DXCO3",
    "direcional": "DIRR3",
    "ecorodovias": "ECOR3",
    "eletrobras": "ELET3",
    "eletrobrás": "ELET3",
    "embraer": "EMBJ3",
    "energisa": "ENGI11",
    "eneva": "ENEV3",
    "engie": "EGIE3",
    "equatorial energia": "EQTL3",
    "equatorial": "EQTL3",
    "eucatex": "EUCA4",
    "even": "EVEN3",
    "ez tec": "EZTC3",
    "eztec": "EZTC3",
    "fleury": "FLRY3",
    "fras-le": "FRAS3",
    "frasle": "FRAS3",
    "gerdau": "GGBR4",
    "grendene": "GRND3",
    "grupo mateus": "GMAT3",
    "grupo vamos": "VAMO3",
    "hapvida": "HAPV3",
    "hidrovias do brasil": "HBSA3",
    "hypera": "HYPE3",
    "iguatemi": "IGTI11",
    "intelbras": "INTB3",
    "irani": "RANI3",
    "irb": "IRBR3",
    "isa energia": "ISAE3",
    "itau unibanco": "ITUB4",
    "itausa": "ITSA4",
    "itaú unibanco": "ITUB4",
    "itaúsa": "ITSA4",
    "itau": "ITUB4",
    "itaú": "ITUB4",
    "jalles machado": "JALL3",
    "jhsf": "JHSF3",
    "jsl": "JSLG3",
    "kepler weber": "KEPL3",
    "klabin": "KLBN11",
    "localiza": "RENT3",
    "locaweb": "LWSA3",
    "lojas renner": "LREN3",
    "renner": "LREN3",
    "m. dias branco": "MDIA3",
    "m dias branco": "MDIA3",
    "magazine luiza": "MGLU3",
    "magalu": "MGLU3",
    "mahle metal leve": "LEVE3",
    "marcopolo": "POMO4",
    "marfrig": "MRFG3",
    "mater dei": "MATD3",
    "mateus": "GMAT3",
    "minerva foods": "BEEF3",
    "minerva": "BEEF3",
    "motiva": "MOTV3",
    "movida": "MOVI3",
    "mrv": "MRVE3",
    "multilaser": "MLAS3",
    "multiplan": "MULT3",
    "natura": "NTCO3",
    "neoenergia": "NEOE3",
    "odontoprev": "ODPV3",
    "oncoclinicas": "ONCO3",
    "oncoclínicas": "ONCO3",
    "orizon": "ORVR3",
    "pague menos": "PGMN3",
    "panvel": "PNVL3",
    "pao de acucar": "PCAR3",
    "pão de açúcar": "PCAR3",
    "petro rio": "PRIO3",
    "prio": "PRIO3",
    "petrobras": "PETR4",
    "petrobrás": "PETR4",
    "petroreconcavo": "RECV3",
    "petz": "AUAU3",
    "porto seguro": "PSSA3",
    "raia drogasil": "RADL3",
    "raia": "RADL3",
    "raizen": "RAIZ4",
    "raízen": "RAIZ4",
    "rede dor": "RDOR3",
    "rumo": "RAIL3",
    "sabesp": "SBSP3",
    "sanepar": "SAPR11",
    "santander": "SANB11",
    "sao carlos": "SCAR3",
    "são carlos": "SCAR3",
    "sao martinho": "SMTO3",
    "são martinho": "SMTO3",
    "ser educacional": "SEER3",
    "simpar": "SIMH3",
    "slc agricola": "SLCE3",
    "slc agrícola": "SLCE3",
    "slc": "SLCE3",
    "smartfit": "SMFT3",
    "suzano": "SUZB3",
    "taesa": "TAEE11",
    "tegma": "TGMA3",
    "telefonica": "VIVT3",
    "telefônica": "VIVT3",
    "tim brasil": "TIMS3",
    "tim": "TIMS3",
    "totvs": "TOTS3",
    "tupy": "TUPY3",
    "ultrapar": "UGPA3",
    "unipar": "UNIP6",
    "usiminas": "USIM5",
    "vale": "VALE3",
    "vamos": "VAMO3",
    "vibra energia": "VBBR3",
    "vibra": "VBBR3",
    "vivara": "VIVA3",
    "vulcabras": "VULC3",
    "weg": "WEGE3",
    "wiz": "WIZC3",
    "wiz solucoes": "WIZC3",
    "wiz soluções": "WIZC3",
    "yduqs": "YDUQ3",
    "3r": "BRAV3",
    "assai": "ASAI3",
    "cogna": "COGN3",
    "b3": "B3SA3",
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

def chamar_deepseek(prompt, usar_web=False):
    system = SYSTEM_PROMPT
    if usar_web:
        system += """

MODO WEB SEARCH ATIVO:
Para perguntas sobre cotações atuais, notícias, maiores altas/baixas,
resultados recentes ou macroeconomia, use seu conhecimento atualizado
e responda de forma completa em português brasileiro."""

    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
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
                    # Detecta perguntas sobre PREÇO SIMPLES
                    p_lower_check = pergunta.lower()
                    keywords_preco = ["qual o valor", "qual é o valor", "quanto vale", "qual o preço",
                                     "qual é o preço", "quanto custa", "cotação", "cotacao",
                                     "preço atual", "preco atual", "valor atual", "valor da ação",
                                     "valor da acao", "preço da ação", "preco da acao"]
                    keywords_historico = ["histórico de preço", "historico de preco", "variação do preço",
                                         "variacao do preco", "histórico de cotação", "historico de cotacao",
                                         "evolução do preço", "evolucao do preco", "variação de preço",
                                         "como variou", "como foi o preço", "historico de valor"]

                    eh_preco_simples = any(k in p_lower_check for k in keywords_preco)
                    eh_historico_preco = any(k in p_lower_check for k in keywords_historico)

                    tickers, segmento = detectar_intencao(pergunta, tickers_map)

                    if tickers and eh_preco_simples and not eh_historico_preco:
                        # Resposta rápida — só o preço
                        indicadores = carregar_indicadores(service)
                        ctx_preco = ""
                        for ticker in tickers[:3]:
                            for linha in indicadores.split("\n"):
                                if linha.strip().startswith(ticker.upper() + " ") or linha.strip().startswith(ticker.upper() + "	"):
                                    ctx_preco += f"{linha.strip()}\n"
                                    break
                        if ctx_preco:
                            prompt = f"""PERGUNTA: {pergunta}

INDICADORES:
{ctx_preco}

INSTRUÇÃO: O usuário quer APENAS o preço atual da ação.
Responda de forma CURTA e DIRETA: informe o ticker, nome e preço atual.
NÃO faça análise completa. Exemplo:
"PETR4 (Petrobras): R$ 44,60"
Se houver mais de uma ação, liste cada uma em uma linha."""
                            resposta = chamar_deepseek(prompt)
                        else:
                            resposta = "❌ Preço não encontrado nos dados locais."

                    elif tickers and eh_historico_preco:
                        # Histórico de variação de preço
                        indicadores = carregar_indicadores(service)
                        ctx_hist = ""
                        for ticker in tickers[:3]:
                            for linha in indicadores.split("\n"):
                                if linha.strip().startswith(ticker.upper() + " ") or linha.strip().startswith(ticker.upper() + "	"):
                                    ctx_hist += f"{linha.strip()}\n"
                                    break
                        prompt = f"""PERGUNTA: {pergunta}

INDICADORES DISPONÍVEIS:
{ctx_hist}

INSTRUÇÃO: O usuário quer o HISTÓRICO DE VARIAÇÃO DE PREÇO.
Foque APENAS em preço, variação percentual e tendência.
NÃO faça análise fundamentalista completa.
Apresente de forma clara e objetiva."""
                        resposta = chamar_deepseek(prompt)

                    elif tickers:
                        ctx = ""
                        for ticker in tickers[:3]:
                            info = tickers_map.get(ticker, {"nome": ticker, "segmento": ""})
                            bal, trim, fatos, ind = buscar_dados_empresa(service, ticker, info["nome"])
                            ctx += f"\n{'='*50}\nTICKER: {ticker} | {info['nome']} | {info['segmento']}\n"
                            if ind:   ctx += f"\nINDICADORES DE MERCADO (inclui preço atual, P/L, P/VP, DY, valor de mercado):\n{ind}\n"
                            if bal:   ctx += f"\nBALANÇO ANUAL:\n{bal}\n"
                            if trim:  ctx += f"\nBALANÇO TRIMESTRAL:\n{trim}\n"
                            if fatos: ctx += f"\nFATOS RELEVANTES:\n{fatos}\n"
                            if not any([bal, trim, fatos, ind]):
                                ctx += f"⚠️ Sem arquivos encontrados para {ticker}\n"

                        prompt = f"""PERGUNTA: {pergunta}

DADOS DOS ARQUIVOS:
{ctx}

INSTRUÇÃO IMPORTANTE:
- Use APENAS os dados acima
- Os dados trimestrais (ITR) contêm os resultados mais recentes (1T26, 2T26 etc)
- Sempre mencione o período mais recente disponível nos dados trimestrais
- Compare com os dados anuais para mostrar a evolução
- Se houver dados do 1T26 ou trimestre recente, destaque-os na análise"""
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
                        # Salva pergunta para análise posterior
                        try:
                            salvar_pergunta_nao_respondida(service, pergunta)
                        except:
                            pass
                        # Pergunta geral — usa web search do DeepSeek
                        indicadores = carregar_indicadores(service)
                        ctx_ind = indicadores[:3000] if indicadores else ""
                        prompt = f"""PERGUNTA DO USUÁRIO: {pergunta}

CONTEXTO DOS DADOS LOCAIS (use se relevante):
{ctx_ind}

INSTRUÇÃO:
Responda a pergunta usando seu conhecimento atualizado sobre o mercado financeiro brasileiro.
Se a pergunta for sobre cotações, altas, baixas, notícias ou eventos recentes, use seu conhecimento.
Se os dados acima forem relevantes, use-os também.
Responda em português brasileiro de forma completa e útil."""
                        resposta = chamar_deepseek(prompt, usar_web=True)

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
