import streamlit as st
import pytesseract
import re
from PIL import Image
import cv2
import numpy as np
from pdf2image import convert_from_bytes
from pyzbar.pyzbar import decode
import pandas as pd
import io
from datetime import datetime

# Configuração de execução do executável do Tesseract
pytesseract.pytesseract.tesseract_cmd = 'tesseract'

# Configuração da página em modo 'wide'
st.set_page_config(page_title="Scanner de Nota Fiscal", page_icon="📄", layout="wide")
st.title("📄 Nota Fiscal Key Scanner (NF-e / NFS-e)")
st.write("Envie o documento na esquerda. O sistema detecta chaves em qualquer página e corrige rotações automaticamente.")
st.divider()

# =========================================================================
# SEÇÃO: INICIALIZAÇÃO DE ESTADOS DA SESSÃO (SESSION STATE)
# =========================================================================
if "forcar_ocr" not in st.session_state:
    st.session_state.forcar_ocr = False

if "historico_chaves" not in st.session_state:
    st.session_state.historico_chaves = []

# Lista estática de rotações suportadas pelo OpenCV
ROTACOES = [
    {"codigo_cv": None},
    {"codigo_cv": cv2.ROTATE_90_CLOCKWISE},
    {"codigo_cv": cv2.ROTATE_180},
    {"codigo_cv": cv2.ROTATE_90_COUNTERCLOCKWISE},
]

def rotacionar(matriz, codigo_cv):
    if codigo_cv is not None:
        return cv2.rotate(matriz, codigo_cv)
    return matriz.copy()

def validar_chave(texto):
    """Extrai 44 ou 50 dígitos consecutivos de uma string."""
    apenas_numeros = re.sub(r'\D', '', texto)
    m = re.search(r'\d{50}|\d{44}', apenas_numeros)
    return m.group(0) if m else None

# =========================================================================
# SEÇÃO: VALIDAÇÃO MATEMÁTICA (MÓDULO 11)
# =========================================================================
def validar_modulo11(chave):
    """
    Valida chaves de 44 ou 50 dígitos usando o algoritmo de Módulo 11.
    Retorna True se o dígito verificador (último número) for matematicamente válido.
    """
    if not chave or len(chave) not in [44, 50]:
        return False
        
    digitos_base = [int(d) for d in chave[:-1]]
    dv_informado = int(chave[-1])
    
    soma = 0
    peso = 2
    
    for d in reversed(digitos_base):
        soma += d * peso
        peso += 1
        if peso > 9:
            peso = 2
            
    resto = soma % 11
    
    if resto in [0, 1]:
        dv_calculado = 0
    else:
        dv_calculado = 11 - resto
        
    return dv_calculado == dv_informado

# =========================================================================
# DETECÇÃO POR PYZBAR
# =========================================================================
def tentar_ler_codigos(imagem_np):
    try:
        if len(imagem_np.shape) == 3:
            cinza = cv2.cvtColor(imagem_np, cv2.COLOR_BGR2GRAY)
        else:
            cinza = imagem_np

        cinza_180 = cv2.rotate(cinza, cv2.ROTATE_180)
        binarizada = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        binarizada_180 = cv2.rotate(binarizada, cv2.ROTATE_180)

        tentativas = [cinza, cinza_180, binarizada, binarizada_180]

        for img in tentatives:
            for codigo in decode(img):
                texto = codigo.data.decode('utf-8')
                chave = validar_chave(texto)
                if chave:
                    return chave
                m = re.search(r'chNFe=(\d{44,50})', texto)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None

# =========================================================================
# OCR TRADICIONAL VIA TESSERACT
# =========================================================================
def extrair_chave_texto_ocr(imagem_np):
    try:
        if len(imagem_np.shape) == 3:
            imagem_cinza = cv2.cvtColor(imagem_np, cv2.COLOR_BGR2GRAY)
        else:
            imagem_cinza = imagem_np

        _, imagem_tratada = cv2.threshold(imagem_cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        texto = pytesseract.image_to_string(imagem_tratada, config='--psm 3')

        m = re.search(r'\b\d{44}\b|\b\d{50}\b', texto)
        if m:
            return m.group(0)

        m = re.search(r'\b(\d{4}\s){10,12}\d{2,4}\b', texto)
        if m:
            return re.sub(r'\s', '', m.group(0))

        texto_limpo = texto.replace('.', '').replace('-', '').replace('/', '')
        for linha in texto_limpo.split('\n'):
            linha_limpa = linha.replace(' ', '').strip()
            if len(linha_limpa) >= 44:
                m = re.search(r'\d{50}|\d{44}', linha_limpa)
                if m:
                    return m.group(0)
    except Exception:
        pass
    return None

# =========================================================================
# ORQUESTRADOR CENTRAL
# =========================================================================
def buscar_chave_em_paginas(paginas, modo, progresso_widget):
    total = len(paginas)
    for idx, img_pagina in enumerate(paginas):
        matriz_original = cv2.cvtColor(np.array(img_pagina), cv2.COLOR_RGB2BGR)

        for r in ROTACOES:
            if total > 1:
                progresso_widget.info(f"⏳ Analisando documento (página {idx+1} de {total})...")
            else:
                progresso_widget.info("⏳ Analisando documento...")

            matriz = rotacionar(matriz_original, r['codigo_cv'])

            if modo == 'codigos':
                chave = tentar_ler_codigos(matriz)
                metodo = "Código de Barras / QR Code"
            else:
                chave = extrair_chave_texto_ocr(matriz)
                metodo = "Leitura de Texto (OCR)"

            if chave:
                return chave, metodo

    return None, ""

# =========================================================================
# LAYOUT DA INTERFACE (STREAMLIT)
# =========================================================================
col_esquerda, col_direita = st.columns(2)
paginas_pdf_processadas   = []
imagem_exibicao_esquerda  = None

with col_esquerda:
    st.subheader("📥 Entrada do Documento")
    aba_upload, aba_camera = st.tabs(["📁 Enviar Arquivo (PDF ou Imagem)", "📸 Tirar Foto em Tempo Real"])

    with aba_upload:
        arquivo_upload = st.file_uploader("Selecione a nota fiscal eletrônica:", type=["png", "jpg", "jpeg", "pdf"])

        if arquivo_upload:
            if arquivo_upload.name.lower().endswith('.pdf'):
                with st.spinner("Lendo páginas do PDF em alta resolução..."):
                    try:
                        paginas_pdf_processadas = convert_from_bytes(arquivo_upload.read(), dpi=300)
                        if paginas_pdf_processadas:
                            imagem_exibicao_esquerda = paginas_pdf_processadas[0]
                    except Exception as e:
                        st.error("Erro ao processar o arquivo PDF.")
                        st.exception(e)
            else:
                imagem_exibicao_esquerda = Image.open(arquivo_upload)
                paginas_pdf_processadas  = [imagem_exibicao_esquerda]

            if 'nome_antigo' not in st.session_state or st.session_state.nome_antigo != arquivo_upload.name:
                st.session_state.nome_antigo = arquivo_upload.name
                st.session_state.forcar_ocr  = False

    with aba_camera:
        st.info("💡 Clique no botão abaixo para liberar o acesso à câmera.")
        if "ligar_camera" not in st.session_state:
            st.session_state.ligar_camera = False

        if st.button("🔋 Ativar Câmera do Dispositivo", type="primary"):
            st.session_state.ligar_camera = True

        if st.session_state.ligar_camera:
            foto_camera = st.camera_input("Aponte a câmera para a nota")
            if foto_camera:
                imagem_exibicao_esquerda    = Image.open(foto_camera)
                paginas_pdf_processadas     = [imagem_exibicao_esquerda]
                st.session_state.forcar_ocr = False

    if imagem_exibicao_esquerda is not None:
        st.write("")
        st.image(imagem_exibicao_esquerda, caption="Documento carregado", width='content')

# --- COLUNA DIREITA: PROCESSAMENTO E EXIBIÇÃO DE RESULTADOS ---
with col_direita:
    st.subheader("🔍 Resultados da Análise")

    if paginas_pdf_processadas:
        chave_encontrada          = None
        metodo_usado              = ""
        exibir_botao_contingencia = False
        progresso_texto           = st.empty()

        if st.session_state.forcar_ocr:
            chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                paginas_pdf_processadas, 'ocr', progresso_texto
            )
        else:
            chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                paginas_pdf_processadas, 'codigos', progresso_texto
            )
            if chave_encontrada:
                exibir_botao_contingencia = True
            else:
                chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                    paginas_pdf_processadas, 'ocr', progresso_texto
                )

        progresso_texto.empty()

        if chave_encontrada:
            chave_valida_matematicamente = validar_modulo11(chave_encontrada)
            
            if chave_valida_matematicamente:
                st.success(f"🎉 Chave válida encontrada via **{metodo_usado}**!")
                status_historico = "Válida"
            else:
                st.warning(f"⚠️ Chave encontrada não validada (Falha no Módulo 11) via **{metodo_usado}**!")
                status_historico = "Inválida (Módulo 11)"

            tipo_doc = "NFS-e (50g)" if len(chave_encontrada) == 50 else "NF-e (44g)"
            
            # -----------------------------------------------------------------
            # REGISTRO NO HISTÓRICO (Evita duplicados consecutivos do mesmo arquivo)
            # -----------------------------------------------------------------
            registro_atual = {
                "Horário da Leitura": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "Chave de Acesso": str(chave_encontrada),
                "Tipo": tipo_doc,
                "Validação": status_historico,
                "Método de Captura": metodo_usado
            }
            
            # Só adiciona se o histórico estiver vazio ou se a última chave adicionada for diferente
            if not st.session_state.historico_chaves or st.session_state.historico_chaves[-1]["Chave de Acesso"] != chave_encontrada:
                st.session_state.historico_chaves.append(registro_atual)

            if len(chave_encontrada) == 50:
                st.info("📝 **Tipo:** Documento classificado como NFS-e.")
            else:
                st.info("🏬 **Tipo:** Documento classificado como NF-e.")

            st.caption("📋 Copie a chave clicando no ícone ao passar o mouse sobre o campo:")
            st.code(chave_encontrada, language="text")

            if exibir_botao_contingencia:
                st.write("")
                if st.button("🔄 Falso Positivo? Identificar por Texto (OCR)", type="secondary", width='content'):
                    st.session_state.forcar_ocr = True
                    st.rerun()

            if st.session_state.forcar_ocr:
                st.write("")
                if st.button("🔙 Voltar para Detecção Automática", type="primary", width='content'):
                    st.session_state.forcar_ocr = False
                    st.rerun()

            st.divider()
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                st.link_button("Ir para a Receita Federal 🌐",
                    "https://www.nfe.fazenda.gov.br/portal/consultaRecouch.aspx?tipoConsulta=completa",
                    width='content')
            with sub_col2:
                st.link_button("Ir para o MeuDanfe 📄", "https://meudanfe.com.br", width='content')

        else:
            st.error("⚠️ Nenhuma chave de 44 ou 50 dígitos foi localizada no documento.")
            if st.session_state.forcar_ocr:
                if st.button("🔙 Voltar para Detecção Automática", type="primary"):
                    st.session_state.forcar_ocr = False
                    st.rerun()
    else:
        st.info("Aguardando o envio de um documento para exibir os resultados nesta área.")

    # =========================================================================
    # SEÇÃO INTERATIVA: HISTÓRICO DE CONSULTAS & EXPORTAÇÃO EXCEL
    # =========================================================================
    st.write("")
    st.subheader("📋 Histórico de Consultas da Sessão")
    
    if st.session_state.historico_chaves:
        # Converte a lista de dicionários para um DataFrame do Pandas
        df_historico = pd.DataFrame(st.session_state.historico_chaves)
        
        # Inverte a ordem para que a leitura mais recente apareça no topo da tabela
        df_exibicao = df_historico.iloc[::-1]
        
        # Renderiza a tabela do histórico na interface
        st.dataframe(df_exibicao, width='stretch', hide_index=True)
        
        # Geração do arquivo Excel (.xlsx) em memória usando BytesIO
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df_historico.to_excel(writer, index=False, sheet_name='Chaves Escaneadas')
        dados_excel = output_excel.getvalue()
        
        # Botões de controle lado a lado (Download e Limpar)
        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn1:
            st.download_button(
                label="📥 Baixar Histórico em Excel (.xlsx)",
                data=dados_excel,
                file_name=f"historico_chaves_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        with col_btn2:
            if st.button("🗑️ Limpar Histórico", type="secondary"):
                st.session_state.historico_chaves = []
                st.rerun()
    else:
        st.caption("O histórico está vazio. Envie documentos válidos para popular a tabela.")
