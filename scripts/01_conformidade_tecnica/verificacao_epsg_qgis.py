# -*- coding: utf-8 -*-

"""
Plugin QGIS para Verificação de Conformidade de Sistema de Referência (EPSG)

Este algoritmo realiza a varredura recursiva em pastas para validar se as imagens 
fotogramétricas (TIFF/GeoTIFF) possuem o sistema de referência de coordenadas (CRS) 
especificado pelo usuário. Esta é uma etapa crucial do Controle de Qualidade 
Integrado (CQI) para evitar a propagação de erros posicionais.

Baseado nas normativas de qualidade cartográfica (ET-EDGV) citadas no Projeto 
de Mestrado de Eliza Silva Maia (UFBA).

Cálculos:
    - Extração de metadados via GDAL (osgeo).
    - Comparação de Authority ID (EPSG) entre o arquivo e o parâmetro alvo.

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 22/04/2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QCoreApplication
import os
from osgeo import gdal, osr
from datetime import datetime


class VerificacaoEpsgImagens(QgsProcessingAlgorithm):
    """
    Algoritmo de auditoria de EPSG para imagens brutas.
    """

    # Constantes de Parâmetros
    INPUT_FOLDER = 'INPUT_FOLDER'
    TARGET_CRS = 'TARGET_CRS'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return VerificacaoEpsgImagens()

    def name(self):
        return 'verificacao_epsg_fotos'

    def displayName(self):
        return self.tr("Fotos Brutas - Imagem - Sistema de Referência (EPSG)")

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        return self.tr("Varre pastas e subpastas em busca de arquivos TIFF/GeoTIFF, "
                       "verificando se o EPSG corresponde ao sistema alvo definido.")

    def initAlgorithm(self, config=None):
        """
        Define a interface de entrada e saída.
        """
        # ======================================
        # INICIALIZAÇÃO DE PARÂMETROS
        # ======================================

        # Pasta de Entrada
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Selecione a pasta raiz das imagens"),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # EPSG Alvo (Lista do QGIS)
        self.addParameter(
            QgsProcessingParameterCrs(
                self.TARGET_CRS,
                self.tr("Sistema de Referência (CRS) esperado"),
                defaultValue='EPSG:4674'  # SIRGAS 2000 como padrão
            )
        )

        # Arquivo de Saída (.txt)
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
        pasta_raiz = self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        crs_alvo_obj = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # Extrair apenas o código numérico (ex: 4674)
        epsg_alvo = crs_alvo_obj.postgisSrid()

        # Coleta de arquivos
        arquivos_tiff = self._listar_arquivos_tiff(pasta_raiz)
        total_arquivos = len(arquivos_tiff)

        if total_arquivos == 0:
            raise QgsProcessingException(self.tr("Nenhum arquivo TIFF encontrado na pasta informada."))

        feedback.pushInfo(f"Iniciando verificação em {total_arquivos} arquivos...")

        # Estruturas de dados para o relatório
        resultados = {
            'corretos': [],
            'divergentes': [],
            'sem_crs': [],
            'erros': []
        }

        # Loop de processamento com tratamento de erros (Try/Except)
        for i, caminho in enumerate(arquivos_tiff):
            if feedback.isCanceled():
                break

            try:
                # Logica de verificação
                status, info = self._verificar_epsg_imagem(caminho, epsg_alvo)
                
                if status == 'CORRETO':
                    resultados['corretos'].append(caminho)
                elif status == 'DIVERGENTE':
                    resultados['divergentes'].append({'path': caminho, 'encontrado': info})
                elif status == 'SEM_CRS':
                    resultados['sem_crs'].append(caminho)
                
            except Exception as e:
                feedback.reportError(f"Falha crítica no arquivo {caminho}: {str(e)}")
                resultados['erros'].append({'path': caminho, 'msg': str(e)})

            # Atualiza barra de progresso
            feedback.setProgress(int((i / total_arquivos) * 100))

        # Geração e Escrita do Relatório
        conteudo_relatorio = self._gerar_conteudo_relatorio(
            pasta_raiz, epsg_alvo, resultados, total_arquivos
        )
        self._escrever_relatorio(caminho_relatorio, conteudo_relatorio)

        feedback.pushInfo(f"Relatório gerado com sucesso em: {caminho_relatorio}")

        return {self.OUTPUT_REPORT: caminho_relatorio}

    # ======================================
    # MÉTODOS AUXILIARES PRIVADOS
    # ======================================

    def _listar_arquivos_tiff(self, pasta):
        """Varre recursivamente a pasta em busca de extensões TIFF."""
        lista = []
        for raiz, _, arquivos in os.walk(pasta):
            for arquivo in arquivos:
                if arquivo.lower().endswith(('.tif', '.tiff', '.geotiff')):
                    lista.append(os.path.join(raiz, arquivo))
        return lista

    def _verificar_epsg_imagem(self, caminho, epsg_alvo):
        """Abre a imagem via GDAL e valida o EPSG."""
        dataset = gdal.Open(caminho, gdal.GA_ReadOnly)
        if not dataset:
            raise Exception("Não foi possível abrir o arquivo via GDAL.")

        proj_wkt = dataset.GetProjection()
        dataset = None  # Fecha o arquivo

        if not proj_wkt:
            return 'SEM_CRS', None

        srs = osr.SpatialReference()
        srs.ImportFromWkt(proj_wkt)
        
        # Tenta recuperar o código EPSG (Authority ID)
        epsg_encontrado = srs.GetAttrValue("AUTHORITY", 1)

        if epsg_encontrado and int(epsg_encontrado) == epsg_alvo:
            return 'CORRETO', epsg_encontrado
        else:
            return 'DIVERGENTE', epsg_encontrado if epsg_encontrado else "Desconhecido"

    def _gerar_conteudo_relatorio(self, pasta, alvo, res, total):
        """Formata o texto final do relatório conforme padrões de auditoria."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        linhas = [
            "==========================================================================",
            "        RELATÓRIO DE AUDITORIA TÉCNICA - CONFORMIDADE DE EPSG",
            "==========================================================================",
            f"Data de Execução: {agora}",
            f"Pasta Analisada:  {pasta}",
            f"EPSG Esperado:    EPSG:{alvo}",
            f"Total de Arquivos: {total}",
            "--------------------------------------------------------------------------\n",
            "RESUMO DA VALIDAÇÃO:",
            f"  - Corretos:      {len(res['corretos'])}",
            f"  - Divergentes:   {len(res['divergentes'])}",
            f"  - Sem CRS:       {len(res['sem_crs'])}",
            f"  - Falhas Leitura: {len(res['erros'])}",
            "\n==========================================================================",
            "DETALHAMENTO DOS ALERTAS E ERROS",
            "=========================================================================="
        ]

        if res['divergentes']:
            linhas.append("\n[!] ARQUIVOS COM EPSG DIVERGENTE:")
            for item in res['divergentes']:
                linhas.append(f"  - {item['path']} | Encontrado: {item['encontrado']}")

        if res['sem_crs']:
            linhas.append("\n[!] ARQUIVOS SEM SISTEMA DE COORDENADAS DEFINIDO:")
            for item in res['sem_crs']:
                linhas.append(f"  - {item['path']}")

        if res['erros']:
            linhas.append("\n[!] ERROS DE PROCESSAMENTO (ARQUIVOS CORROMPIDOS OU BLOQUEADOS):")
            for item in res['erros']:
                linhas.append(f"  - {item['path']} | Erro: {item['msg']}")

        if not res['divergentes'] and not res['sem_crs'] and not res['erros']:
            linhas.append("\n✓ SUCESSO: Todos os arquivos estão em conformidade com o EPSG alvo.")

        linhas.append("\n--------------------------------------------------------------------------")
        linhas.append("Fim do Relatório.")
        
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho, conteudo):
        """Salva a string do relatório no arquivo físico."""
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(conteudo)