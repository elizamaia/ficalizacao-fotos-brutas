# -*- coding: utf-8 -*-
"""
Plugin QGIS para Detecção de Arrasto (Motion Blur) em Fotografias Aéreas Brutas

Este algoritmo avalia a nitidez e detecta o borramento por movimento (arrasto)
em fotografias aéreas brutas utilizando estatística direcional do gradiente
de Sobel em amostragem em grade 3x3 com agregação via Média Aparada (Trimmean),
seguindo a metodologia de Takahashi et al. (2020).

Metodologia e Referências:
    - Takahashi, Y., Kuhara, C., & Chikatsu, H. (2020). Image blur detection 
      method based on gradient information in directional statistics. 
      The International Archives of the Photogrammetry, Remote Sensing and 
      Spatial Information Sciences, XLIII-B2-2020, 91-95.
      
Projeto de Pesquisa:
    - Dissertação de Mestrado de Eliza Silva Maia (PPEC/UFBA - 2026).
"""

import os
import glob
from datetime import datetime
import numpy as np
import cv2
from osgeo import gdal
from scipy.stats import skew, kurtosis, trim_mean

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication


class DetectorArrastoTakahashi(QgsProcessingAlgorithm):
    """
    Algoritmo de análise quantitativa de arrasto em fotografias aéreas brutas.

    Processa arquivos GeoTIFF (.tif/.tiff) extraindo recortes de amostragem (512x512)
    em grade 3x3, calcula as métricas direcionais de Sobel 5x5 com binarização automática 
    de Otsu e agrega os resultados pelo método Trimmean.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    INPUT_FOLDER = 'INPUT_FOLDER'
    EVALUATION_THRESHOLD = 'EVALUATION_THRESHOLD'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================

    def tr(self, string):
        """
        Traduz string usando o sistema de internacionalização do QGIS.

        Args:
            string (str): String a ser traduzida.

        Returns:
            str: String traduzida para o idioma atual do QGIS.
        """
        return QCoreApplication.translate('DetectorArrastoTakahashi', string)

    def createInstance(self):
        """Cria uma nova instância do algoritmo."""
        return DetectorArrastoTakahashi()

    def name(self):
        """Retorna o identificador único do algoritmo."""
        return 'detector_arrasto_takahashi'

    def displayName(self):
        """Retorna o nome exibido do algoritmo na Caixa de Ferramentas."""
        return self.tr('Fotos Brutas - Imagem - Arrasto')

    def group(self):
        """Retorna o grupo do algoritmo."""
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        """Retorna o ID do grupo."""
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        """Retorna a documentação resumida para a interface do QGIS."""
        return self.tr(
            "Avalia a nitidez e detecta o borramento por movimento (arrasto) "
            "em fotografias aéreas brutas utilizando estatística direcional do gradiente "
            "de Sobel em amostragem 3x3 com agregação via Trimmean.\n\n"
            "Desenvolvido para a pesquisa de Mestrado de Eliza Silva Maia (PPEC/UFBA)."
        )

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================

    def initAlgorithm(self, config=None):
        """
        Inicializa os parâmetros do algoritmo.

        Define 3 parâmetros organizados nas seguintes categorias:
        1. Pasta de entrada das fotografias
        2. Limiares de avaliação técnica
        3. Arquivo de saída do relatório
        """
        # ======================================
        # INICIALIZAÇÃO DE PARÂMETROS
        # ======================================

        # 1. Pasta com Fotografias Aéreas Brutas
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com as Fotografias Aéreas Brutas (.tif / .tiff)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # 2. Limiar Mínimo de Avaliação
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EVALUATION_THRESHOLD,
                self.tr('Limiar Mínimo de Avaliação para Reprovação por Arrasto (Evaluation Value)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.1
            )
        )

        # 3. Relatório de Saída TXT
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Arquivo de Saída do Relatório TXT'),
                fileFilter='Text Files (*.txt)'
            )
        )

    # =========================================================================
    # MÉTODO PRINCIPAL DE PROCESSAMENTO
    # =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        """
        Executa a rotina central de detecção de arrasto em lote.

        Args:
            parameters (dict): Dicionário de parâmetros do QGIS.
            context (QgsProcessingContext): Contexto de processamento.
            feedback (QgsProcessingFeedback): Interface de progresso e log.

        Returns:
            dict: Dicionário contendo o caminho do arquivo de relatório final.
        """
        # 1. Recuperação e validação inicial dos parâmetros
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params, feedback)
        
        gdal.UseExceptions()

        # 2. Listagem das fotografias
        lista_imagens = self._listar_arquivos(params['pasta_imagens'], feedback)
        total_fotos = len(lista_imagens)

        # 3. Inicialização do relatório
        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, total_fotos))

        resultados_fotos = []

        # 4. Loop de processamento de arquivos com tratamento de erros robusto
        for idx, caminho_foto in enumerate(lista_imagens):
            if feedback.isCanceled():
                break

            nome_foto = os.path.basename(caminho_foto)

            try:
                eval_final = self._processar_imagem(caminho_foto, feedback)
                
                if eval_final > params['limiar_critico']:
                    status = "[!] REPROVADO (ARRASTO DETECTADO)"
                else:
                    status = "✓ APROVADO (NÍTIDO)"

                resultados_fotos.append((nome_foto, eval_final, status))

            except IOError as e:
                msg_erro = f"[ERRO LEITURA] Falha de I/O em {nome_foto}: {str(e)}"
                feedback.reportError(msg_erro)
                resultados_fotos.append((nome_foto, -1.0, msg_erro))

            except Exception as e:
                msg_erro = f"[ERRO CRÍTICO] Falha no processamento de {nome_foto}: {str(e)}"
                feedback.reportError(msg_erro)
                resultados_fotos.append((nome_foto, -1.0, msg_erro))

            # Atualização da barra de progresso
            feedback.setProgress(int(((idx + 1) / total_fotos) * 100))

        # 5. Formatação do corpo e encerramento do relatório
        buffer_relatorio.append(self._formatar_corpo_relatorio(resultados_fotos))
        
        # 6. Escrita do arquivo em disco
        self._escrever_relatorio(params['caminho_relatorio'], buffer_relatorio)

        feedback.pushInfo(self.tr(f"✓ Processamento concluído com sucesso: {total_fotos} fotografia(s) auditada(s)."))
        feedback.pushInfo(self.tr(f"Relatório gerado em: {params['caminho_relatorio']}"))

        return {self.OUTPUT_REPORT: params['caminho_relatorio']}

    # =========================================================================
    # MÉTODOS AUXILIARES PRIVADOS
    # =========================================================================

    def _recuperar_parametros(self, parameters, context):
        """Recupera e estrutura os parâmetros passados pela interface do QGIS."""
        return {
            'pasta_imagens': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'limiar_critico': self.parameterAsDouble(parameters, self.EVALUATION_THRESHOLD, context),
            'caminho_relatorio': self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)
        }

    def _validar_parametros(self, params, feedback):
        """Valida a coerência dos parâmetros informados."""
        if not params['pasta_imagens'] or not os.path.exists(params['pasta_imagens']):
            raise QgsProcessingException(self.tr("A pasta de imagens informada é inválida ou não existe."))

        if params['limiar_critico'] <= 0:
            raise QgsProcessingException(self.tr("O Limiar Crítico de Avaliação deve ser maior que zero."))

    def _listar_arquivos(self, pasta, feedback):
        """Varre a pasta informada buscando arquivos GeoTIFF de imagem aérea."""
        extensoes = ('*.tif', '*.tiff', '*.geotiff', '*.TIF', '*.TIFF')
        arquivos = []
        for ext in extensoes:
            arquivos.extend(glob.glob(os.path.join(pasta, "**", ext), recursive=True))

        if not arquivos:
            raise QgsProcessingException(
                self.tr(f"Nenhuma imagem GeoTIFF encontrada na pasta: {pasta}")
            )

        return sorted(list(set(arquivos)))

    def _processar_imagem(self, caminho_foto, feedback):
        """
        Abre a imagem via GDAL, amostra 9 recortes (512x512) em grade 3x3 e 
        calcula o valor final de avaliação agregado por Média Aparada (Trimmean).
        """
        ds = gdal.Open(caminho_foto, gdal.GA_ReadOnly)
        if ds is None:
            raise IOError(f"Não foi possível abrir a imagem via GDAL: {caminho_foto}")

        largura = ds.RasterXSize
        altura = ds.RasterYSize
        banda = ds.GetRasterBand(1).ReadAsArray()
        ds = None  # Libera a memória do dataset

        tamanho_crop = 512
        xs = [int(largura * 0.2), int(largura * 0.5), int(largura * 0.8)]
        ys = [int(altura * 0.2), int(altura * 0.5), int(altura * 0.8)]

        valores_crops = []

        for x in xs:
            for y in ys:
                x_ini = max(0, x - tamanho_crop // 2)
                y_ini = max(0, y - tamanho_crop // 2)
                
                crop = banda[y_ini:y_ini + tamanho_crop, x_ini:x_ini + tamanho_crop]

                if crop.shape[0] == tamanho_crop and crop.shape[1] == tamanho_crop:
                    val = self._calcular_takahashi_crop(crop)
                    valores_crops.append(val)

        if not valores_crops:
            raise ValueError(f"Dimensões da fotografia ({largura}x{altura}) insuficientes para amostragem 512x512.")

        # Agregação via Média Aparada (Trimmean - descarta menor e maior valor)
        if len(valores_crops) > 2:
            eval_final = trim_mean(valores_crops, proportiontocut=1.0 / len(valores_crops))
        else:
            eval_final = np.mean(valores_crops)

        return float(eval_final)

    def _calcular_takahashi_crop(self, img_crop):
        """
        Calcula o Evaluation Value de um crop 512x512 conforme Takahashi et al. (2020).
        
        Aplica derivativas de Sobel 5x5, variância circular, histograma direcional 36 bins,
        partição via Otsu e análise de curtose e assimetria.
        """
        # 1. Filtro de Sobel (Derivadas parciais gH e gV em janela 5x5)
        gH = cv2.Sobel(img_crop, cv2.CV_64F, 1, 0, ksize=5)
        gV = cv2.Sobel(img_crop, cv2.CV_64F, 0, 1, ksize=5)

        # 2. Magnitude (nabla I) e Direção (nabla theta)
        magnitude = np.sqrt(gH**2 + gV**2)
        mean_magnitude = np.mean(magnitude)

        if mean_magnitude == 0:
            return 0.0  # Área completamente homogênea / sem textura

        direcao_rad = np.arctan2(gV, gH)
        direcao_deg = np.degrees(direcao_rad) % 360

        # 3. Variância Circular (sigma^2_theta)
        c_bar = np.mean(np.cos(direcao_rad))
        s_bar = np.mean(np.sin(direcao_rad))
        variancia_circular = 1.0 - np.sqrt(c_bar**2 + s_bar**2)

        # 4. Histograma Direcional (36 bins de 10 graus cada)
        counts, _ = np.histogram(direcao_deg, bins=36, range=(0, 360))

        # 5. Normalização: Rotaciona a partir do ângulo de menor frequência
        min_idx = np.argmin(counts)
        counts_rot = np.roll(counts, -min_idx)

        # 6. Partição Automática por Limiarização de Otsu
        counts_norm = cv2.normalize(counts_rot, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, _ = cv2.threshold(counts_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        regiao1 = counts_rot[:18]
        regiao2 = counts_rot[18:]

        # 7. Curtose e Assimetria nas Regiões
        kurt1 = kurtosis(regiao1, fisher=False)
        kurt2 = kurtosis(regiao2, fisher=False)
        skew1 = skew(regiao1)
        skew2 = skew(regiao2)

        # 8. Cálculo do Valor de Avaliação (Evaluation Value)
        diferenca_curtose = abs((kurt1 + kurt2) - 3.0)
        diferenca_assimetria = abs(skew1 - skew2)

        evaluation_value = ((diferenca_curtose - diferenca_assimetria) / mean_magnitude) * variancia_circular * 100.0

        return max(0.0, float(evaluation_value))

    def _criar_cabecalho(self, params, total_fotos):
        """Cria o cabeçalho padronizado do relatório final de auditoria."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        linhas = [
            "==================================================================================",
            " PPEC/UFBA - RELATÓRIO DE AVALIAÇÃO DE ARRASTO (MOTION BLUR)",
            " Metodologia: Estatística Direcional de Takahashi et al. (2020)",
            " Pesquisa: Dissertação de Mestrado de Eliza Silva Maia (PPEC/UFBA)",
            "==================================================================================",
            f"Data/Hora do Processamento: {agora}",
            f"Diretório Analisado: {params['pasta_imagens']}",
            f"Total de Fotografias Auditadas: {total_fotos}",
            "",
            "PARÂMETROS DE CONFIGURAÇÃO:",
            f"  • Limiar Mínimo de Avaliação (Evaluation Value): {params['limiar_critico']:.2f}",
            "  • Amostragem: Grade 3x3 de Crops (512x512 px) com Agregação via Trimmean",
            "==================================================================================",
            ""
        ]
        return "\n".join(linhas)

    def _formatar_corpo_relatorio(self, resultados):
        """Formata os dados de resultados de auditoria por imagem no relatório."""
        reprovadas = [r for r in resultados if "[!]" in r[2]]
        aprovadas = [r for r in resultados if "✓" in r[2]]

        linhas = [
            "SÍNTESE DA INSPEÇÃO VISUAL:",
            f"  • Fotografias Aprovadas (Nítidas): {len(aprovadas)}",
            f"  • Fotografias Reprovadas (Com Arrasto): {len(reprovadas)}",
            "",
            "----------------------------------------------------------------------------------",
            "DETALHAMENTO POR FOTOGRAFIA AÉREA BRUTA:",
            "----------------------------------------------------------------------------------"
        ]

        for foto, val, status in resultados:
            if val >= 0:
                linhas.append(f" Imagem: {foto:<40} | Evaluation Value: {val:7.3f} | Status: {status}")
            else:
                linhas.append(f" Imagem: {foto:<40} | Status: {status}")

        linhas.extend([
            "==================================================================================",
            "FIM DO RELATÓRIO"
        ])

        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho_saida, buffer):
        """Salva o buffer com todas as linhas do relatório em um arquivo texto de saída."""
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write("\n".join(buffer) if isinstance(buffer, list) else buffer)
        except IOError as e:
            raise QgsProcessingException(self.tr(f"Erro ao gravar arquivo de relatório: {str(e)}"))