# -*- coding: utf-8 -*-
"""
Plugin QGIS para Fiscalização de Conformidade Radiométrica (Profundidade de Bits)

Este algoritmo realiza a varredura recursiva de imagens aéreas brutas (TIFF/GeoTIFF)
em um diretório e verifica se a profundidade de bits (BitsPerSample) atende ao
índice de qualidade estabelecido no projeto de aerolevantamento (ex.: 16 bits).

Contexto: Projeto de Mestrado - Eliza Silva Maia (PPEC/UFBA) - Etapa 1 (Conformidade Técnica)
Autor: Versão Refatorada (Padrão POO)
Data: 11/11/2026
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProcessingException
)
import os
from PIL import Image
from PIL.TiffTags import TAGS
from datetime import datetime


class VerificarBitsAlgoritmo(QgsProcessingAlgorithm):
    """
    Algoritmo para verificar a conformidade radiométrica (profundidade de bits)
    em lotes de fotografias aéreas brutas no formato TIFF/GeoTIFF.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    INPUT_FOLDER = 'INPUT_FOLDER'
    BITS_REFERENCIA = 'BITS_REFERENCIA'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    OPCOES_BITS = ['4', '8', '16', '32', '64']

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
        return QCoreApplication.translate('VerificarBitsAlgoritmo', string)

    def createInstance(self):
        """
        Cria uma nova instância do algoritmo.

        Returns:
            VerificarBitsAlgoritmo: Nova instância da classe.
        """
        return VerificarBitsAlgoritmo()

    def name(self):
        """
        Retorna o identificador único do algoritmo.

        Returns:
            str: Nome interno do algoritmo.
        """
        return 'fiscalizacao_profundidade_bits'

    def displayName(self):
        """
        Retorna o nome exibido do algoritmo na Caixa de Ferramentas.

        Returns:
            str: Nome de exibição traduzido.
        """
        return self.tr('Fotos Brutas - Imagem - Profundidade de Bits')

    def group(self):
        """
        Retorna o nome do grupo ao qual o algoritmo pertence.

        Returns:
            str: Nome do grupo traduzido.
        """
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        """
        Retorna o identificador único do grupo.

        Returns:
            str: ID do grupo.
        """
        return 'fiscalizacao_sei'

    def shortHelpString(self):
        """
        Retorna a descrição curta de ajuda exibida na interface da ferramenta.

        Returns:
            str: Texto explicativo do algoritmo.
        """
        return self.tr(
            "Verifica recursivamente se os arquivos TIFF/GeoTIFF em uma pasta "
            "possuem a profundidade de bits (conformidade radiométrica) esperada. "
            "Identifica arquivos não conformes ou corrompidos e gera um relatório "
            "de auditoria em formato TXT."
        )

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================

    def initAlgorithm(self, config=None):
        """
        Inicializa os parâmetros do algoritmo na interface do QGIS.

        Args:
            config (dict, optional): Configurações adicionais da API.
        """
        # --------------------------------------------------------------------
        # 1. ARQUIVOS DE ENTRADA
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Selecione a Pasta Mãe (Imagens TIFF/GeoTIFF)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # --------------------------------------------------------------------
        # 2. PARÂMETROS DE QUALIDADE RADIOMÉTRICA
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterEnum(
                self.BITS_REFERENCIA,
                self.tr('Profundidade de Bits Esperada'),
                options=self.OPCOES_BITS,
                defaultValue=2  # Padrão: 16 bits (índice 2)
            )
        )

        # --------------------------------------------------------------------
        # 3. ARQUIVO DE SAÍDA (RELATÓRIO TXT)
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Relatório de Auditoria em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    # =========================================================================
    # PROCESSAMENTO CENTRAL
    # =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        """
        Executa o fluxo principal de validação de profundidade de bits.

        Args:
            parameters (dict): Dicionário de parâmetros configurados pelo usuário.
            context (QgsProcessingContext): Contexto de processamento do QGIS.
            feedback (QgsProcessingFeedback): Objeto de comunicação e barra de progresso.

        Returns:
            dict: Dicionário contendo o caminho do relatório gerado.
        """
        Image.MAX_IMAGE_PIXELS = None

        # 1. Recuperação e validação de parâmetros
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params)

        # 2. Listagem de arquivos TIFF
        arquivos_tiff = self._listar_arquivos(params['pasta_mae'], feedback)
        total_arquivos = len(arquivos_tiff)

        # 3. Iteração e validação individual com tratamento de erros
        arquivos_aprovados = []
        arquivos_nao_conformes = []
        arquivos_corrompidos = []

        for i, caminho_completo in enumerate(arquivos_tiff):
            if feedback.isCanceled():
                break

            feedback.setProgress(int(((i + 1) / total_arquivos) * 100))

            status, caminho_rel, detalhe = self._processar_arquivo(
                caminho_completo,
                params['pasta_mae'],
                params['bits_alvo'],
                feedback
            )

            if status == 'APROVADO':
                arquivos_aprovados.append((caminho_rel, detalhe))
            elif status == 'REPROVADO':
                arquivos_nao_conformes.append((caminho_rel, detalhe))
            else:
                arquivos_corrompidos.append((caminho_rel, detalhe))

        # 4. Construção e escrita do relatório final
        buffer_relatorio = self._montar_relatorio(
            params,
            total_arquivos,
            arquivos_aprovados,
            arquivos_nao_conformes,
            arquivos_corrompidos
        )
        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(
            self.tr(f"✓ Processamento concluído: {total_arquivos} arquivo(s) verificado(s).")
        )

        return {self.OUTPUT_REPORT: params['arquivo_saida']}

    # =========================================================================
    # MÉTODOS AUXILIARES PRIVADOS
    # =========================================================================

    def _recuperar_parametros(self, parameters, context):
        """
        Extrai e organiza os parâmetros escolhidos pelo usuário.

        Args:
            parameters (dict): Parâmetros brutos do QGIS.
            context (QgsProcessingContext): Contexto de execução.

        Returns:
            dict: Parâmetros estruturados.
        """
        idx_bits = self.parameterAsEnum(parameters, self.BITS_REFERENCIA, context)
        return {
            'pasta_mae': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'bits_alvo': int(self.OPCOES_BITS[idx_bits]),
            'arquivo_saida': self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)
        }

    def _validar_parametros(self, params):
        """
        Verifica se os parâmetros básicos de entrada são válidos.

        Args:
            params (dict): Dicionário com os parâmetros recuperados.

        Raises:
            QgsProcessingException: Caso a pasta de entrada não exista.
        """
        if not params['pasta_mae'] or not os.path.isdir(params['pasta_mae']):
            raise QgsProcessingException(
                self.tr(f"Diretório de entrada inválido ou inexistente: {params['pasta_mae']}")
            )

    def _listar_arquivos(self, pasta_mae, feedback):
        """
        Realiza varredura recursiva na pasta de entrada em busca de imagens TIFF.

        Args:
            pasta_mae (str): Diretório raiz da busca.
            feedback (QgsProcessingFeedback): Objeto de feedback do QGIS.

        Returns:
            list: Lista com os caminhos completos dos arquivos TIFF encontrados.

        Raises:
            QgsProcessingException: Caso nenhum arquivo TIFF seja localizado.
        """
        arquivos_tiff = []
        for root, _, files in os.walk(pasta_mae):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    arquivos_tiff.append(os.path.join(root, f))

        if not arquivos_tiff:
            raise QgsProcessingException(
                self.tr(f"Nenhum arquivo .tif ou .tiff encontrado em: {pasta_mae}")
            )

        return sorted(arquivos_tiff)

    def _processar_arquivo(self, caminho_completo, pasta_mae, bits_alvo, feedback):
        """
        Extrai a tag BitsPerSample de um arquivo TIFF e avalia sua conformidade.

        Args:
            caminho_completo (str): Caminho absoluto do arquivo raster.
            pasta_mae (str): Caminho do diretório raiz para extração do caminho relativo.
            bits_alvo (int): Valor de profundidade de bits de referência.
            feedback (QgsProcessingFeedback): Objeto para reporte de erros sem travamento.

        Returns:
            tuple: (status, caminho_relativo, descricao_detalhada)
        """
        rel_path = os.path.relpath(caminho_completo, pasta_mae)

        try:
            with Image.open(caminho_completo) as img:
                if not hasattr(img, 'tag_v2') or img.tag_v2 is None:
                    msg = "Estrutura de tags TIFF ausente ou ilegível"
                    feedback.reportError(self.tr(f"[!] {rel_path}: {msg}"))
                    return ('ERRO', rel_path, msg)

                meta_dict = {TAGS.get(key, key): img.tag_v2.get(key) for key in img.tag_v2}
                bits_encontrados = meta_dict.get('BitsPerSample')

                if bits_encontrados is None:
                    msg = "Tag 'BitsPerSample' ausente nos metadados"
                    feedback.reportError(self.tr(f"[!] {rel_path}: {msg}"))
                    return ('ERRO', rel_path, msg)

                if self._validar_bits(bits_encontrados, bits_alvo):
                    return ('APROVADO', rel_path, f"{bits_encontrados} bits")
                else:
                    return ('REPROVADO', rel_path, f"Encontrado: {bits_encontrados}")

        except (IOError, OSError, Image.UnidentifiedImageError) as e:
            msg = f"Arquivo corrompido ou erro de leitura I/O: {str(e)}"
            feedback.reportError(self.tr(f"[!] Erro em {rel_path}: {msg}"))
            return ('ERRO', rel_path, msg)

        except Exception as e:
            msg = f"Erro inesperado ao processar imagem: {str(e)}"
            feedback.reportError(self.tr(f"[!] Erro crítico em {rel_path}: {msg}"))
            return ('ERRO', rel_path, msg)

    def _validar_bits(self, bits_lidos, valor_alvo):
        """
        Compara o valor de bits extraído do cabeçalho TIFF com o valor de referência.

        Args:
            bits_lidos (tuple | int): Profundidade de bits lida por canal ou única.
            valor_alvo (int): Profundidade de bits exigida.

        Returns:
            bool: True se todas as bandas possuírem a profundidade exigida, False caso contrário.
        """
        if isinstance(bits_lidos, (tuple, list)):
            return all(int(b) == valor_alvo for b in bits_lidos)
        return int(bits_lidos) == valor_alvo

    def _montar_relatorio(self, params, total, aprovados, reprovados, corrompidos):
        """
        Organiza todas as seções do relatório de auditoria em uma lista de linhas.

        Args:
            params (dict): Parâmetros utilizados na execução.
            total (int): Total de arquivos processados.
            aprovados (list): Lista de tuplas (caminho, detalhe) aprovadas.
            reprovados (list): Lista de tuplas (caminho, detalhe) reprovadas.
            corrompidos (list): Lista de tuplas (caminho, erro) corrompidas.

        Returns:
            list: Linhas formatadas do relatório.
        """
        agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        alvo = params['bits_alvo']

        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE FISCALIZAÇÃO - CONFORMIDADE RADIOMÉTRICA (BITS)"),
            self.tr(f"Data/Hora: {agora}"),
            "=" * 80,
            self.tr("PARÂMETROS DE CONFIGURAÇÃO:"),
            f"  • Diretório Analisado: {params['pasta_mae']}",
            f"  • Profundidade de Bits Esperada: {alvo} bits",
            "",
            self.tr("RESUMO DA AUDITORIA:"),
            f"  • Total de arquivos verificados: {total}",
            f"  • Arquivos aprovados (conformes): {len(aprovados)}",
            f"  • Arquivos reprovados (fora da especificação): {len(reprovados)}",
            f"  • Arquivos corrompidos ou com erro de leitura: {len(corrompidos)}",
            "=" * 80,
            ""
        ]

        # 1. Listagem prioritária de Reprovações e Alertas
        if reprovados or corrompidos:
            if reprovados:
                linhas.append(self.tr(f"[!] ARQUIVOS REPROVADOS (Diferentes de {alvo} bits):"))
                linhas.append("-" * 80)
                for path, detalhe in reprovados:
                    linhas.append(f"  [!] {path} | {detalhe}")
                linhas.append("")

            if corrompidos:
                linhas.append(self.tr("[!] ARQUIVOS CORROMPIDOS OU COM ERRO DE LEITURA:"))
                linhas.append("-" * 80)
                for path, erro in corrompidos:
                    linhas.append(f"  [!] {path} | {erro}")
                linhas.append("")
        else:
            linhas.append(
                self.tr(f"✓ STATUS: CONFORME. Todos os {total} arquivos possuem {alvo} bits.")
            )
            linhas.append("")

        # 2. Listagem dos demais arquivos (Aprovados)
        if aprovados:
            linhas.append(self.tr("ARQUIVOS CONFORMES (APROVADOS):"))
            linhas.append("-" * 80)
            for path, detalhe in aprovados:
                linhas.append(f"  ✓ {path} | {detalhe}")
            linhas.append("")

        linhas.append("-" * 80)
        linhas.append(self.tr("Gerado automaticamente pelo Sistema de Fiscalização Mapeamento SEI"))

        return linhas

    def _escrever_relatorio(self, caminho_saida, buffer):
        """
        Grava o conteúdo do buffer de auditoria em um arquivo de texto (.txt).

        Args:
            caminho_saida (str): Caminho completo do arquivo .txt de destino.
            buffer (list): Lista de strings que compõem o relatório.

        Raises:
            QgsProcessingException: Caso ocorra falha de permissão ou I/O ao salvar.
        """
        try:
            diretorio_pai = os.path.dirname(caminho_saida)
            if diretorio_pai and not os.path.exists(diretorio_pai):
                os.makedirs(diretorio_pai, exist_ok=True)

            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(
                self.tr(f"Erro ao salvar o arquivo de relatório em '{caminho_saida}': {str(e)}")
            )