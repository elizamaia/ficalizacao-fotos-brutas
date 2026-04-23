# -*- coding: utf-8 -*-

"""
Plugin QGIS para Verificação de Conformidade Espectral (Bandas)

Este algoritmo realiza a varredura em diretórios para validar a conformidade 
radiométrica de imagens aerofotogramétricas brutas (TIFF/GeoTIFF). O processo
verifica se a quantidade de bandas do raster corresponde ao produto contratado 
(ex: RGB ou RGIR), identificando falhas de composição, arquivos corrompidos e 
arquivos intrusos (extensões não permitidas).

Baseado nas normativas de qualidade cartográfica (ET-EDGV) citadas no Projeto 
de Mestrado de Eliza Silva Maia (UFBA).

Cálculos/Regras:
    - Extração do RasterCount via GDAL.
    - Comparação com o parâmetro de bandas exigidas.
    - Filtro de extensões válidas e auxiliares.

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 23/04/2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
import os
from osgeo import gdal
from datetime import datetime


class ConformidadeEspectralBandas(QgsProcessingAlgorithm):
    """
    Algoritmo de auditoria de bandas e conformidade radiométrica de imagens.
    """

    # Constantes de Parâmetros
    INPUT_FOLDER = 'INPUT_FOLDER'
    COMPOSITION_TYPE = 'COMPOSITION_TYPE'
    EXPECTED_BANDS = 'EXPECTED_BANDS'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # Opções do Enum
    COMPOSITIONS = ['RGB', 'RGIR']

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConformidadeEspectralBandas()

    def name(self):
        return 'verificacao_bandas_fotos'

    def displayName(self):
        return self.tr("Fotos Brutas - Imagem - Conformidade Espectral (Bandas)")

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        return self.tr("Varre pastas de imagens e valida se a quantidade de bandas "
                       "espectrais corresponde à composição exigida (RGB ou RGIR), "
                       "identificando arquivos corrompidos e intrusos.")

    def initAlgorithm(self, config=None):
        """
        Define a interface de entrada e saída.
        """
        # ======================================
        # INICIALIZAÇÃO DE PARÂMETROS
        # ======================================

        # 1. Pasta de Entrada
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Selecione a pasta raiz das imagens"),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # 2. Tipo de Composição Esperada (Dropdown)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.COMPOSITION_TYPE,
                self.tr("Composição Esperada"),
                options=self.COMPOSITIONS,
                defaultValue=1  # Padrão: RGIR
            )
        )

        # 3. Quantidade de Bandas Exigidas
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EXPECTED_BANDS,
                self.tr("Quantidade de Bandas Exigidas"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=4,
                minValue=1,
                maxValue=10
            )
        )

        # 4. Arquivo de Saída (.txt)
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr("Caminho para o Relatório de Auditoria (.txt)"),
                fileFilter='Text files (*.txt)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Execução central do processamento.
        """
        # Recuperar parâmetros
        pasta_raiz = self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        idx_comp = self.parameterAsEnum(parameters, self.COMPOSITION_TYPE, context)
        composicao = self.COMPOSITIONS[idx_comp]
        bandas_esperadas = self.parameterAsInt(parameters, self.EXPECTED_BANDS, context)
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # Configurar GDAL para lançar exceções capturáveis
        gdal.UseExceptions()

        # Estruturas para armazenar os resultados
        resultados = {
            'corretos': [],
            'erro_banda': [],
            'corrompidos': [],
            'intrusos': []
        }

        # Extensões mapeadas
        ext_imagem = ('.tif', '.tiff', '.geotif', '.geotiff')
        ext_auxiliar = ('.aux', '.tfw', '.xml', '.db', '.ini', '.prj', '.ovr', '.cpg')

        # Listar todos os arquivos da pasta e subpastas
        todos_arquivos = self._listar_todos_arquivos(pasta_raiz)
        total_arquivos = len(todos_arquivos)

        if total_arquivos == 0:
            raise QgsProcessingException(self.tr("Nenhum arquivo encontrado na pasta informada."))

        feedback.pushInfo(f"Iniciando verificação de {total_arquivos} arquivos...")

        # Loop de processamento
        for i, caminho_completo in enumerate(todos_arquivos):
            if feedback.isCanceled():
                break

            extensao = os.path.splitext(caminho_completo)[1].lower()

            # Lógica de Separação
            if extensao in ext_imagem:
                try:
                    status, msg = self._verificar_radiometria(caminho_completo, bandas_esperadas)
                    if status == 'CORRETO':
                        resultados['corretos'].append(caminho_completo)
                    elif status == 'ERRO_BANDA':
                        resultados['erro_banda'].append({'path': caminho_completo, 'msg': msg})
                except Exception as e:
                    # Captura erros do GDAL ou de leitura
                    mensagem_erro = str(e).strip()
                    feedback.reportError(f"Arquivo corrompido: {caminho_completo} ({mensagem_erro})")
                    resultados['corrompidos'].append({'path': caminho_completo, 'msg': mensagem_erro})

            elif extensao not in ext_auxiliar:
                resultados['intrusos'].append(caminho_completo)

            # Atualiza barra de progresso
            feedback.setProgress(int((i / total_arquivos) * 100))

        # Geração e Escrita do Relatório
        conteudo_relatorio = self._gerar_conteudo_relatorio(
            pasta_raiz, composicao, bandas_esperadas, resultados
        )
        self._escrever_relatorio(caminho_relatorio, conteudo_relatorio)

        feedback.pushInfo(f"Relatório gerado com sucesso em: {caminho_relatorio}")

        return {self.OUTPUT_REPORT: caminho_relatorio}

    # ======================================
    # MÉTODOS AUXILIARES PRIVADOS
    # ======================================

    def _listar_todos_arquivos(self, pasta):
        """Varre recursivamente a pasta e retorna todos os arquivos encontrados."""
        lista = []
        for raiz, _, arquivos in os.walk(pasta):
            for arquivo in arquivos:
                lista.append(os.path.join(raiz, arquivo))
        return lista

    def _verificar_radiometria(self, caminho, bandas_esperadas):
        """Abre a imagem via GDAL e valida a quantidade de bandas."""
        dataset = gdal.Open(caminho, gdal.GA_ReadOnly)
        
        if not dataset:
            raise Exception("Erro desconhecido ao abrir via GDAL.")

        quantidade_bandas = dataset.RasterCount
        dataset = None  # Libera a memória fechando o dataset

        if quantidade_bandas == 0:
            raise Exception("RasterCount = 0 (Arquivo sem dados de imagem válidos).")

        if quantidade_bandas == bandas_esperadas:
            return 'CORRETO', None
        else:
            return 'ERRO_BANDA', f"Possui {quantidade_bandas} banda(s), esperado {bandas_esperadas}."

    def _gerar_conteudo_relatorio(self, pasta, composicao, bandas, res):
        """Formata o texto final do relatório com marcadores de auditoria."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        total_imagens_lidas = len(res['corretos']) + len(res['erro_banda']) + len(res['corrompidos'])
        
        linhas = [
            "==========================================================================",
            "        RELATÓRIO DE AUDITORIA TÉCNICA - CONFORMIDADE ESPECTRAL",
            "==========================================================================",
            f"Data de Execução:    {agora}",
            f"Pasta Analisada:     {pasta}",
            f"Composição Exigida:  {composicao} ({bandas} Bandas)",
            f"Imagens Lidas (TIF): {total_imagens_lidas}",
            "--------------------------------------------------------------------------\n",
            "RESUMO DA VALIDAÇÃO:",
            f"  - Corretas:               {len(res['corretos'])}",
            f"  - Falhas de Composição:   {len(res['erro_banda'])}",
            f"  - Arquivos Corrompidos:   {len(res['corrompidos'])}",
            f"  - Arquivos Intrusos:      {len(res['intrusos'])}",
            "\n==========================================================================",
            "DETALHAMENTO DOS ALERTAS E ERROS",
            "=========================================================================="
        ]

        if res['erro_banda']:
            linhas.append("\n[!] FALHAS DE COMPOSIÇÃO RADIOMÉTRICA (Nº DE BANDAS INCORRETO):")
            for item in res['erro_banda']:
                linhas.append(f"  - {item['path']}\n    Problema: {item['msg']}")

        if res['corrompidos']:
            linhas.append("\n[!] ARQUIVOS CORROMPIDOS OU ILEGÍVEIS:")
            for item in res['corrompidos']:
                linhas.append(f"  - {item['path']}\n    Problema: {item['msg']}")

        if res['intrusos']:
            linhas.append("\n[!] ARQUIVOS INTRUSOS (EXTENSÕES NÃO PERMITIDAS):")
            for item in res['intrusos']:
                linhas.append(f"  - {item}")

        if not res['erro_banda'] and not res['corrompidos'] and not res['intrusos']:
            linhas.append("\n✓ SUCESSO: Todas as imagens estão corretas e o diretório está limpo.")

        linhas.append("\n--------------------------------------------------------------------------")
        linhas.append("Fim do Relatório.")
        
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho, conteudo):
        """Salva a string do relatório no arquivo físico com codificação correta."""
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(conteudo)