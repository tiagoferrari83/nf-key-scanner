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
# Na nuvem do Streamlit, o Tesseract e o Poppler são instalados globalmente.
# Não precisamos apontar para caminhos do Windows (C:\...)
pytesseract.pytesseract.tesseract_cmd = 'tesseract'
# Para o pdf2image, na nuvem, basta remover o parâmetro poppler_path da função!

# Configuração da página em modo 'wide' para tela cheia
st.set_page_config(page_title="Scanner de Nota Fiscal", page_icon="📄", layout="wide")

st.title("📄 Scanner de Notas Fiscais com Contingência")
st.write("Envie o documento na esquerda. Você pode forçar o OCR de texto caso o código falhe.")
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
    DOCUMENTAÇÃO:
    Busca códigos de barras (1D) ou QR Codes (2D) na imagem.
    Retorna a string da chave se válida, ou None se não encontrar.
    """
    imagem_np = np.array(imagem_pil)
    codigos_detectados = decode(imagem_np)
    
    for codigo in codigos_detectados:
        conteudo_texto = codigo.data.decode('utf-8')
        apenas_numeros = re.sub(r'\D', '', conteudo_texto)
        
        if len(apenas_numeros) == 44:
            return apenas_numeros
            
        busca_chave_url = re.search(r'chNFe=(\d{44})', conteudo_texto)
        if busca_chave_url:
            return busca_chave_url.group(1)
            
    return None

# =========================================================================
# SEÇÃO: LÓGICA DE PROCESSAMENTO DE IMAGEM (OCR TRADICIONAL)
# =========================================================================
def extrair_chave_texto_ocr(imagem_pil):
    """
    DOCUMENTAÇÃO:
    Processa a imagem em escala de cinza e aplica o pytesseract para
    extrair a chave de 44 dígitos a partir do texto impresso.
    """
    imagem_np = np.array(imagem_pil)
    imagem_cinza = cv2.cvtColor(imagem_np, cv2.COLOR_RGB2GRAY)
    
    texto_extraido = pytesseract.image_to_string(imagem_cinza)
    
    padrao_direto = re.search(r'\b\d{44}\b', texto_extraido)
    if padrao_direto:
        return padrao_direto.group(0)
    
    padrao_espacado = re.search(r'\b(\d{4}\s){10}\d{4}\b', texto_extraido)
    if padrao_espacado:
        return re.sub(r'\s', '', padrao_espacado.group(0))
        
    texto_linhas = texto_extraido.replace('.', '').replace('-', '').replace('/', '')
    for linha in texto_linhas.split('\n'):
        linha_limpa = linha.replace(' ', '').strip()
        if len(linha_limpa) >= 44:
            achou = re.search(r'\d{44}', linha_limpa)
            if achou:
                return achou.group(0)
                
    return None

# =========================================================================
# SEÇÃO: CONFIGURAÇÃO DO LAYOUT LADO A LADO
# =========================================================================
col_esquerda, col_direita = st.columns(2)
imagem_final = None

# --- COLUNA DA ESQUERDA: ENTRADA DE DADOS ---
with col_esquerda:
    st.subheader("📥 Entrada do Documento")
    aba_upload, aba_camera = st.tabs(["📁 Enviar Arquivo (PDF ou Imagem)", "📸 Tirar Foto em Tempo Real"])
    
    with aba_upload:
        st.warning("⚠️ **Aviso:** Para PDFs, apenas a **primeira página** será reconhecida.")
        arquivo_upload = st.file_uploader("Selecione a nota fiscal eletrônica:", type=["png", "jpg", "jpeg", "pdf"])
        
        if arquivo_upload:
            if arquivo_upload.name.lower().endswith('.pdf'):
                with st.spinner("Processando PDF..."):
                    try:
                        paginas = convert_from_bytes(arquivo_upload.read(), dpi=300)
                        if paginas:
                            imagem_final = paginas[0]
                    except Exception as e:
                        st.error("Erro ao processar o arquivo PDF.")
                        st.exception(e)
            else:
                imagem_final = Image.open(arquivo_upload)
                
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
                imagem_final = Image.open(foto_camera)
                st.session_state.forcar_ocr = False
    
    if imagem_final is not None:
        st.write("") 
        st.image(imagem_final, caption="Documento carregado atualmente", width="stretch")

# --- COLUNA DA DIREITA: ORQUESTRADOR INTELIGENTE COM LAYOUT CLEAN ---
with col_direita:
    st.subheader("🔍 Resultados da Análise")
    
    if imagem_final is not None:
        chave_encontrada = None
        metodo_usado = ""
        exibir_botao_contingencia = False
        
        # Fluxo de Decisão do Motor
        if st.session_state.forcar_ocr:
            with st.spinner("Modo manual ativo. Ignorando códigos..."):
                chave_encontrada = extrair_chave_texto_ocr(imagem_final)
                if chave_encontrada:
                    metodo_usado = "Leitura de Texto (OCR) [Manual]"
        else:
            with st.spinner("Buscando Códigos de Barras ou QR Code..."):
                chave_encontrada = tentar_ler_codigos(imagem_final)
                if chave_encontrada:
                    metodo_usado = "Código de Barras / QR Code"
                    exibir_botao_contingencia = True
            
            if not chave_encontrada:
                with st.spinner("Iniciando OCR de texto automaticamente..."):
                    chave_encontrada = extrair_chave_texto_ocr(imagem_final)
                    if chave_encontrada:
                        metodo_usado = "Leitura de Texto (OCR) [Automático]"

        # EXIBIÇÃO CLEAN DOS RESULTADOS
        if chave_encontrada:
            # Mensagem de sucesso e método na mesma linha/bloco
            st.success(f"🎉 Chave de Acesso encontrada via **{metodo_usado}**!")
            
            # INSERÇÃO COMPLEMENTAR: Mensagem instrutiva antes de exibir a chave
            st.caption("📋 Copie a chave clicando no ícone que aparece ao passar o mouse sobre o campo abaixo:")
            
            # Exibe o código capturado
            st.code(chave_encontrada, language="text")
            
            # Botão de contingência unificado (Pergunta + Ação na mesma linha)
            if exibir_botao_contingencia:
                st.write("") 
                if st.button("🔄 Falso Positivo? Ignorar Código e Identificar por Texto (OCR)", type="secondary", width="stretch"):
                    st.session_state.forcar_ocr = True
                    st.rerun()
            
            # Se estiver no modo forçado, exibe botão para retornar ao fluxo normal
            if st.session_state.forcar_ocr:
                st.write("")
                if st.button("🔙 Voltar para Detecção Automática (Códigos)", type="primary", width="stretch"):
                    st.session_state.forcar_ocr = False
                    st.rerun()

            st.divider() # Linha divisória fina para separar os botões de ação externa
            
            # Botões de links externos alinhados lado a lado
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
            st.error("⚠️ Não conseguimos identificar a chave de acesso neste documento.")
            if st.session_state.forcar_ocr:
                if st.button("🔙 Voltar para Detecção Automática", type="primary"):
                    st.session_state.forcar_ocr = False
                    st.rerun()
    else:
        st.info("Aguardando o envio de um documento para exibir os resultados nesta área.")