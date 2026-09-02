# -*- coding: utf-8 -*-
"""
Plugin QGIS para Detecção de Arrasto (Motion Blur) em Fotografias Aéreas Brutas
com Extração de Keypoints, Leitura por Janela (Big Earth Data) e Relatório Hierárquico.

Estrutura do Laudo Técnico:
    1. Parâmetros de Configuração e Metadados da Auditoria
    2. Painel de Triagem Imediata: Apenas Fotografias Reprovadas e Inconsistentes
    3. Detalhamento Integral: Listagem Sequencial de Todas as Fotografias
    4. Síntese Estatística Consolidada

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
        return self.tr('Fotos Brutas - Imagem - Arrasto (Triagem Executiva)')

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
                self.tr('Limite de Avaliação para Reprovação (Evaluation Value)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.30,
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
                    status = "[!] REPROVADO (ARRASTO DETECTADO)"
                    is_inconforme = True
                    total_reprovadas += 1
                else:
                    status = "✓ APROVADO (NÍTIDO)"
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
                msg_falha = f"[!] REPROVADO (ARQUIVO CORROMPIDO / ERRO I/O: {str(e)[:50]})"
                feedback.reportError(self.tr(f"Falha física no arquivo {nome_arquivo}: {str(e)}"))

                resultados.append({
                    'foto': nome_arquivo,
                    'eval': -1.0,
                    'status': msg_falha,
                    'inconforme': True,
                    'erro': True
                })

            if i % 100 == 0:
                gc.collect()

        # Montagem do relatório completo
        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, total_arquivos, inicio_processamento))
        buffer_relatorio.append(self._criar_painel_reprovadas(resultados, params['limiar_critico']))
        buffer_relatorio.append(self._criar_painel_todas(resultados))
        buffer_relatorio.append(self._criar_rodape(total_arquivos, total_aprovadas, total_reprovadas, total_corrompidas))

        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(
            self.tr(f"✓ Auditoria concluída: {total_arquivos} fotos | Aprovadas: {total_aprovadas} | Reprovadas: {total_reprovadas} | Falhas I/O: {total_corrompidas}")
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
            raise QgsProcessingException(self.tr("A pasta informada é inválida ou inacessível."))
        if params['limiar_critico'] <= 0:
            raise QgsProcessingException(self.tr("O limite de avaliação deve ser superior a zero."))

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
                raise IOError("GDAL não conseguiu obter descritor do arquivo.")

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
            raise ValueError("Dimensões insuficientes ou falha na leitura dos crops.")

        if len(valores_crops) > 2:
            eval_final = trim_mean(valores_crops, proportiontocut=1.0 / len(valores_crops))
        else:
            eval_final = np.mean(valores_crops)

        return float(eval_final)

    def _calcular_takahashi_crop(self, img_crop):
        # 1. Normalização Radiométrica Direta (16-bit para escala de 8-bit)
        if img_crop.dtype == np.uint16 or img_crop.max() > 255:
            img_crop_norm = img_crop.astype(float) / 256.0
        else:
            img_crop_norm = img_crop.astype(float)

        # 2. Convolução de Sobel 5x5
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

        # 3. Extração de Keypoints (Máximos Locais com Magnitude > 1.0)
        local_max = maximum_filter(img_crop_norm, size=5)
        keypoints_mask = (img_crop_norm == local_max) & (magnitude > 1.0)

        if np.count_nonzero(keypoints_mask) < 30:
            return 0.0

        kp_angles = direcao_deg[keypoints_mask]
        kp_mags = magnitude[keypoints_mask]

        mean_magnitude = float(np.mean(kp_mags))
        if mean_magnitude <= 0.0:
            return 0.0

        # 4. Variância Circular dos Keypoints
        kp_rad = np.radians(kp_angles)
        c_bar = np.mean(np.cos(kp_rad))
        s_bar = np.mean(np.sin(kp_rad))
        variancia_circular = 1.0 - np.sqrt(c_bar**2 + s_bar**2)

        # 5. Histograma Angular (36 bins)
        counts, _ = np.histogram(kp_angles, bins=36, range=(0, 360))
        min_idx = np.argmin(counts)
        counts_rot = np.roll(counts, -min_idx)

        # 6. Partição de Otsu
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

        # 7. Momentos Estatísticos (Curtose e Assimetria)
        kurt1 = kurtosis(regiao1, fisher=False)
        kurt2 = kurtosis(regiao2, fisher=False)
        skew1 = skew(regiao1)
        skew2 = skew(regiao2)

        diferenca_curtose = abs((kurt1 + kurt2) - 3.0)
        diferenca_assimetria = abs(skew1 - skew2)

        # 8. Métrica Final
        evaluation_value = ((diferenca_curtose - diferenca_assimetria) / mean_magnitude) * variancia_circular * 100.0
        return max(0.0, float(evaluation_value))

    def _criar_cabecalho(self, params, total_fotos, inicio):
        linhas = [
            "=" * 90,
            self.tr("LAUDO DE FISCALIZAÇÃO CARTOGRÁFICA: NITIDEZ E BORRAMENTO POR MOVIMENTO (ARRASTO)"),
            self.tr(f"Data/Hora de Início: {inicio.strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 90,
            self.tr("PARÂMETROS DA AUDITORIA:"),
            f"  • Diretório Alvo: {params['pasta']}",
            f"  • Volume Total de Fotografias Identificadas: {total_fotos}",
            f"  • Limite Crítico de Reprovação (Evaluation Value): {params['limiar_critico']:.2f}",
            f"  • Metodologia: Estatística Direcional com Keypoints (Takahashi et al., 2020; Maia et al., 2026)",
            f"  • Amostragem Espacial: Grade Regular 3x3 de Crops (512x512) com Agregação Trimmean",
            "=" * 90,
            ""
        ]
        return "\n".join(linhas)

    def _criar_painel_reprovadas(self, resultados, limiar):
        inconformes = [r for r in resultados if r['inconforme']]
        linhas = [
            "!" * 90,
            self.tr("PAINEL DE TRIAGEM RÁPIDA: FOTOGRAFIAS REPROVADAS / INCONSISTENTES"),
            f"Total de Ocorrências com Inconformidade: {len(inconformes)} fotografia(s)",
            "!" * 90,
        ]

        if not inconformes:
            linhas.append(self.tr("  ✓ NENHUMA FOTOGRAFIA REPROVADA. Todas as imagens auditadas cumprem o critério de nitidez."))
        else:
            linhas.append(f" {'FOTOGRAFIA AÉREA':<45} | {'EVAL VALUE':<12} | {'DIAGNÓSTICO':<25}")
            linhas.append("-" * 90)
            for r in inconformes:
                eval_str = f"{r['eval']:7.3f}" if r['eval'] >= 0 else "    ---   "
                linhas.append(f" {r['foto']:<45} | {eval_str:<12} | {r['status']}")

        linhas.extend(["", ""])
        return "\n".join(linhas)

    def _criar_painel_todas(self, resultados):
        linhas = [
            "-" * 90,
            self.tr("DETALHAMENTO INTEGRAL DE TODAS AS FOTOGRAFIAS AUDITADAS"),
            "-" * 90,
            f" {'FOTOGRAFIA AÉREA':<45} | {'EVAL VALUE':<12} | {'STATUS':<25}",
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
            self.tr("SÍNTESE ESTATÍSTICA CONSOLIDADA:"),
            f"  • Fotografias Auditadas no Lote: {total}",
            f"  • Fotografias Conformes (Nítidas): {aprovadas} ({(aprovadas/total*100 if total else 0):.2f}%)",
            f"  • Fotografias com Arrasto Detectado: {reprovadas} ({(reprovadas/total*100 if total else 0):.2f}%)",
            f"  • Fotografias Inconsistentes (Falha de I/O / Corrompidas): {corrompidas} ({(corrompidas/total*100 if total else 0):.2f}%)",
            "=" * 90,
            self.tr(f"Data/Hora de Conclusão: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 90
        ]
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho_saida, buffer):
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(self.tr(f"Erro ao salvar laudo de auditoria: {str(e)}"))