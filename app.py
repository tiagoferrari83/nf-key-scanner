import streamlit as st
import pytesseract
import re
from PIL import Image
import cv2
import numpy as np
from pdf2image import convert_from_bytes
from pyzbar.pyzbar import decode

# =========================================================================
# CONFIGURAÇÕES DE CAMINHOS DO SISTEMA (COMPATÍVEL COM LINUX/NUVEM)
# =========================================================================
pytesseract.pytesseract.tesseract_cmd = 'tesseract'

# Configuração da página em modo 'wide'
st.set_page_config(page_title="Scanner de Nota Fiscal", page_icon="📄", layout="wide")

st.title("📄 Nota Fiscal Key Scanner (NF-e / NFS-e) - VS Code AMBIENTE DE DESENVOLVIMENTO")
st.write("Envie o documento na esquerda. O sistema detecta chaves em qualquer página e corrige rotações automaticamente.")
st.divider()

# =========================================================================
# SEÇÃO: INICIALIZAÇÃO DE ESTADOS (SESSION STATE)
# =========================================================================
if "forcar_ocr" not in st.session_state:
    st.session_state.forcar_ocr = False

# =========================================================================
# SEÇÃO: LÓGICA DE DETECÇÃO DE CÓDIGOS (BARRAS / QR)
# =========================================================================
def tentar_ler_codigos(imagem_np):
    """
    Busca códigos de barras ou QR Codes em uma matriz OpenCV (NumPy).
    """
    codigos_detectados = decode(imagem_np)
    
    for codigo in codigos_detectados:
        conteudo_texto = codigo.data.decode('utf-8')
        apenas_numeros = re.sub(r'\D', '', conteudo_texto)
        
        if len(apenas_numeros) in [44, 50]:
            return apenas_numeros
            
        busca_chave_url = re.search(r'chNFe=(\d{44,50})', conteudo_texto)
        if busca_chave_url:
            return busca_chave_url.group(1)
            
    return None

# =========================================================================
# SEÇÃO: LÓGICA DE PROCESSAMENTO DE IMAGEM (OCR TRADICIONAL OTIMIZADO)
# =========================================================================
def extrair_chave_texto_ocr(imagem_np):
    """
    Processa a matriz OpenCV aplicando filtros e executando o OCR do Tesseract.
    """
    imagem_cinza = cv2.cvtColor(imagem_np, cv2.COLOR_RGB2GRAY)
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
                
    return None

# =========================================================================
# SEÇÃO: CONFIGURAÇÃO DO LAYOUT LADO A LADO
# =========================================================================
col_esquerda, col_direita = st.columns(2)

paginas_pdf_processadas = []
imagem_exibicao_esquerda = None

# --- COLUNA DA ESQUERDA: ENTRADA DE DADOS ---
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
                paginas_pdf_processadas = [imagem_exibicao_esquerda]
                
            if 'nome_antigo' not in st.session_state or st.session_state.nome_antigo != arquivo_upload.name:
                st.session_state.nome_antigo = arquivo_upload.name
                st.session_state.forcar_ocr = False

    with aba_camera:
        st.info("💡 Clique no botão abaixo para liberar o acesso à câmera.")
        if "ligar_camera" not in st.session_state:
            st.session_state.ligar_camera = False

        if st.button("🔋 Ativar Câmera do Dispositivo", type="primary"):
            st.session_state.ligar_camera = True

        if st.session_state.ligar_camera:
            foto_camera = st.camera_input("Aponte a câmera para a nota")
            if foto_camera:
                imagem_exibicao_esquerda = Image.open(foto_camera)
                paginas_pdf_processadas = [imagem_exibicao_esquerda]
                st.session_state.forcar_ocr = False
    
    if imagem_exibicao_esquerda is not None:
        st.write("") 
        st.image(imagem_exibicao_esquerda, caption="Documento carregado (Visualização Original)", width="stretch")

# --- COLUNA DA DIREITA: ORQUESTRADOR MULTI-PÁGINAS E MULTI-ANGULOS ---
with col_direita:
    st.subheader("🔍 Resultados da Análise")
    
    if paginas_pdf_processadas:
        chave_encontrada = None
        metodo_usado = ""
        exibir_botao_contingencia = False
        
        total_paginas = len(paginas_pdf_processadas)
        progresso_texto = st.empty()
        
        # Definição dos 4 ângulos de rotação do OpenCV
        rotacoes_opencv = [
            {"codigo_cv": None},
            {"codigo_cv": cv2.ROTATE_90_CLOCKWISE},
            {"codigo_cv": cv2.ROTATE_180},
            {"codigo_cv": cv2.ROTATE_90_COUNTERCLOCKWISE}
        ]
        
        # =========================================================================
        # FLUXO 1: SE O USUÁRIO FORÇOU OCR MANUALMENTE
        # =========================================================================
        if st.session_state.forcar_ocr:
            for indice, img_pagina in enumerate(paginas_pdf_processadas):
                num_pagina_atual = indice + 1
                matriz_original = np.array(img_pagina)
                
                for rotacao in rotacoes_opencv:
                    if total_paginas > 1:
                        progresso_texto.info(f"Aplicando OCR: Pág. {num_pagina_atual} de {total_paginas}...")
                    else:
                        progresso_texto.info(f"Aplicando OCR no documento...")
                        
                    if rotacao["codigo_cv"] is not None:
                        matriz_analise = cv2.rotate(matriz_original, rotacao["codigo_cv"])
                    else:
                        matriz_analise = matriz_original.copy()
                        
                    chave_encontrada = extrair_chave_texto_ocr(matriz_analise)
                    if chave_encontrada:
                        metodo_usado = f"Leitura de Texto (OCR) [Manual] na Pág. {num_pagina_atual}"
                        break
                if chave_encontrada:
                    break
                    
        # =========================================================================
        # FLUXO 2: MODO AUTOMÁTICO INTELIGENTE (CÓDIGO PRIMEIRO -> DEPOIS OCR)
        # =========================================================================
        else:
            # --- PASSO A: Tentar Código de Barras / QR Code em todas as páginas e ângulos ---
            for indice, img_pagina in enumerate(paginas_pdf_processadas):
                num_pagina_atual = indice + 1
                matriz_original = np.array(img_pagina)
                
                for r_idx, rotacao in enumerate(rotacoes_opencv):
                    if total_paginas > 1:
                        progresso_texto.info(f"Buscando Códigos: Pág. {num_pagina_atual} de {total_paginas}...")
                    else:
                        progresso_texto.info(f"Buscando Códigos de barras/QR...")
                        
                    if {rotacao["codigo_cv"]} is not None:
                        matriz_analise = cv2.rotate(matriz_original, rotacao["codigo_cv"])
                    else:
                        matriz_analise = matriz_original.copy()
                        
                    chave_encontrada = tentar_ler_codigos(matriz_analise)
                    if chave_encontrada:
                        metodo_usado = f"Código de Barras / QR Code na Pág. {num_pagina_atual}"
                        exibir_botao_contingencia = True  # Garante que o botão de Falso Positivo apareça!
                        break
                if chave_encontrada:
                    break
            
            # --- PASSO B: Se não achou nenhum código, tenta OCR em todas as páginas e ângulos ---
            if not chave_encontrada:
                for indice, img_pagina in enumerate(paginas_pdf_processadas):
                    num_pagina_atual = indice + 1
                    matriz_original = np.array(img_pagina)
                    
                    for rotacao in rotacoes_opencv:
                        if total_paginas > 1:
                            progresso_texto.info(f"Buscando via OCR: Pág. {num_pagina_atual} de {total_paginas}...")
                        else:
                            progresso_texto.info(f"Buscando via OCR (Linha por linha)...")
                            
                        if rotacao["codigo_cv"] is not None:
                            matriz_analise = cv2.rotate(matriz_original, rotacao["codigo_cv"])
                        else:
                            matriz_analise = matriz_original.copy()
                            
                        chave_encontrada = extrair_chave_texto_ocr(matriz_analise)
                        if chave_encontrada:
                            metodo_usado = f"Leitura de Texto (OCR) [Automático] na Pág. {num_pagina_atual}"
                            break
                    if chave_encontrada:
                        break
                        
        progresso_texto.empty()

        # --- EXIBIÇÃO CLEAN DOS RESULTADOS ---
        if chave_encontrada:
            st.success(f"🎉 Chave de Acesso encontrada via **{metodo_usado}**!")
            
            if len(chave_encontrada) == 50:
                st.info("📝 **Tipo Identificado:** Documento classificado como **NFS-e** (50 dígitos).")
            else:
                st.info("🏬 **Tipo Identificado:** Documento classificado como **NF-e** (44 dígitos).")
            
            st.caption("📋 Copie a chave clicando no ícone que aparece ao passar o mouse sobre o campo abaixo:")
            st.code(chave_encontrada, language="text")
            
            # O botão de contingência agora respeitará a variável perfeitamente, mesmo com rotação
            if exibir_botao_contingencia:
                st.write("") 
                if st.button("🔄 Falso Positivo? Ignorar Código e Identificar por Texto (OCR)", type="secondary", width="stretch"):
                    st.session_state.forcar_ocr = True
                    st.rerun()
            
            if st.session_state.forcar_ocr:
                st.write("")
                if st.button("🔙 Voltar para Detecção Automática (Códigos)", type="primary", width="stretch"):
                    st.session_state.forcar_ocr = False
                    st.rerun()

            st.divider()
            
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                url_receita = "https://www.nfe.fazenda.gov.br/portal/consultaRecouch.aspx?tipoConsulta=completa"
                st.link_button("Ir para a Receita Federal 🌐", url_receita, width="stretch")
            with sub_col2:
                url_meudanfe = "https://meudanfe.com.br"
                st.link_button("Ir para o MeuDanfe 📄", url_meudanfe, width="stretch")
                
            st.write("")
            st.text_input("Visualização auxiliar (texto):", value=chave_encontrada, key="chave_fiscal_reserva")
        else:
            st.error(f"⚠️ Nenhuma chave de 44 ou 50 dígitos foi localizada no documento.")
            if st.session_state.forcar_ocr:
                if st.button("🔙 Voltar para Detecção Automática", type="primary"):
                    st.session_state.forcar_ocr = False
                    st.rerun()
    else:
        st.info("Aguardando o envio de um documento para exibir os resultados nesta área.")
