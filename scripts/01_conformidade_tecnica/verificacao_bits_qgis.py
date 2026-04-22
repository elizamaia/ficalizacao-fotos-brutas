# -*- coding: utf-8 -*-

"""
MODELO DE SCRIPT PARA CAIXA DE FERRAMENTAS DO QGIS
Contexto: Projeto de Mestrado - Eliza Silva Maia (PPEC/UFBA)
Objetivo: Fiscalização de Profundidade de Bits (Customizável)
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFolderDestination,
                       QgsMessageLog)
import os
from PIL import Image
from PIL.TiffTags import TAGS
from datetime import datetime

class VerificarBitsAlgoritmo(QgsProcessingAlgorithm):
    """
    Algoritmo para verificar conformidade de profundidade de bits em imagens TIFF.
    Permite ao usuário definir o valor de referência para auditoria.
    """

    # Constantes dos Parâmetros
    PASTA_ENTRADA = 'PASTA_ENTRADA'
    BITS_REFERENCIA = 'BITS_REFERENCIA'
    ARQUIVO_RELATORIO = 'ARQUIVO_RELATORIO'
    
    # Opções de bits para o usuário
    OPCOES_BITS = ['4', '8', '16', '32', '64']

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return VerificarBitsAlgoritmo()

    def name(self):
        return 'fiscalizacao_profundidade_bits'

    def displayName(self):
        return self.tr('Fotos Brutas - Imagem - Profundidade de Bits')

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        return self.tr("Verifica recursivamente se os arquivos TIFF em uma pasta possuem a "
                       "profundidade de bits selecionada. Gera um relatório de auditoria TXT.")

    def initAlgorithm(self, config=None):
        """
        ========================================================================
        INICIALIZAÇÃO DE PARÂMETROS
        ========================================================================
        """
        # Entrada: Pasta
        self.addParameter(
            QgsProcessingParameterFile(
                self.PASTA_ENTRADA,
                self.tr('Selecione a Pasta Mãe (Imagens TIFF)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # Entrada: Escolha da profundidade de bits
        self.addParameter(
            QgsProcessingParameterEnum(
                self.BITS_REFERENCIA,
                self.tr('Profundidade de Bits Esperada'),
                options=self.OPCOES_BITS,
                defaultValue=2  # Valor padrão: 16 (index 2 na lista)
            )
        )

        # Saída: Pasta do Relatório
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.ARQUIVO_RELATORIO,
                self.tr('Pasta para salvar o relatório de auditoria')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        ========================================================================
        PROCESSAMENTO CENTRAL
        ========================================================================
        """
        pasta_mae = self.parameterAsString(parameters, self.PASTA_ENTRADA, context)
        pasta_saida = self.parameterAsString(parameters, self.ARQUIVO_RELATORIO, context)
        
        # Recupera o valor numérico dos bits selecionado pelo usuário
        idx_bits = self.parameterAsInt(parameters, self.BITS_REFERENCIA, context)
        valor_bits_alvo = int(self.OPCOES_BITS[idx_bits])
        
        caminho_txt = os.path.join(pasta_saida, f'relatorio_auditoria_{valor_bits_alvo}bits.txt')
        
        Image.MAX_IMAGE_PIXELS = None
        arquivos_nao_conformes = []
        arquivos_com_erro = []
        total_verificados = 0

        # Mapeamento de arquivos
        arquivos_tiff = []
        for root, _, files in os.walk(pasta_mae):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    arquivos_tiff.append(os.path.join(root, f))

        total_arquivos = len(arquivos_tiff)
        if total_arquivos == 0:
            feedback.reportError("Nenhum arquivo TIFF encontrado.")
            return {self.ARQUIVO_RELATORIO: pasta_saida}

        step = 100.0 / total_arquivos

        for i, caminho_completo in enumerate(arquivos_tiff):
            if feedback.isCanceled():
                break

            total_verificados += 1
            rel_path = os.path.relpath(caminho_completo, pasta_mae)
            
            try:
                with Image.open(caminho_completo) as img:
                    # Extração de metadados via PIL
                    meta_dict = {TAGS.get(key, key): img.tag_v2.get(key) for key in img.tag_v2}
                    bits_encontrados = meta_dict.get('BitsPerSample')

                    if bits_encontrados is None:
                        arquivos_com_erro.append((rel_path, "Tag 'BitsPerSample' ausente"))
                    elif not self._validar_bits(bits_encontrados, valor_bits_alvo):
                        arquivos_nao_conformes.append((rel_path, bits_encontrados))

            except Exception as e:
                arquivos_com_erro.append((rel_path, str(e)))

            feedback.setProgress(int(i * step))

        # Geração do Relatório
        self._gerar_relatorio_txt(caminho_txt, pasta_mae, total_verificados, 
                                 valor_bits_alvo, arquivos_nao_conformes, arquivos_com_erro)

        return {self.ARQUIVO_RELATORIO: caminho_txt}

    def _validar_bits(self, bits_lidos, valor_alvo):
        """Compara o valor lido do arquivo com o alvo selecionado pelo usuário."""
        if isinstance(bits_lidos, tuple):
            return all(b == valor_alvo for b in bits_lidos)
        return bits_lidos == valor_alvo

    def _gerar_relatorio_txt(self, caminho, pasta, total, alvo, lista_falhas, lista_erros):
        """Formata o relatório final com as marcas de auditoria."""
        agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write("==========================================================\n")
            f.write("       RELATÓRIO DE FISCALIZAÇÃO - PROFUNDIDADE DE BITS\n")
            f.write(f"       DATA: {agora}\n")
            f.write("==========================================================\n\n")
            f.write(f"Diretório: {pasta}\n")
            f.write(f"Referência esperada: {alvo} bits\n")
            f.write(f"Total de arquivos analisados: {total}\n\n")

            if not lista_falhas and not lista_erros:
                f.write("✓ STATUS: CONFORME. Todos os arquivos possuem a profundidade correta.\n")
            
            if lista_falhas:
                f.write(f"[!] ALERTAS - FORA DA ESPECIFICAÇÃO (Não possuem {alvo} bits):\n")
                f.write("-" * 60 + "\n")
                for path, bit in lista_falhas:
                    f.write(f"- {path} | Encontrado: {bit}\n")
                f.write("\n")

            if lista_erros:
                f.write("[X] ERROS CRÍTICOS (Arquivos ilegíveis ou metadados corrompidos):\n")
                f.write("-" * 60 + "\n")
                for path, erro in lista_erros:
                    f.write(f"- {path} | Erro: {erro}\n")

            f.write("\n--- Gerado automaticamente pelo sistema de Fiscalização SEI ---")