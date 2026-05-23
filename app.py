import streamlit as st
import pytesseract
import re
from PIL import Image
import cv2
import numpy as np
from pdf2image import convert_from_bytes
from pyzbar.pyzbar import decode

pytesseract.pytesseract.tesseract_cmd = 'tesseract'

st.set_page_config(page_title="Scanner de Nota Fiscal", page_icon="📄", layout="wide")
st.title("📄 Nota Fiscal Key Scanner (NF-e / NFS-e)")
st.write("Envie o documento na esquerda. O sistema detecta chaves em qualquer página e corrige rotações automaticamente.")
st.divider()

if "forcar_ocr" not in st.session_state:
    st.session_state.forcar_ocr = False

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
# DETECÇÃO POR PYZBAR
# =========================================================================
def tentar_ler_codigos(imagem_np):
    """
    Tenta decodificar código de barras ou QR Code via PyZbar.
    Para cada imagem testa a versão original e rotacionada 180°,
    pois o PyZbar não lida bem com códigos de barras lineares invertidos.
    Também testa com binarização Otsu para imagens de baixo contraste.
    """
    if len(imagem_np.shape) == 3:
        cinza = cv2.cvtColor(imagem_np, cv2.COLOR_BGR2GRAY)
    else:
        cinza = imagem_np

    cinza_180 = cv2.rotate(cinza, cv2.ROTATE_180)
    binarizada = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    binarizada_180 = cv2.rotate(binarizada, cv2.ROTATE_180)

    tentativas = [cinza, cinza_180, binarizada, binarizada_180]

    for img in tentativas:
        for codigo in decode(img):
            texto = codigo.data.decode('utf-8')
            chave = validar_chave(texto)
            if chave:
                return chave
            m = re.search(r'chNFe=(\d{44,50})', texto)
            if m:
                return m.group(1)
    return None

# =========================================================================
# OCR TRADICIONAL
# =========================================================================
def extrair_chave_texto_ocr(imagem_np):
    try:
        if len(imagem_np.shape) == 3:
            imagem_cinza = cv2.cvtColor(imagem_np, cv2.COLOR_BGR2GRAY)
        else:
            imagem_cinza = imagem_np

        _, imagem_tratada = cv2.threshold(imagem_cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        texto = pytesseract.image_to_string(imagem_tratada, config='--psm 3')

        # Tentativa 1: sequência direta de 44/50 dígitos
        m = re.search(r'\b\d{44}\b|\b\d{50}\b', texto)
        if m:
            return m.group(0)

        # Tentativa 2: chave com espaços (grupos de 4)
        m = re.search(r'\b(\d{4}\s){10,12}\d{2,4}\b', texto)
        if m:
            return re.sub(r'\s', '', m.group(0))

        # Tentativa 3: linha com muitos dígitos misturados a separadores
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
    """
    Itera páginas × rotações. Retorna (chave, metodo_simples) ou (None, "").
    A mensagem de progresso é genérica — sem expor ângulos ao usuário.
    """
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
# LAYOUT
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

        if st.button("🔋 Ativar Câmera do Dispositivo", type="primary", width="stretch"):
            st.session_state.ligar_camera = True

        if st.session_state.ligar_camera:
            foto_camera = st.camera_input("Aponte a câmera para a nota")
            if foto_camera:
                imagem_exibicao_esquerda    = Image.open(foto_camera)
                paginas_pdf_processadas     = [imagem_exibicao_esquerda]
                st.session_state.forcar_ocr = False

    if imagem_exibicao_esquerda is not None:
        st.write("")
        st.image(imagem_exibicao_esquerda, caption="Documento carregado", width="stretch")

# =========================================================================
# COLUNA DIREITA — resultados
# =========================================================================
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
            st.success(f"🎉 Chave encontrada via **{metodo_usado}**!")

            if len(chave_encontrada) == 50:
                st.info("📝 **Tipo:** NFS-e (50 dígitos)")
            else:
                st.info("🏬 **Tipo:** NF-e (44 dígitos)")

            st.caption("📋 Copie a chave clicando no ícone ao passar o mouse sobre o campo:")
            st.code(chave_encontrada, language="text")

            if exibir_botao_contingencia:
                st.write("")
                if st.button("🔄 Falso Positivo? Identificar por Texto (OCR)", type="secondary", width="stretch"):
                    st.session_state.forcar_ocr = True
                    st.rerun()

            if st.session_state.forcar_ocr:
                st.write("")
                if st.button("🔙 Voltar para Detecção Automática", type="primary", width="stretch"):
                    st.session_state.forcar_ocr = False
                    st.rerun()

            st.divider()
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                st.link_button("Ir para a Receita Federal 🌐",
                    "https://www.nfe.fazenda.gov.br/portal/consultaRecouch.aspx?tipoConsulta=completa",
                    width="stretch")
            with sub_col2:
                st.link_button("Ir para o MeuDanfe 📄", "https://meudanfe.com.br", width="stretch")

            st.write("")
            st.text_input("Visualização auxiliar (texto):", value=chave_encontrada, key="chave_fiscal_reserva")

        else:
            st.error("⚠️ Nenhuma chave de 44 ou 50 dígitos foi localizada no documento.")
            if st.session_state.forcar_ocr:
                if st.button("🔙 Voltar para Detecção Automática", type="primary"):
                    st.session_state.forcar_ocr = False
                    st.rerun()
    else:
        st.info("Aguardando o envio de um documento para exibir os resultados nesta área.")
