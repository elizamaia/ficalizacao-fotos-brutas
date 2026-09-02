# -*- coding: utf-8 -*-
"""
Plugin QGIS para Detecção de Arrasto (Motion Blur) em Fotografias Aéreas Brutas
com Extração de Keypoints, Leitura por Janela (Big Earth Data) e Laudo Técnico Sobrio.

Estrutura do Laudo Técnico de Fiscalização:
    1. Parâmetros de Configuração e Metadados da Auditoria
    2. Painel de Triagem Inicial: Fotografias Não Conformes e Inconsistentes
    3. Detalhamento Integral: Registro Sequencial de Todas as Fotografias Auditadas
    4. Síntese Estatística e Projeção de Conformidade

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
import gc
from datetime import datetime


class DetectorArrastoTakahashi(QgsProcessingAlgorithm):

    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'
    EVALUATION_THRESHOLD = 'EVALUATION_THRESHOLD'

    def tr(self, string):
        return QCoreApplication.translate('DetectorArrastoTakahashi', string)

    def createInstance(self):
        return DetectorArrastoTakahashi()

    def name(self):
        return 'detector_arrasto_takahashi'

    def displayName(self):
        return self.tr('Fotos Brutas - Imagem - Arrasto')

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

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
                self.tr('Limite Crítico de Reprovação (Evaluation Value)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.30,
                minValue=0.01
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Laudo Técnico em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params, feedback)
        
        gdal.UseExceptions()

        lista_arquivos = self._listar_arquivos(params['pasta'], feedback)
        total_arquivos = len(lista_arquivos)

        resultados = []
        total_aprovadas = 0
        total_reprovadas = 0
        total_corrompidas = 0

        inicio_processamento = datetime.now()

        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            nome_arquivo = os.path.basename(caminho_arquivo)
            feedback.setProgress(int((i / total_arquivos) * 100))

            try:
                eval_final = self._processar_imagem_otimizada(caminho_arquivo)
                
                if eval_final > params['limiar_critico']:
                    status = "REPROVADO (ARRASTO DETECTADO)"
                    is_inconforme = True
                    total_reprovadas += 1
                else:
                    status = "APROVADO (NITIDO)"
                    is_inconforme = False
                    total_aprovadas += 1

                resultados.append({
                    'foto': nome_arquivo,
                    'eval': eval_final,
                    'status': status,
                    'inconforme': is_inconforme,
                    'erro': False
                })

            except Exception as e:
                total_corrompidas += 1
                msg_falha = f"REPROVADO (FALHA DE LEITURA / ARQUIVO CORROMPIDO: {str(e)[:45]})"
                feedback.reportError(self.tr(f"Falha fisica no arquivo {nome_arquivo}: {str(e)}"))

                resultados.append({
                    'foto': nome_arquivo,
                    'eval': -1.0,
                    'status': msg_falha,
                    'inconforme': True,
                    'erro': True
                })

            if i % 100 == 0:
                gc.collect()

        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, total_arquivos, inicio_processamento))
        buffer_relatorio.append(self._criar_painel_reprovadas(resultados, params['limiar_critico']))
        buffer_relatorio.append(self._criar_painel_todas(resultados))
        buffer_relatorio.append(self._criar_rodape(total_arquivos, total_aprovadas, total_reprovadas, total_corrompidas))

        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(
            self.tr(f"Auditoria concluida: {total_arquivos} fotos | Aprovadas: {total_aprovadas} | Reprovadas por Arrasto: {total_reprovadas} | Falhas de I/O: {total_corrompidas}")
        )

        return {self.OUTPUT_REPORT: params['arquivo_saida']}

    def _recuperar_parametros(self, parameters, context):
        return {
            'pasta': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'limiar_critico': self.parameterAsDouble(parameters, self.EVALUATION_THRESHOLD, context),
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context)
        }

    def _validar_parametros(self, params, feedback):
        if not params['pasta'] or not os.path.exists(params['pasta']):
            raise QgsProcessingException(self.tr("A pasta informada e invalida ou inacessivel."))
        if params['limiar_critico'] <= 0:
            raise QgsProcessingException(self.tr("O limite de avaliacao deve ser superior a zero."))

    def _listar_arquivos(self, pasta, feedback):
        extensoes = ('*.tif', '*.tiff', '*.geotiff', '*.TIF', '*.TIFF')
        arquivos = []
        for ext in extensoes:
            arquivos.extend(glob.glob(os.path.join(pasta, "**", ext), recursive=True))

        if not arquivos:
            raise QgsProcessingException(self.tr(f"Nenhum arquivo TIFF encontrado em: {pasta}"))

        return sorted(list(set(arquivos)))

    def _processar_imagem_otimizada(self, caminho_foto):
        ds = None
        valores_crops = []
        tamanho_crop = 512

        try:
            ds = gdal.Open(caminho_foto, gdal.GA_ReadOnly)
            if ds is None:
                raise IOError("GDAL nao conseguiu obter descritor do arquivo.")

            largura = ds.RasterXSize
            altura = ds.RasterYSize
            banda = ds.GetRasterBand(1)

            xs = [int(largura * 0.2), int(largura * 0.5), int(largura * 0.8)]
            ys = [int(altura * 0.2), int(altura * 0.5), int(altura * 0.8)]

            for x in xs:
                for y in ys:
                    x_ini = max(0, x - tamanho_crop // 2)
                    y_ini = max(0, y - tamanho_crop // 2)

                    if x_ini + tamanho_crop <= largura and y_ini + tamanho_crop <= altura:
                        crop = banda.ReadAsArray(x_ini, y_ini, tamanho_crop, tamanho_crop)
                        if crop is not None and crop.shape == (tamanho_crop, tamanho_crop):
                            val = self._calcular_takahashi_crop(crop)
                            valores_crops.append(val)

        finally:
            banda = None
            ds = None

        if not valores_crops:
            raise ValueError("Dimensoes insuficientes ou falha na leitura dos recortes.")

        if len(valores_crops) > 2:
            eval_final = trim_mean(valores_crops, proportiontocut=1.0 / len(valores_crops))
        else:
            eval_final = np.mean(valores_crops)

        return float(eval_final)

    def _calcular_takahashi_crop(self, img_crop):
        if img_crop.dtype == np.uint16 or img_crop.max() > 255:
            img_crop_norm = img_crop.astype(float) / 256.0
        else:
            img_crop_norm = img_crop.astype(float)

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

        local_max = maximum_filter(img_crop_norm, size=5)
        keypoints_mask = (img_crop_norm == local_max) & (magnitude > 1.0)

        if np.count_nonzero(keypoints_mask) < 30:
            return 0.0

        kp_angles = direcao_deg[keypoints_mask]
        kp_mags = magnitude[keypoints_mask]

        mean_magnitude = float(np.mean(kp_mags))
        if mean_magnitude <= 0.0:
            return 0.0

        kp_rad = np.radians(kp_angles)
        c_bar = np.mean(np.cos(kp_rad))
        s_bar = np.mean(np.sin(kp_rad))
        variancia_circular = 1.0 - np.sqrt(c_bar**2 + s_bar**2)

        counts, _ = np.histogram(kp_angles, bins=36, range=(0, 360))
        min_idx = np.argmin(counts)
        counts_rot = np.roll(counts, -min_idx)

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

        kurt1 = kurtosis(regiao1, fisher=False)
        kurt2 = kurtosis(regiao2, fisher=False)
        skew1 = skew(regiao1)
        skew2 = skew(regiao2)

        diferenca_curtose = abs((kurt1 + kurt2) - 3.0)
        diferenca_assimetria = abs(skew1 - skew2)

        evaluation_value = ((diferenca_curtose - diferenca_assimetria) / mean_magnitude) * variancia_circular * 100.0
        return max(0.0, float(evaluation_value))

    def _criar_cabecalho(self, params, total_fotos, inicio):
        linhas = [
            "=" * 90,
            self.tr("LAUDO TECNICO DE FISCALIZACAO: NITIDEZ E DETECCAO DE ARRASTO (MOTION BLUR)"),
            self.tr(f"Data/Hora de Inicio: {inicio.strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 90,
            self.tr("PARAMETROS DE AUDITORIA:"),
            f"  • Diretorio Alvo: {params['pasta']}",
            f"  • Volume de Fotografias Auditadas: {total_fotos}",
            f"  • Limite Critico de Reprovacao (Evaluation Value): {params['limiar_critico']:.2f}",
            f"  • Fundamentacao Metodologica: Estatistica Direcional com Keypoints (Takahashi et al., 2020)",
            f"  • Procedimento de Amostragem: Grade Regular 3x3 de Crops (512x512) com Agregacao Trimmean",
            "=" * 90,
            ""
        ]
        return "\n".join(linhas)

    def _criar_painel_reprovadas(self, resultados, limiar):
        inconformes = [r for r in resultados if r['inconforme']]
        linhas = [
            "-" * 90,
            self.tr("PAINEL DE TRIAGEM PRELIMINAR: FOTOGRAFIAS REPROVADAS E INCONSISTENCIAS"),
            f"Total de Ocorrencias Nao Conformes: {len(inconformes)} fotografia(s)",
            "-" * 90,
        ]

        if not inconformes:
            linhas.append(self.tr("  CONFORME: Nenhuma fotografia apresentou indice de arrasto superior ao limite."))
        else:
            linhas.append(f" {'FOTOGRAFIA AEREA':<45} | {'EVAL VALUE':<12} | {'STATUS':<25}")
            linhas.append("-" * 90)
            for r in inconformes:
                eval_str = f"{r['eval']:7.3f}" if r['eval'] >= 0 else "    ---   "
                linhas.append(f" {r['foto']:<45} | {eval_str:<12} | {r['status']}")

        linhas.extend(["", ""])
        return "\n".join(linhas)

    def _criar_painel_todas(self, resultados):
        linhas = [
            "-" * 90,
            self.tr("REGISTRO EXAUSTIVO DE TODAS AS FOTOGRAFIAS ANALISADAS"),
            "-" * 90,
            f" {'FOTOGRAFIA AEREA':<45} | {'EVAL VALUE':<12} | {'STATUS':<25}",
            "-" * 90
        ]

        for r in resultados:
            eval_str = f"{r['eval']:7.3f}" if r['eval'] >= 0 else "    ---   "
            linhas.append(f" {r['foto']:<45} | {eval_str:<12} | {r['status']}")

        linhas.extend(["", ""])
        return "\n".join(linhas)

    def _criar_rodape(self, total, aprovadas, reprovadas, corrompidas):
        linhas = [
            "=" * 90,
            self.tr("SINTESE ESTATISTICA CONSOLIDADA:"),
            f"  • Total de Fotografias no Lote: {total}",
            f"  • Fotografias Conformes (Nitidas): {aprovadas} ({(aprovadas/total*100 if total else 0):.2f}%)",
            f"  • Fotografias Reprovadas por Arrasto: {reprovadas} ({(reprovadas/total*100 if total else 0):.2f}%)",
            f"  • Fotografias com Inconsistencia de I/O ou Arquivo: {corrompidas} ({(corrompidas/total*100 if total else 0):.2f}%)",
            "=" * 90,
            self.tr(f"Data/Hora de Conclusao: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 90
        ]
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho_saida, buffer):
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(self.tr(f"Erro ao salvar laudo de auditoria: {str(e)}"))