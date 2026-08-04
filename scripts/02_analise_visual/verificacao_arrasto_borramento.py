# -*- coding: utf-8 -*-
"""
Plugin QGIS para Detecção de Arrasto (Motion Blur) em Fotografias Aéreas Brutas

Este algoritmo processa arquivos GeoTIFF e gera um relatório de controle de 
qualidade baseado na metodologia de estatística direcional do gradiente de 
Sobel (Takahashi et al., 2020) para detectar anomalias visuais de arrasto.

Cálculos:
    - Normalização: Escalonamento radiométrico de 16 bits para 8 bits na memória.
    - Avaliação: Extração de amostras 3x3, convolução de Sobel 5x5, variância 
      circular e partição de Otsu.
    - Agregação: Média Aparada (Trimmean).

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
from scipy.ndimage import convolve
from osgeo import gdal
import os
import glob
from datetime import datetime


class DetectorArrastoTakahashi(QgsProcessingAlgorithm):
    """
    Algoritmo de análise quantitativa de arrasto em fotografias aéreas brutas.

    Este processador avalia múltiplos arquivos TIFF/GeoTIFF, extrai recortes 
    de amostragem e valida a nitidez contra limites de qualidade (Evaluation Value)
    especificados pelo usuário.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    # Entrada e Saída
    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # Limites de Qualidade
    EVALUATION_THRESHOLD = 'EVALUATION_THRESHOLD'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================

    def tr(self, string):
        """
        Traduz string usando o sistema de internacionalização do QGIS.

        Args:
            string (str): String a ser traduzida

        Returns:
            str: String traduzida para o idioma atual do QGIS
        """
        return QCoreApplication.translate('DetectorArrastoTakahashi', string)

    def createInstance(self):
        """Cria uma nova instância do algoritmo."""
        return DetectorArrastoTakahashi()

    def name(self):
        """Retorna o identificador único do algoritmo."""
        return 'detector_arrasto_takahashi'

    def displayName(self):
        """Retorna o nome exibido do algoritmo."""
        return self.tr('Fotos Brutas - Imagem - Arrasto')

    def group(self):
        """Retorna o grupo do algoritmo."""
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        """Retorna o ID do grupo."""
        return 'fiscalizacao_sei'

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================

    def initAlgorithm(self, config=None):
        """
        Inicializa os parâmetros do algoritmo.

        Define 3 parâmetros organizados em 3 categorias:
        1. Arquivos (pasta de entrada)
        2. Limites de qualidade
        3. Arquivo de saída
        """
        # --------------------------------------------------------------------
        # 1. ARQUIVOS (PASTA DE ENTRADA)
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com as Fotografias Aéreas Brutas (.tif / .tiff)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # --------------------------------------------------------------------
        # 2. LIMITES DE QUALIDADE
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EVALUATION_THRESHOLD,
                self.tr('Limite de Avaliação para Reprovação (Evaluation Value)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.1
            )
        )

        # --------------------------------------------------------------------
        # 3. ARQUIVO DE SAÍDA
        # --------------------------------------------------------------------
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
        """
        Executa o algoritmo de detecção quantitativa de arrasto.

        Args:
            parameters: Dicionário de parâmetros do QGIS
            context: Contexto de processamento do QGIS
            feedback: Objeto de feedback para progresso e mensagens

        Returns:
            dict: Dicionário com o caminho do arquivo de saída
        """
        # --------------------------------------------------------------------
        # RECUPERAÇÃO E VALIDAÇÃO DE PARÂMETROS
        # --------------------------------------------------------------------
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params, feedback)
        
        gdal.UseExceptions()

        # --------------------------------------------------------------------
        # LISTA DE ARQUIVOS PARA PROCESSAMENTO
        # --------------------------------------------------------------------
        lista_arquivos = self._listar_arquivos(params['pasta'], feedback)

        # --------------------------------------------------------------------
        # INICIALIZAÇÃO DO RELATÓRIO
        # --------------------------------------------------------------------
        total_arquivos = len(lista_arquivos)
        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, total_arquivos))

        resultados_fotos = []

        # --------------------------------------------------------------------
        # PROCESSAMENTO DOS ARQUIVOS
        # --------------------------------------------------------------------
        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            nome_arquivo = os.path.basename(caminho_arquivo)
            feedback.setProgress(int((i / total_arquivos) * 100))

            try:
                # Processar arquivo individual
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

        # --------------------------------------------------------------------
        # MONTAGEM E ESCRITA DO RELATÓRIO FINAL
        # --------------------------------------------------------------------
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
        """
        Recupera e organiza os parâmetros do algoritmo.

        Returns:
            dict: Dicionário com todos os parâmetros organizados
        """
        return {
            'pasta': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'limiar_critico': self.parameterAsDouble(parameters, self.EVALUATION_THRESHOLD, context),
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context)
        }

    def _validar_parametros(self, params, feedback):
        """
        Valida os parâmetros de entrada.

        Args:
            params (dict): Dicionário de parâmetros
            feedback: Objeto de feedback do QGIS

        Raises:
            QgsProcessingException: Se validação falhar
        """
        if not params['pasta'] or not os.path.exists(params['pasta']):
            raise QgsProcessingException(
                self.tr("A pasta de imagens informada é inválida ou não existe.")
            )

        if params['limiar_critico'] <= 0:
            raise QgsProcessingException(
                self.tr("O limite de avaliação deve ser maior que zero.")
            )

    def _listar_arquivos(self, pasta, feedback):
        """
        Lista todos os arquivos válidos na pasta.

        Args:
            pasta (str): Caminho da pasta
            feedback: Objeto de feedback do QGIS

        Returns:
            list: Lista de caminhos de arquivos

        Raises:
            QgsProcessingException: Se nenhum arquivo encontrado
        """
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
        """
        Abre a imagem, extrai amostragem em grade e calcula a agregação Trimmean.

        Args:
            caminho_foto (str): Caminho absoluto da imagem
            feedback: Objeto de feedback

        Returns:
            float: Valor final de avaliação
        """
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
        Calcula o Evaluation Value de um crop, aplicando normalização 16 bits para 8 bits.

        Args:
            img_crop (np.array): Matriz 512x512 bruta

        Returns:
            float: Valor de avaliação para o recorte
        """
        # ----------------------------------------------------------------
        # NORMALIZAÇÃO RADIOMÉTRICA (16-bit -> 8-bit dinâmico)
        # ----------------------------------------------------------------
        min_val, max_val = img_crop.min(), img_crop.max()
        if max_val > min_val:
            img_crop_norm = ((img_crop.astype(float) - min_val) / (max_val - min_val) * 255.0)
        else:
            img_crop_norm = img_crop.astype(float)

        # ----------------------------------------------------------------
        # CÁLCULO DE MÉTRICAS (SOBEL 5x5)
        # ----------------------------------------------------------------
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
        mean_magnitude = np.mean(magnitude)

        if mean_magnitude == 0:
            return 0.0

        direcao_rad = np.arctan2(gV, gH)
        direcao_deg = np.degrees(direcao_rad) % 360

        c_bar = np.mean(np.cos(direcao_rad))
        s_bar = np.mean(np.sin(direcao_rad))
        variancia_circular = 1.0 - np.sqrt(c_bar**2 + s_bar**2)

        counts, _ = np.histogram(direcao_deg, bins=36, range=(0, 360))

        min_idx = np.argmin(counts)
        counts_rot = np.roll(counts, -min_idx)

        best_var = -1
        best_t = 18
        total_bins = len(counts_rot)
        
        for t in range(1, total_bins):
            mean1 = np.mean(counts_rot[:t])
            mean2 = np.mean(counts_rot[t:])
            var_between = t * (total_bins - t) * (mean1 - mean2)**2
            
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

    def _criar_cabecalho(self, params, total_fotos):
        """
        Cria o cabeçalho do relatório de auditoria.

        Args:
            params (dict): Dicionário de parâmetros
            total_fotos (int): Quantidade de imagens

        Returns:
            str: Cabeçalho formatado
        """
        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE AVALIAÇÃO DE ARRASTO (MOTION BLUR)"),
            self.tr(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 80,
            self.tr("PARÂMETROS DE CONFIGURAÇÃO:"),
            f"  • Diretório: {params['pasta']}",
            f"  • Fotografias Auditadas: {total_fotos}",
            f"  • Limite de Reprovação (Evaluation Value): {params['limiar_critico']:.2f}",
            f"  • Amostragem: Grade 3x3 de Crops (512x512) com Trimmean",
            "=" * 80,
            ""
        ]

        return "\n".join(linhas)

    def _formatar_corpo_relatorio(self, resultados):
        """
        Formata os dados de resultados por imagem.

        Args:
            resultados (list): Lista de tuplas com os resultados processados

        Returns:
            str: Corpo do relatório formatado
        """
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
        """
        Escreve o relatório completo em arquivo.

        Args:
            caminho_saida (str): Caminho do arquivo de saída
            buffer (list): Buffer com linhas do relatório
        """
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(
                self.tr(f"Erro ao escrever arquivo de saída: {str(e)}")
            )