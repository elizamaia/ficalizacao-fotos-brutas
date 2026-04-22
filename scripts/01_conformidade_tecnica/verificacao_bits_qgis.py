# -*- coding: utf-8 -*-

"""
MODELO DE SCRIPT PARA CAIXA DE FERRAMENTAS DO QGIS
Contexto: Projeto de Mestrado - Eliza Silva Maia (PPEC/UFBA)
Objetivo: Verificação de Conformidade Radiométrica (16 bits) em lote.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterFolderDestination,
                       QgsMessageLog)
import os
from PIL import Image
from PIL.TiffTags import TAGS
from datetime import datetime

class VerificarBitsAlgoritmo(QgsProcessingAlgorithm):
    """
    Algoritmo para verificar recursivamente se imagens TIFF possuem 16 bits,
    conforme os parâmetros de conformidade técnica da pesquisa.
    """

    # Constantes dos Parâmetros
    PASTA_ENTRADA = 'PASTA_ENTRADA'
    ARQUIVO_RELATORIO = 'ARQUIVO_RELATORIO'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return VerificarBitsAlgoritmo()

    def name(self):
        return 'verificar_conformidade_16bits'

    def displayName(self):
        return self.tr('Fotos Brutas - Relatório - Profundidade de Bits')

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        return self.tr("Verifica se os arquivos TIFF em uma pasta e subpastas são de 16 bits. "
                       "Gera um relatório TXT detalhado com os resultados.")

    def initAlgorithm(self, config=None):
        """
        ========================================================================
        INICIALIZAÇÃO DE PARÂMETROS
        ========================================================================
        """
        self.addParameter(
            QgsProcessingParameterFile(
                self.PASTA_ENTRADA,
                self.tr('Selecione a Pasta Mãe (Imagens TIFF)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

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
        
        caminho_txt = os.path.join(pasta_saida, 'relatorio_conformidade_bits.txt')
        
        Image.MAX_IMAGE_PIXELS = None
        arquivos_nao_16bit = []
        arquivos_com_erro = []
        total_verificados = 0

        # Lista arquivos para o progresso
        arquivos_tiff = []
        for root, _, files in os.walk(pasta_mae):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    arquivos_tiff.append(os.path.join(root, f))

        total_arquivos = len(arquivos_tiff)
        if total_arquivos == 0:
            feedback.reportError("Nenhum arquivo TIFF encontrado na pasta selecionada.")
            return {self.ARQUIVO_RELATORIO: caminho_txt}

        step = 100.0 / total_arquivos

        for i, caminho_completo in enumerate(arquivos_tiff):
            if feedback.isCanceled():
                break

            total_verificados += 1
            rel_path = os.path.relpath(caminho_completo, pasta_mae)
            
            try:
                with Image.open(caminho_completo) as img:
                    # Lógica de extração de metadados [cite: 150, 224]
                    meta_dict = {TAGS.get(key, key): img.tag_v2.get(key) for key in img.tag_v2}
                    bits = meta_dict.get('BitsPerSample')

                    if bits is None:
                        arquivos_com_erro.append((rel_path, "Tag 'BitsPerSample' ausente"))
                    elif self._validar_bits(bits) is False:
                        arquivos_nao_16bit.append((rel_path, bits))

            except Exception as e:
                arquivos_com_erro.append((rel_path, str(e)))
                feedback.reportError(f"Erro no arquivo {rel_path}: {str(e)}")

            feedback.setProgress(int(i * step))

        # Geração do Relatório Final
        self._gerar_relatorio_txt(caminho_txt, pasta_mae, total_verificados, arquivos_nao_16bit, arquivos_com_erro)

        feedback.pushInfo(f"Verificação concluída. Relatório salvo em: {caminho_txt}")

        return {self.ARQUIVO_RELATORIO: caminho_txt}

    def _validar_bits(self, bits_per_sample):
        """Método auxiliar para validar a tupla ou inteiro de bits."""
        if isinstance(bits_per_sample, tuple):
            return all(b == 16 for b in bits_per_sample)
        return bits_per_sample == 16

    def _gerar_relatorio_txt(self, caminho, pasta, total, lista_falhas, lista_erros):
        """Formata o relatório de saída conforme diretrizes de auditoria."""
        agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write("==========================================================\n")
            f.write("       RELATÓRIO DE CONFORMIDADE TÉCNICA - BITS\n")
            f.write(f"       Data do Processamento: {agora}\n")
            f.write("==========================================================\n\n")
            f.write(f"Pasta analisada: {pasta}\n")
            f.write(f"Total de arquivos TIFF verificados: {total}\n\n")

            if not lista_falhas and not lista_erros:
                f.write("✓ STATUS: Todos os arquivos estão em conformidade (16 bits).\n")
            
            if lista_falhas:
                f.write("[!] ALERTAS - ARQUIVOS FORA DA ESPECIFICAÇÃO (16-bit):\n")
                f.write("-" * 60 + "\n")
                for path, bit in lista_falhas:
                    f.write(f"- {path} | Bits encontrados: {bit}\n")
                f.write("\n")

            if lista_erros:
                f.write("[X] ERROS DE PROCESSAMENTO/ARQUIVOS CORROMPIDOS:\n")
                f.write("-" * 60 + "\n")
                for path, erro in lista_erros:
                    f.write(f"- {path} | Erro: {erro}\n")

            f.write("\n--- Fim do Relatório ---")