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

# =========================================================================
# ROTAÇÕES — lista usada em AMBOS os fluxos (códigos e OCR)
# =========================================================================
ROTACOES = [
    {"label": "0°",   "codigo_cv": None},
    {"label": "90°",  "codigo_cv": cv2.ROTATE_90_CLOCKWISE},
    {"label": "180°", "codigo_cv": cv2.ROTATE_180},
    {"label": "270°", "codigo_cv": cv2.ROTATE_90_COUNTERCLOCKWISE},
]

def rotacionar(matriz, codigo_cv):
    """Retorna a matriz rotacionada, ou a original se codigo_cv for None."""
    if codigo_cv is not None:
        return cv2.rotate(matriz, codigo_cv)
    return matriz.copy()

# =========================================================================
# DETECÇÃO DE CÓDIGO DE BARRAS / QR CODE
# Correção: pré-processa a imagem para melhorar detecção de código de barras
# linear (que NÃO é rotacionado automaticamente pelo PyZbar).
# =========================================================================
def tentar_ler_codigos(imagem_np):
    """
    Tenta decodificar código de barras ou QR Code.
    Aplica binarização para aumentar contraste antes de passar ao PyZbar,
    o que melhora significativamente a leitura de códigos lineares.
    """
    try:
        # Converte para cinza
        if len(imagem_np.shape) == 3:
            cinza = cv2.cvtColor(imagem_np, cv2.COLOR_BGR2GRAY)
        else:
            cinza = imagem_np

        # FIX: tenta com a imagem original E com binarização Otsu
        # O código de barras linear da NFe muitas vezes só é detectado
        # após binarização, especialmente em imagens escaneadas.
        tentativas = [cinza, cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]

        for img_tentativa in tentativas:
            codigos_detectados = decode(img_tentativa)
            for codigo in codigos_detectados:
                conteudo_texto = codigo.data.decode('utf-8')
                apenas_numeros = re.sub(r'\D', '', conteudo_texto)

                if len(apenas_numeros) in [44, 50]:
                    return apenas_numeros

                busca_chave_url = re.search(r'chNFe=(\d{44,50})', conteudo_texto)
                if busca_chave_url:
                    return busca_chave_url.group(1)
    except Exception:
        pass
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
        texto_extraido = pytesseract.image_to_string(imagem_tratada, config='--psm 3')

        padrao_direto = re.search(r'\b\d{44}\b|\b\d{50}\b', texto_extraido)
        if padrao_direto:
            return padrao_direto.group(0)

        padrao_espacado = re.search(r'\b(\d{4}\s){10,12}\d{2,4}\b', texto_extraido)
        if padrao_espacado:
            return re.sub(r'\s', '', padrao_espacado.group(0))

        texto_linhas = texto_extraido.replace('.', '').replace('-', '').replace('/', '')
        for linha in texto_linhas.split('\n'):
            linha_limpa = linha.replace(' ', '').strip()
            if len(linha_limpa) >= 44:
                achou = re.search(r'\d{50}|\d{44}', linha_limpa)
                if achou:
                    return achou.group(0)
    except Exception:
        pass
    return None

# =========================================================================
# ORQUESTRADOR CENTRAL — evita duplicação de lógica entre os dois fluxos
# =========================================================================
def buscar_chave_em_paginas(paginas, modo, progresso_widget):
    """
    Itera páginas × rotações aplicando 'modo' ('codigos' ou 'ocr').
    Retorna (chave_encontrada, metodo_usado) ou (None, "").

    FIX principal: o break interno saía apenas do loop de rotações.
    Agora usa flag 'achou' para também interromper o loop de páginas,
    garantindo que TODAS as rotações sejam tentadas antes de desistir.
    """
    total = len(paginas)
    for idx, img_pagina in enumerate(paginas):
        num = idx + 1
        matriz_original = cv2.cvtColor(np.array(img_pagina), cv2.COLOR_RGB2BGR)

        for r in ROTACOES:
            label_pag = f"Pág. {num}/{total}" if total > 1 else "documento"

            if modo == 'codigos':
                progresso_widget.info(f"🔍 Buscando código de barras/QR ({r['label']}) — {label_pag}...")
                matriz = rotacionar(matriz_original, r['codigo_cv'])
                chave  = tentar_ler_codigos(matriz)
                metodo = f"Código de Barras/QR ({r['label']}) — Pág. {num}"
            else:
                progresso_widget.info(f"🔤 OCR ({r['label']}) — {label_pag}...")
                matriz = rotacionar(matriz_original, r['codigo_cv'])
                chave  = extrair_chave_texto_ocr(matriz)
                metodo = f"OCR ({r['label']}) — Pág. {num}"

            if chave:
                return chave, metodo   # interrompe tudo imediatamente

    return None, ""

# =========================================================================
# LAYOUT
# =========================================================================
col_esquerda, col_direita = st.columns(2)
paginas_pdf_processadas = []
imagem_exibicao_esquerda = None

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
        st.image(imagem_exibicao_esquerda, caption="Documento carregado (Visualização Original)", use_container_width=True)

# =========================================================================
# COLUNA DIREITA — resultados
# =========================================================================
with col_direita:
    st.subheader("🔍 Resultados da Análise")

    if paginas_pdf_processadas:
        chave_encontrada        = None
        metodo_usado            = ""
        exibir_botao_contingencia = False
        progresso_texto         = st.empty()

        # ── FLUXO 1: forçar OCR manualmente ──────────────────────────────
        if st.session_state.forcar_ocr:
            chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                paginas_pdf_processadas, 'ocr', progresso_texto
            )

        # ── FLUXO 2: automático (códigos → OCR) ──────────────────────────
        else:
            # Etapa 1: código de barras / QR em todas as rotações
            chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                paginas_pdf_processadas, 'codigos', progresso_texto
            )

            if chave_encontrada:
                exibir_botao_contingencia = True
            else:
                # Etapa 2: OCR somente se nenhum código foi encontrado
                chave_encontrada, metodo_usado = buscar_chave_em_paginas(
                    paginas_pdf_processadas, 'ocr', progresso_texto
                )

        progresso_texto.empty()

        # ── Exibição dos resultados ───────────────────────────────────────
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
                if st.button("🔄 Falso Positivo? Identificar por Texto (OCR)", type="secondary", use_container_width=True):
                    st.session_state.forcar_ocr = True
                    st.rerun()

            if st.session_state.forcar_ocr:
                st.write("")
                if st.button("🔙 Voltar para Detecção Automática", type="primary", use_container_width=True):
                    st.session_state.forcar_ocr = False
                    st.rerun()

            st.divider()
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                st.link_button("Ir para a Receita Federal 🌐",
                    "https://www.nfe.fazenda.gov.br/portal/consultaRecouch.aspx?tipoConsulta=completa",
                    use_container_width=True)
            with sub_col2:
                st.link_button("Ir para o MeuDanfe 📄", "https://meudanfe.com.br", use_container_width=True)

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
