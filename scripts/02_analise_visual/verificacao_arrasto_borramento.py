# -*- coding: utf-8 -*-
"""
Plugin QGIS para Detecção de Arrasto (Motion Blur) em Fotografias Aéreas Brutas
com Filtragem de Keypoints (Pontos de Máximo Local).

Este algoritmo processa arquivos GeoTIFF e gera um relatório de controle de 
qualidade baseado na metodologia de estatística direcional do gradiente de 
Sobel (Takahashi et al., 2020) para detectar anomalias visuais de arrasto.

Cálculos:
    - Normalização: Escalonamento radiométrico direto de 16 bits para 8 bits (/ 256.0).
    - Keypoints: Extração de extremos locais de luminância via maximum_filter 5x5.
    - Avaliação: Estatística direcional (Sobel 5x5, variância circular, partição de Otsu).
    - Agregação: Média Aparada (Trimmean) em grade espacial 3x3.

Autor: Eliza Silva Maia (PPEC/UFBA)
Data: 2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
import numpy as np
from scipy.stats import skew, kurtosis, trim_mean
from scipy.ndimage import convolve, maximum_filter
from osgeo import gdal
import os
import glob
from datetime import datetime


class DetectorArrastoTakahashi(QgsProcessingAlgorithm):
    """
    Algoritmo de análise quantitativa de arrasto em fotografias aéreas brutas
    com extração de feições locais baseada em keypoints.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'
    EVALUATION_THRESHOLD = 'EVALUATION_THRESHOLD'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================

    def tr(self, string):
        return QCoreApplication.translate('DetectorArrastoTakahashi', string)

    def createInstance(self):
        return DetectorArrastoTakahashi()

    def name(self):
        return 'detector_arrasto_takahashi'

    def displayName(self):
        return self.tr('Fotos Brutas - Imagem - Arrasto (Keypoints)')

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com as Fotografias Aéreas Brutas (.tif / .tiff)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.EVALUATION_THRESHOLD,
                self.tr('Limite de Avaliação para Reprovação (Evaluation Value)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.50,
                minValue=0.01
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Relatório Final em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    # =========================================================================
    # MÉTODO PRINCIPAL DE PROCESSAMENTO
    # =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params, feedback)
        
        gdal.UseExceptions()

        lista_arquivos = self._listar_arquivos(params['pasta'], feedback)
        total_arquivos = len(lista_arquivos)
        
        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, total_arquivos))

        resultados_fotos = []

        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            nome_arquivo = os.path.basename(caminho_arquivo)
            feedback.setProgress(int((i / total_arquivos) * 100))

            try:
                eval_final = self._processar_imagem(caminho_arquivo, feedback)
                
                if eval_final > params['limiar_critico']:
                    status = "[!] REPROVADO (ARRASTO DETECTADO)"
                else:
                    status = "✓ APROVADO (NÍTIDO)"

                resultados_fotos.append((nome_arquivo, eval_final, status))

            except IOError as e:
                msg_erro = f"[ERRO LEITURA] Falha de I/O: {str(e)}"
                feedback.reportError(self.tr(f"Erro de I/O em {nome_arquivo}: {e}"))
                resultados_fotos.append((nome_arquivo, -1.0, msg_erro))

            except Exception as e:
                msg_erro = f"[ERRO CRÍTICO] Falha inesperada: {str(e)}"
                feedback.reportError(self.tr(f"Erro inesperado em {nome_arquivo}: {e}"))
                resultados_fotos.append((nome_arquivo, -1.0, msg_erro))

        buffer_relatorio.append(self._formatar_corpo_relatorio(resultados_fotos))
        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(
            self.tr(f"✓ Processamento concluído: {total_arquivos} fotografia(s) auditada(s)")
        )

        return {self.OUTPUT_REPORT: params['arquivo_saida']}

    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================

    def _recuperar_parametros(self, parameters, context):
        return {
            'pasta': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'limiar_critico': self.parameterAsDouble(parameters, self.EVALUATION_THRESHOLD, context),
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context)
        }

    def _validar_parametros(self, params, feedback):
        if not params['pasta'] or not os.path.exists(params['pasta']):
            raise QgsProcessingException(
                self.tr("A pasta de imagens informada é inválida ou não existe.")
            )

        if params['limiar_critico'] <= 0:
            raise QgsProcessingException(
                self.tr("O limite de avaliação deve ser maior que zero.")
            )

    def _listar_arquivos(self, pasta, feedback):
        extensoes = ('*.tif', '*.tiff', '*.geotiff', '*.TIF', '*.TIFF')
        arquivos = []
        for ext in extensoes:
            arquivos.extend(glob.glob(os.path.join(pasta, "**", ext), recursive=True))

        if not arquivos:
            raise QgsProcessingException(
                self.tr(f"Nenhum arquivo TIFF encontrado em: {pasta}")
            )

        return sorted(list(set(arquivos)))

    def _processar_imagem(self, caminho_foto, feedback):
        ds = gdal.Open(caminho_foto, gdal.GA_ReadOnly)
        if ds is None:
            raise IOError(self.tr("Falha ao abrir imagem via GDAL."))

        largura = ds.RasterXSize
        altura = ds.RasterYSize
        banda = ds.GetRasterBand(1).ReadAsArray()
        ds = None

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
            raise ValueError(self.tr(f"Dimensões insuficientes para amostragem 512x512 ({largura}x{altura})."))

        if len(valores_crops) > 2:
            eval_final = trim_mean(valores_crops, proportiontocut=1.0 / len(valores_crops))
        else:
            eval_final = np.mean(valores_crops)

        return float(eval_final)

    def _calcular_takahashi_crop(self, img_crop):
        """
        Calcula o Evaluation Value de um crop de 512x512 pixels utilizando
        a extração de Keypoints por máximos locais e estatística circular.
        """
        # 1. Normalização Radiométrica Direta (16-bit para escala de 8-bit)
        if img_crop.dtype == np.uint16 or img_crop.max() > 255:
            img_crop_norm = img_crop.astype(float) / 256.0
        else:
            img_crop_norm = img_crop.astype(float)

        # 2. Convolução de Sobel 5x5 (Gradientes Horizontal e Vertical)
        sobel_x = np.array([
            [-1, -2, 0,  2,  1],
            [-4, -8, 0,  8,  4],
            [-6,-12, 0, 12,  6],
            [-4, -8, 0,  8,  4],
            [-1, -2, 0,  2,  1]
        ], dtype=float)
        sobel_y = sobel_x.T

        gH = convolve(img_crop_norm, sobel_x)
        gV = convolve(img_crop_norm, sobel_y)

        magnitude = np.sqrt(gH**2 + gV**2)
        direcao_rad = np.arctan2(gV, gH)
        direcao_deg = np.degrees(direcao_rad) % 360.0

        # 3. Extração de Keypoints (Máximos Locais 5x5 com Magnitude > 1.0)
        local_max = maximum_filter(img_crop_norm, size=5)
        keypoints_mask = (img_crop_norm == local_max) & (magnitude > 1.0)

        # Salvaguarda: neutraliza janelas homogêneas sem feições estruturadas
        if np.count_nonzero(keypoints_mask) < 30:
            return 0.0

        kp_angles = direcao_deg[keypoints_mask]
        kp_mags = magnitude[keypoints_mask]

        # 4. Magnitude Média dos Keypoints
        mean_magnitude = float(np.mean(kp_mags))
        if mean_magnitude <= 0.0:
            return 0.0

        # 5. Variância Circular dos Keypoints
        kp_rad = np.radians(kp_angles)
        c_bar = np.mean(np.cos(kp_rad))
        s_bar = np.mean(np.sin(kp_rad))
        variancia_circular = 1.0 - np.sqrt(c_bar**2 + s_bar**2)

        # 6. Histograma Angular (36 bins -> 10 graus cada)
        counts, _ = np.histogram(kp_angles, bins=36, range=(0, 360))

        # 7. Alinhamento pela Frequência Mínima
        min_idx = np.argmin(counts)
        counts_rot = np.roll(counts, -min_idx)

        # 8. Partição de Otsu no Espaço de Bins
        best_var = -1.0
        best_t = 18
        total_bins = len(counts_rot)
        
        for t in range(1, total_bins):
            mean1 = np.mean(counts_rot[:t])
            mean2 = np.mean(counts_rot[t:])
            var_between = t * (total_bins - t) * ((mean1 - mean2)**2)
            
            if var_between > best_var:
                best_var = var_between
                best_t = t

        best_t = max(3, min(best_t, 33))

        regiao1 = counts_rot[:best_t]
        regiao2 = counts_rot[best_t:]

        # 9. Momentos Estatísticos (Curtose e Assimetria)
        kurt1 = kurtosis(regiao1, fisher=False)
        kurt2 = kurtosis(regiao2, fisher=False)
        skew1 = skew(regiao1)
        skew2 = skew(regiao2)

        diferenca_curtose = abs((kurt1 + kurt2) - 3.0)
        diferenca_assimetria = abs(skew1 - skew2)

        # 10. Métrica Final de Avaliação (Evaluation Value)
        evaluation_value = ((diferenca_curtose - diferenca_assimetria) / mean_magnitude) * variancia_circular * 100.0

        return max(0.0, float(evaluation_value))

    def _criar_cabecalho(self, params, total_fotos):
        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE AVALIAÇÃO DE ARRASTO (MOTION BLUR - KEYPOINTS)"),
            self.tr(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 80,
            self.tr("PARÂMETROS DE CONFIGURAÇÃO:"),
            f"  • Diretório: {params['pasta']}",
            f"  • Fotografias Auditadas: {total_fotos}",
            f"  • Limite de Reprovação (Evaluation Value): {params['limiar_critico']:.2f}",
            f"  • Amostragem: Grade 3x3 de Crops (512x512) com Keypoints e Trimmean",
            "=" * 80,
            ""
        ]
        return "\n".join(linhas)

    def _formatar_corpo_relatorio(self, resultados):
        reprovadas = [r for r in resultados if "[!]" in r[2]]
        aprovadas = [r for r in resultados if "✓" in r[2]]

        linhas = [
            self.tr("📊 SÍNTESE DA INSPEÇÃO VISUAL"),
            f"  • Fotografias Aprovadas (Nítidas): {len(aprovadas)}",
            f"  • Fotografias Reprovadas (Com Arrasto): {len(reprovadas)}",
            "",
            "-" * 80,
            self.tr("DETALHAMENTO POR FOTOGRAFIA AÉREA BRUTA"),
            "-" * 80,
        ]

        for foto, val, status in resultados:
            if val >= 0:
                linhas.append(f" Imagem: {foto:<40} | Eval: {val:7.3f} | Status: {status}")
            else:
                linhas.append(f" Imagem: {foto:<40} | Status: {status}")

        linhas.extend([
            "",
            "=" * 80,
            self.tr("FIM DO RELATÓRIO")
        ])
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho_saida, buffer):
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(
                self.tr(f"Erro ao escrever arquivo de saída: {str(e)}")
            )