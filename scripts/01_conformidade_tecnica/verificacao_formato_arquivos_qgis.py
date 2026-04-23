# -*- coding: utf-8 -*-

"""
Plugin QGIS para Verificação de Consistência de Formato de Arquivos

Este algoritmo realiza uma varredura profunda no lote de imagens brutas para
garantir a consistência e integridade dos formatos entregues. Ele valida se as 
imagens (TIFF/GeoTIFF) estão íntegras e conseguem ser abertas, contabiliza 
arquivos auxiliares válidos (.xml, .tfw, etc.) e identifica arquivos intrusos 
(lixo de SO, projetos salvos erroneamente, extensões não permitidas).

Baseado nas normativas de qualidade cartográfica (ET-EDGV) citadas no Projeto 
de Mestrado de Eliza Silva Maia (UFBA), focado na Qualidade dos Anexos e 
Documentação.

Cálculos/Regras:
    - Filtro de extensões permitidas e auxiliares.
    - Teste de integridade de leitura raster via GDAL (verificação de corrupção).

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 23/04/2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
import os
from osgeo import gdal
from datetime import datetime


class ConsistenciaFormatoArquivos(QgsProcessingAlgorithm):
    """
    Algoritmo de auditoria de consistência de formato de arquivos e diretórios.
    """

    # Constantes de Parâmetros
    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsistenciaFormatoArquivos()

    def name(self):
        return 'verificacao_formato_fotos'

    def displayName(self):
        return self.tr("Fotos Brutas - Imagem - Consistência de Formato")

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        return self.tr("Varre o lote de imagens para identificar a conformidade do formato dos arquivos"
                       "(tiff ou geotiff arquivos corrompidos, contabilizar auxiliares válidos"
                       " e listar arquivos intrusos ou não permitidos no pacote de entrega."
                       )

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
                self.tr("Selecione a pasta raiz do lote de imagens"),
                behavior=QgsProcessingParameterFile.Folder
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
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # Configurar GDAL para lançar exceções
        gdal.UseExceptions()

        # Definição das extensões
        ext_imagem = ('.tif', '.tiff', '.geotif', '.geotiff')
        ext_auxiliar = ('.aux', '.tfw', '.tfwx', '.xml', '.db', '.ini', '.prj', '.ovr', '.cpg', '.jgw')

        # Estruturas de contagem e armazenamento
        resultados = {
            'total_tifs': 0,
            'total_auxiliares': 0,
            'pastas_lidas': 0,
            'corrompidos': [],
            'intrusos': []
        }

        # Listar estrutura de arquivos
        feedback.pushInfo("Mapeando a estrutura de diretórios...")
        lista_arquivos, resultados['pastas_lidas'] = self._mapear_diretorios(pasta_raiz)
        total_arquivos = len(lista_arquivos)

        if total_arquivos == 0:
            raise QgsProcessingException(self.tr("A pasta selecionada está vazia."))

        feedback.pushInfo(f"Iniciando auditoria de formato em {total_arquivos} arquivos...")

        # Loop de auditoria
        for i, caminho_completo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            extensao = os.path.splitext(caminho_completo)[1].lower()

            # CASO 1: É uma imagem TIFF
            if extensao in ext_imagem:
                resultados['total_tifs'] += 1
                try:
                    self._verificar_integridade_tif(caminho_completo)
                except Exception as e:
                    mensagem_erro = str(e).strip()
                    feedback.reportError(f"TIFF corrompido: {caminho_completo} ({mensagem_erro})")
                    resultados['corrompidos'].append({'path': caminho_completo, 'msg': mensagem_erro})

            # CASO 2: É um arquivo auxiliar válido
            elif extensao in ext_auxiliar:
                resultados['total_auxiliares'] += 1

            # CASO 3: É um formato não permitido (Intruso)
            else:
                resultados['intrusos'].append(caminho_completo)

            # Atualiza barra de progresso
            feedback.setProgress(int((i / total_arquivos) * 100))

        # Geração e Escrita do Relatório
        conteudo_relatorio = self._gerar_conteudo_relatorio(pasta_raiz, resultados)
        self._escrever_relatorio(caminho_relatorio, conteudo_relatorio)

        feedback.pushInfo(f"Relatório gerado com sucesso em: {caminho_relatorio}")

        return {self.OUTPUT_REPORT: caminho_relatorio}

    # ======================================
    # MÉTODOS AUXILIARES PRIVADOS
    # ======================================

    def _mapear_diretorios(self, pasta):
        """Varre a pasta, retornando a lista de arquivos e a contagem de subpastas."""
        lista_arquivos = []
        qtd_pastas = 0
        for raiz, dirs, arquivos in os.walk(pasta, followlinks=True):
            qtd_pastas += 1
            for arquivo in arquivos:
                lista_arquivos.append(os.path.join(raiz, arquivo))
        return lista_arquivos, qtd_pastas

    def _verificar_integridade_tif(self, caminho):
        """Tenta abrir o raster no GDAL para verificar se o arquivo está íntegro."""
        dataset = gdal.Open(caminho, gdal.GA_ReadOnly)
        if not dataset:
            raise Exception("O GDAL não conseguiu abrir o arquivo (dataset nulo).")
        
        if dataset.RasterCount == 0:
            dataset = None
            raise Exception("RasterCount = 0 (Arquivo sem bandas legíveis).")
            
        dataset = None # Fechar e liberar memória

    def _gerar_conteudo_relatorio(self, pasta, res):
        """Formata o relatório com estatísticas globais e listas de intrusos/erros."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        linhas = [
            "==========================================================================",
            "        RELATÓRIO DE AUDITORIA TÉCNICA - CONSISTÊNCIA DE FORMATO",
            "==========================================================================",
            f"Data de Execução: {agora}",
            f"Pasta Analisada:  {pasta}",
            "--------------------------------------------------------------------------\n",
            "ESTATÍSTICAS DO LOTE:",
            f"  - Pastas Verificadas:                  {res['pastas_lidas']}",
            f"  - Total de Imagens (TIF/GeoTIFF):      {res['total_tifs']}",
            f"  - Arquivos Auxiliares Válidos:         {res['total_auxiliares']}",
            "\n==========================================================================",
            "DETALHAMENTO DE ALARMES E INCONSISTÊNCIAS",
            "=========================================================================="
        ]

        # 1. Falta de imagens
        if res['total_tifs'] == 0:
            linhas.append("\n[!] FALHA CRÍTICA: Nenhuma imagem TIF/GeoTIFF encontrada no lote.")

        # 2. Arquivos Corrompidos
        if res['corrompidos']:
            linhas.append(f"\n[!] ARQUIVOS CORROMPIDOS OU ILEGÍVEIS ({len(res['corrompidos'])} encontrados):")
            for item in res['corrompidos']:
                linhas.append(f"  - {item['path']}\n    Erro: {item['msg']}")

        # 3. Arquivos Intrusos
        if res['intrusos']:
            linhas.append(f"\n[!] ARQUIVOS INTRUSOS / NÃO PERMITIDOS ({len(res['intrusos'])} encontrados):")
            for item in res['intrusos']:
                linhas.append(f"  - {item}")

        # Se tudo estiver perfeito
        if res['total_tifs'] > 0 and not res['corrompidos'] and not res['intrusos']:
            linhas.append("\n✓ SUCESSO: O lote está limpo, não possui intrusos e todos os TIFFs estão íntegros.")

        linhas.append("\n--------------------------------------------------------------------------")
        linhas.append("Fim do Relatório.")
        
        return "\n".join(linhas)

    def _escrever_relatorio(self, caminho, conteudo):
        """Salva a string do relatório no arquivo físico (UTF-8)."""
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(conteudo)