# -*- coding: utf-8 -*-
"""
Plugin QGIS para Análise de Qualidade Visual: Arrasto/Borramento
Replicação estrita da metodologia de Takahashi et al. (2020)
- Estatística Direcional
- Filtro Sobel (5x5)
- Histograma de Gradiente e Otsu
- Média Aparada (Trimmean) em 9 recortes de 512x512
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
from osgeo import gdal
import numpy as np
import cv2
from scipy.stats import skew, kurtosis
import os
import glob
from datetime import datetime

class AnaliseBorramentoTakahashi(QgsProcessingAlgorithm):

    INPUT_FOLDER = 'INPUT_FOLDER'
    RECURSIVE = 'RECURSIVE'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    def tr(self, string):
        return QCoreApplication.translate('AnaliseBorramentoTakahashi', string)

    def createInstance(self):
        return AnaliseBorramentoTakahashi()

    def name(self):
        return 'analise_borramento_takahashi'

    def displayName(self):
        return self.tr('Fotos Brutas - Imagem - Arrasto/Borramento (Takahashi 2020)')

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta principal com as Fotografias Aéreas (.tif)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RECURSIVE,
                self.tr('Buscar em subpastas?'),
                defaultValue=True
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Relatório Final em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    def calcular_metricas_takahashi(self, crop):
        """
        Aplica os 12 passos da Figura 7 (Takahashi et al., 2020) em um recorte de 512x512.
        """
        # Sobel 5x5 (Passo 4.1 do artigo)
        gH = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=5)
        gV = cv2.Sobel(crop, cv2.CV_64F, 0, 1, ksize=5)

        # Magnitude e Direção
        magnitude = np.sqrt(gH**2 + gV**2)
        direction = np.arctan2(gV, gH) * (180 / np.pi)
        direction = np.mod(direction, 360) # Normalizar para 0-359

        # Histograma (Passo 1)
        hist, bins = np.histogram(direction, bins=360, range=(0, 360))
        
        # Normalizar histograma pela menor frequência (Passo 2)
        min_idx = np.argmin(hist)
        hist_shifted = np.roll(hist, -min_idx)
        
        # Threshold de Otsu para dividir em 2 áreas (Passo 3)
        # Como o Otsu do CV2 requer imagem 8-bit, adaptamos para o array do histograma
        hist_norm = cv2.normalize(hist_shifted, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, thresh = cv2.threshold(hist_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Áreas divididas baseadas no limite de Otsu
        area1 = hist_shifted[hist_norm.flatten() <= thresh[0][0]]
        area2 = hist_shifted[hist_norm.flatten() > thresh[0][0]]

        # Se alguma área ficar vazia devido a imagens com cor sólida/sem borda, tratamos o erro
        if len(area1) == 0 or len(area2) == 0:
            return None

        # Skewness (Passo 4)
        skewness_val = skew(hist_shifted)

        # Kurtosis de cada área (Passo 5)
        kurt1 = kurtosis(area1)
        kurt2 = kurtosis(area2)

        # Adicionar kurtosis da distribuição uniforme (1.8) (Passo 6)
        kurt1_unif = kurt1 + 1.8
        kurt2_unif = kurt2 + 1.8

        # Soma e Diferença Absoluta (Passos 7 e 8)
        soma = kurt1_unif + kurt2_unif
        diff_abs = abs(kurt1_unif - kurt2_unif)

        # Diferença do passo anterior (Passo 9)
        diff_9 = soma - diff_abs

        # Diferença com Skewness (Passo 10)
        diff_10 = diff_9 - skewness_val

        # Dividir pela magnitude média (Passo 11)
        mean_mag = np.mean(magnitude)
        if mean_mag == 0: return None
        val_11 = diff_10 / mean_mag

        # Variância Circular
        cos_theta = np.mean(np.cos(np.radians(direction)))
        sin_theta = np.mean(np.sin(np.radians(direction)))
        var_circular = 1 - np.sqrt(cos_theta**2 + sin_theta**2)

        # Multiplicar pela variância circular (Passo 12 - Valor de Avaliação Final)
        eval_value = val_11 * var_circular

        return eval_value

    def processAlgorithm(self, parameters, context, feedback):
        pasta_entrada = self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        busca_recursiva = self.parameterAsBool(parameters, self.RECURSIVE, context)
        arquivo_saida = self.parameterAsString(parameters, self.OUTPUT_REPORT, context)

        if busca_recursiva:
            padrao_busca = os.path.join(pasta_entrada, '**', '*.tif')
            lista_arquivos = glob.glob(padrao_busca, recursive=True)
        else:
            padrao_busca = os.path.join(pasta_entrada, '*.tif')
            lista_arquivos = glob.glob(padrao_busca)

        if not lista_arquivos:
            raise QgsProcessingException(self.tr("Nenhum arquivo .tif encontrado."))

        buffer_relatorio = []
        buffer_relatorio.append("=" * 80)
        buffer_relatorio.append("RELATÓRIO DE CONTROLE DE QUALIDADE: ARRASTO (Metodologia Takahashi 2020)")
        buffer_relatorio.append(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        buffer_relatorio.append("Técnica: 9 recortes de 512x512 com Trimmean (média aparada)")
        buffer_relatorio.append("=" * 80)

        total_arquivos = len(lista_arquivos)
        
        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break
            
            nome_arquivo = os.path.basename(caminho_arquivo)
            feedback.setProgress(int((i / total_arquivos) * 100))
            
            try:
                dataset = gdal.Open(caminho_arquivo)
                if not dataset:
                    buffer_relatorio.append(f"[ERRO LEITURA] {nome_arquivo}")
                    continue

                x_size = dataset.RasterXSize
                y_size = dataset.RasterYSize
                band = dataset.GetRasterBand(1) # Banda 1 (R)
                
                crop_size = 512
                eval_values = []

                # Gerar 9 pontos distribuídos (grade 3x3)
                x_steps = [int(x_size * 0.25), int(x_size * 0.5), int(x_size * 0.75)]
                y_steps = [int(y_size * 0.25), int(y_size * 0.5), int(y_size * 0.75)]

                for y in y_steps:
                    for x in x_steps:
                        # Ajustar offset para centralizar o recorte no ponto
                        x_off = max(0, min(x - crop_size//2, x_size - crop_size))
                        y_off = max(0, min(y - crop_size//2, y_size - crop_size))
                        
                        crop = band.ReadAsArray(x_off, y_off, crop_size, crop_size)
                        
                        # Normalizar para 8bits
                        if crop.dtype == np.uint16:
                            crop = (crop / 256).astype(np.uint8)
                        
                        val = self.calcular_metricas_takahashi(crop)
                        if val is not None:
                            eval_values.append(val)
                            
                dataset = None # Fechar arquivo

                # Aplicar Trimmean (Remover min e max, e fazer a média)
                if len(eval_values) >= 3:
                    eval_values.sort()
                    eval_values = eval_values[1:-1] # Remove o menor (índice 0) e o maior (último índice)
                    trimmean = np.mean(eval_values)
                    buffer_relatorio.append(f"Imagem: {nome_arquivo} | Valor Trimmean: {trimmean:.5f}")
                else:
                    buffer_relatorio.append(f"Imagem: {nome_arquivo} | Valor Trimmean: FALHA (Feições insuficientes nos recortes)")

            except Exception as e:
                buffer_relatorio.append(f"[ERRO PROCESSAMENTO] {nome_arquivo}: {str(e)}")

        # Salvar relatório
        try:
            with open(arquivo_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer_relatorio))
        except IOError as e:
            raise QgsProcessingException(self.tr(f"Erro ao salvar arquivo: {str(e)}"))

        return {self.OUTPUT_REPORT: arquivo_saida}