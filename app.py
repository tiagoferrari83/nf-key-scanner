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

st.title("📄 Scanner de Notas Fiscais Inteligente (NF-e / NFS-e)")
st.write("Envie o documento na esquerda. O sistema detecta automaticamente chaves de 44 ou 50 dígitos em qualquer página.")
st.divider()

# =========================================================================
# SEÇÃO: INICIALIZAÇÃO DE ESTADOS (SESSION STATE)
# =========================================================================
if "forcar_ocr" not in st.session_state:
    st.session_state.forcar_ocr = False

# =========================================================================
# SEÇÃO: LÓGICA DE DETECÇÃO DE CÓDIGOS (BARRAS / QR)
# =========================================================================
def tentar_ler_codigos(imagem_pil):
    """
    Busca códigos de barras ou QR Codes na imagem.
    Suporta chaves padrão de 44 dígitos (NF-e) e chaves de 50 dígitos (NFS-e).
    """
    imagem_np = np.array(imagem_pil)
    codigos_detectados = decode(imagem_np)
    
    for codigo in codigos_detectados:
        conteudo_texto = codigo.data.decode('utf-8')
        apenas_numeros = re.sub(r'\D', '', conteudo_texto)
        
        # Suporta dinamicamente 44 ou 50 dígitos puros
        if len(apenas_numeros) in [44, 50]:
            return apenas_numeros
            
        # Busca chave em URLs de QR Code (captura 44 ou 50 números após o parâmetro)
        busca_chave_url = re.search(r'chNFe=(\d{44,50})', conteudo_texto)
        if busca_chave_url:
            return busca_chave_url.group(1)
            
    return None

# =========================================================================
# SEÇÃO: LÓGICA DE PROCESSAMENTO DE IMAGEM (OCR TRADICIONAL)
# =========================================================================
def extrair_chave_texto_ocr(imagem_pil):
    """
    Processa a imagem via pytesseract buscando padrões de 44 ou 50 dígitos.
    """
    imagem_np = np.array(imagem_pil)
    imagem_cinza = cv2.cvtColor(imagem_np, cv2.COLOR_RGB2GRAY)
    
    texto_extraido = pytesseract.image_to_string(imagem_cinza)
    
    # Padrão 1: Procura por 44 ou 50 números grudados puramente
    padrao_direto = re.search(r'\b\d{44}\b|\b\d{50}\b', texto_extraido)
    if padrao_direto:
        return padrao_direto.group(0)
    
    # Padrão 2: Procura por formatos espaçados (ex: blocos de 4 dígitos)
    padrao_espacado = re.search(r'\b(\d{4}\s){10,12}\d{2,4}\b', texto_extraido)
    if padrao_espacado:
        return re.sub(r'\s', '', padrao_espacado.group(0))
        
    # Padrão 3: Varredura linha por linha limpando pontuações
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

# Criamos uma lista de tuplas para armazenar as páginas do PDF e visualizá-las
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
                with st.spinner("Lendo páginas do PDF..."):
                    try:
                        # Converte todas as páginas do PDF
                        paginas_pdf_processadas = convert_from_bytes(arquivo_upload.read(), dpi=200)
                        # Define a primeira página por padrão para aparecer na pré-visualização esquerda
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
        # Mostra o documento (ou a primeira página do PDF) na esquerda como feedback
        st.image(imagem_exibicao_esquerda, caption="Documento carregado (Primeira página exibida)", width="stretch")

# --- COLUNA DA DIREITA: ORQUESTRADOR MULTI-PÁGINAS INTELIGENTE ---
with col_direita:
    st.subheader("🔍 Resultados da Análise")
    
    if paginas_pdf_processadas:
        chave_encontrada = None
        metodo_usado = ""
        exibir_botao_contingencia = False
        pagina_alvo = 0
        
        # Cria uma barra de progresso caso o PDF tenha muitas páginas
        total_paginas = len(paginas_pdf_processadas)
        progresso_texto = st.empty()
        
        # --- EXECUÇÃO DO FLUXO MULTI-PÁGINAS ---
        for indice, img_pagina in enumerate(paginas_pdf_processadas):
            num_pagina_atual = indice + 1
            if total_paginas > 1:
                progresso_texto.info(f"Analisando página {num_pagina_atual} de {total_paginas}...")

            # Estratégia A: Se o usuário FORÇOU o OCR manualmente
            if st.session_state.forcar_ocr:
                chave_encontrada = extrair_chave_texto_ocr(img_pagina)
                if chave_encontrada:
                    metodo_usado = f"Leitura de Texto (OCR) [Manual] na Pág. {num_pagina_atual}"
                    pagina_alvo = indice
                    break
            else:
                # Estratégia B: Fluxo padrão automático (Procura código de barras/QR nesta página)
                chave_encontrada = tentar_ler_codigos(img_pagina)
                if chave_encontrada:
                    metodo_usado = f"Código de Barras / QR Code na Pág. {num_pagina_atual}"
                    exibir_botao_contingencia = True
                    pagina_alvo = indice
                    break
                
                # Se não achou código na página atual, tenta o OCR de texto nela mesma antes de ir para a próxima página
                chave_encontrada = extrair_chave_texto_ocr(img_pagina)
                if chave_encontrada:
                    metodo_usado = f"Leitura de Texto (OCR) [Automático] na Pág. {num_pagina_atual}"
                    pagina_alvo = indice
                    break
                    
        progresso_texto.empty() # Limpa o texto de progresso do laço

        # --- EXIBIÇÃO CLEAN DOS RESULTADOS ---
        if chave_encontrada:
            st.success(f"🎉 Chave de Acesso encontrada via **{metodo_usado}**!")
            
            # Se a chave tiver 50 dígitos, adiciona um selo visual informando que é NFS-e
            if len(chave_encontrada) == 50:
                st.info("📝 **Tipo Identificado:** Documento classificado como **NFS-e** (50 dígitos).")
            else:
                st.info("🏬 **Tipo Identificado:** Documento classificado como **NF-e** (44 dígitos).")
            
            st.caption("📋 Copie a chave clicando no ícone que aparece ao passar o mouse sobre o campo abaixo:")
            st.code(chave_encontrada, language="text")
            
            # Botão de contingência unificado
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
            
            # Botões de links dinâmicos adaptados
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
            st.error(f"⚠️ Nenhuma chave de 44 ou 50 dígitos foi localizada nas {total_paginas} páginas analisadas.")
            if st.session_state.forcar_ocr:
                if st.button("🔙 Voltar para Detecção Automática", type="primary"):
                    st.session_state.forcar_ocr = False
                    st.rerun()
    else:
        st.info("Aguardando o envio de um documento para exibir os resultados nesta área.")
