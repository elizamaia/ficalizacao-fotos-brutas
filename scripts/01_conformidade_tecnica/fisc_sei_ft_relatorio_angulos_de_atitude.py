# -*- coding: utf-8 -*-
"""
Plugin QGIS para Análise de Qualidade de Voo Aerofotogramétrico

Este algoritmo processa relatórios de voo contendo ângulos de atitude
(omega/phi/kappa) e gera um relatório de controle de qualidade baseado
em limites de inclinação (tilt) e deriva (yaw drift).

Cálculos:
    - Tilt: √(ω² + φ²) - magnitude do vetor de inclinação
    - Deriva: |κ - median(κ)| - normalizado para ângulos circulares 0-360°

Autor: Versão Refatorada
Data: 2025
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime


class AnaliseQualidadeVoo(QgsProcessingAlgorithm):
    """
    Algoritmo de análise de qualidade de voo para fotogrametria.

    Este processador avalia múltiplos arquivos CSV/TXT contendo dados de
    atitude de câmeras (omega, phi, kappa) e valida contra limites de
    qualidade especificados pelo usuário.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    # Entrada e Saída
    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # Mapeamento de Colunas
    COL_ID = 'COL_ID'
    COL_OMEGA = 'COL_OMEGA'
    COL_PHI = 'COL_PHI'
    COL_KAPPA = 'COL_KAPPA'

    # Configuração de Separadores
    DELIMITER = 'DELIMITER'
    DECIMAL = 'DECIMAL'

    # Configuração de Faixa
    STRIP_START = 'STRIP_START'
    STRIP_END = 'STRIP_END'

    # Limites de Qualidade
    LIMIT_TILT_PHOTO = 'LIMIT_TILT_PHOTO'
    LIMIT_TILT_STRIP = 'LIMIT_TILT_STRIP'
    LIMIT_DERIVA_PHOTO = 'LIMIT_DERIVA_PHOTO'
    LIMIT_DERIVA_STRIP = 'LIMIT_DERIVA_STRIP'

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
        return QCoreApplication.translate('AnaliseQualidadeVoo', string)

    def createInstance(self):
        """Cria uma nova instância do algoritmo."""
        return AnaliseQualidadeVoo()

    def name(self):
        """Retorna o identificador único do algoritmo."""
        return 'relatorio_atitude_omega_phi_kappa'

    def displayName(self):
        """Retorna o nome exibido do algoritmo."""
        return self.tr('Fotos Brutas - Relatório - Ângulos de Atitude (omega/phi/kappa)')

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

        Define 14 parâmetros organizados em 6 categorias:
        1. Arquivos (pasta de entrada)
        2. Mapeamento de colunas
        3. Configuração de texto (separadores)
        4. Configuração de faixa
        5. Limites de qualidade
        6. Arquivo de saída
        """
        # --------------------------------------------------------------------
        # 1. ARQUIVOS (PASTA DE ENTRADA)
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com os Relatórios de Voo'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # --------------------------------------------------------------------
        # 2. MAPEAMENTO DE COLUNAS
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_ID,
                self.tr('Nome da Coluna da FOTO (Ex: PHOTOID)'),
                defaultValue='PHOTOID'
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.COL_OMEGA,
                self.tr('Nome da Coluna OMEGA / ROLL'),
                defaultValue='OMEGA'
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.COL_PHI,
                self.tr('Nome da Coluna PHI / PITCH'),
                defaultValue='PHI'
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.COL_KAPPA,
                self.tr('Nome da Coluna KAPPA / YAW'),
                defaultValue='KAPPA'
            )
        )

        # --------------------------------------------------------------------
        # 3. CONFIGURAÇÃO DE SEPARADORES
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DELIMITER,
                self.tr('Separador de Colunas'),
                options=['Ponto e Vírgula (;)', 'Vírgula (,)'],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DECIMAL,
                self.tr('Separador Decimal'),
                options=['Ponto (.)', 'Vírgula (,)'],
                defaultValue=0
            )
        )

        # --------------------------------------------------------------------
        # 4. CONFIGURAÇÃO DE FAIXA
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STRIP_START,
                self.tr('Índice Inicial da Faixa (Recorte do Nome)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.STRIP_END,
                self.tr('Índice Final da Faixa (Recorte do Nome)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=4,
                minValue=1
            )
        )

        # --------------------------------------------------------------------
        # 5. LIMITES DE QUALIDADE
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIMIT_TILT_PHOTO,
                self.tr('Limite Tilt (Foto)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIMIT_TILT_STRIP,
                self.tr('Limite Tilt (Média Faixa)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.0,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIMIT_DERIVA_PHOTO,
                self.tr('Limite Deriva (Foto)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIMIT_DERIVA_STRIP,
                self.tr('Limite Deriva (Média Faixa)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.1
            )
        )

        # --------------------------------------------------------------------
        # 6. ARQUIVO DE SAÍDA
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
        Executa o algoritmo de análise de qualidade de voo.

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

        # --------------------------------------------------------------------
        # LISTA DE ARQUIVOS PARA PROCESSAMENTO
        # --------------------------------------------------------------------
        lista_arquivos = self._listar_arquivos(params['pasta'], feedback)

        # --------------------------------------------------------------------
        # INICIALIZAÇÃO DO RELATÓRIO
        # --------------------------------------------------------------------
        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params))

        # --------------------------------------------------------------------
        # PROCESSAMENTO DOS ARQUIVOS
        # --------------------------------------------------------------------
        total_arquivos = len(lista_arquivos)

        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            feedback.setProgress(int((i / total_arquivos) * 100))

            # Processar arquivo individual
            resultado = self._processar_arquivo(
                caminho_arquivo,
                params,
                feedback
            )

            # Adicionar resultado ao buffer
            buffer_relatorio.extend(resultado)

        # --------------------------------------------------------------------
        # ESCRITA DO RELATÓRIO FINAL
        # --------------------------------------------------------------------
        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(
            self.tr(f"✓ Processamento concluído: {total_arquivos} arquivo(s)")
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
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context),
            'colunas': {
                'id': self.parameterAsString(parameters, self.COL_ID, context).strip(),
                'omega': self.parameterAsString(parameters, self.COL_OMEGA, context).strip(),
                'phi': self.parameterAsString(parameters, self.COL_PHI, context).strip(),
                'kappa': self.parameterAsString(parameters, self.COL_KAPPA, context).strip()
            },
            'separador': ';' if self.parameterAsEnum(parameters, self.DELIMITER, context) == 0 else ',',
            'decimal': '.' if self.parameterAsEnum(parameters, self.DECIMAL, context) == 0 else ',',
            'faixa': {
                'inicio': self.parameterAsInt(parameters, self.STRIP_START, context),
                'fim': self.parameterAsInt(parameters, self.STRIP_END, context)
            },
            'limites': {
                'tilt_foto': self.parameterAsDouble(parameters, self.LIMIT_TILT_PHOTO, context),
                'tilt_faixa': self.parameterAsDouble(parameters, self.LIMIT_TILT_STRIP, context),
                'deriva_foto': self.parameterAsDouble(parameters, self.LIMIT_DERIVA_PHOTO, context),
                'deriva_faixa': self.parameterAsDouble(parameters, self.LIMIT_DERIVA_STRIP, context)
            }
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
        # Validar índices de faixa
        f_ini = params['faixa']['inicio']
        f_fim = params['faixa']['fim']

        if f_ini >= f_fim:
            raise QgsProcessingException(
                self.tr("Índice inicial da faixa deve ser menor que o índice final")
            )

        if f_ini < 0:
            raise QgsProcessingException(
                self.tr("Índice inicial da faixa não pode ser negativo")
            )

        # Validar limites (devem ser positivos)
        for chave, valor in params['limites'].items():
            if valor <= 0:
                raise QgsProcessingException(
                    self.tr(f"Limite '{chave}' deve ser maior que zero")
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
        arquivos = (
            glob.glob(os.path.join(pasta, "*.txt")) +
            glob.glob(os.path.join(pasta, "*.csv"))
        )

        if not arquivos:
            raise QgsProcessingException(
                self.tr(f"Nenhum arquivo .txt ou .csv encontrado em: {pasta}")
            )

        return arquivos

    def _criar_cabecalho(self, params):
        """
        Cria o cabeçalho do relatório.

        Args:
            params (dict): Dicionário de parâmetros

        Returns:
            str: Cabeçalho formatado
        """
        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE CONTROLE DE QUALIDADE DE VOO"),
            self.tr(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 80,
            self.tr("PARÂMETROS DE CONFIGURAÇÃO:"),
            f"  • Separador: '{params['separador']}'",
            f"  • Decimal: '{params['decimal']}'",
            f"  • Colunas: {', '.join(params['colunas'].values())}",
            f"  • Faixa: [{params['faixa']['inicio']}:{params['faixa']['fim']}]",
            "",
            self.tr("LIMITES DE QUALIDADE:"),
            f"  • Tilt (Foto): {params['limites']['tilt_foto']}°",
            f"  • Tilt (Faixa): {params['limites']['tilt_faixa']}°",
            f"  • Deriva (Foto): {params['limites']['deriva_foto']}°",
            f"  • Deriva (Faixa): {params['limites']['deriva_faixa']}°",
            "=" * 80,
            ""
        ]

        return "\n".join(linhas)

    def _processar_arquivo(self, caminho_arquivo, params, feedback):
        """
        Processa um arquivo individual de relatório de voo.

        Args:
            caminho_arquivo (str): Caminho do arquivo
            params (dict): Parâmetros de processamento
            feedback: Objeto de feedback

        Returns:
            list: Lista de strings com o resultado do processamento
        """
        nome_arquivo = os.path.basename(caminho_arquivo)
        resultado = []

        try:
            # ----------------------------------------------------------------
            # LEITURA E PREPARAÇÃO DOS DADOS
            # ----------------------------------------------------------------
            df = self._ler_arquivo(caminho_arquivo, params, feedback)

            # Validar colunas
            if not self._validar_colunas(df, params, feedback):
                return [
                    f"\n{self.tr('[ERRO]')} {nome_arquivo}: " +
                    self.tr("Colunas obrigatórias não encontradas")
                ]

            # Renomear colunas para padronização interna
            df = self._padronizar_colunas(df, params)

            # Identificar faixa
            df['Faixa'] = (
                df['ID']
                .astype(str)
                .str.strip()
                .str[params['faixa']['inicio']:params['faixa']['fim']]
            )

            # ----------------------------------------------------------------
            # CÁLCULO DE MÉTRICAS
            # ----------------------------------------------------------------
            df = self._calcular_metricas(df, params, feedback, nome_arquivo)

            # Validar se há faixas vazias
            faixas_vazias = df[df['Faixa'] == '']
            if len(faixas_vazias) > 0:
                feedback.pushWarning(
                    self.tr(f"{len(faixas_vazias)} fotos com faixa vazia em {nome_arquivo}")
                )

            # ----------------------------------------------------------------
            # ANÁLISE POR FAIXA
            # ----------------------------------------------------------------
            resumo_faixas = df.groupby('Faixa').agg({
                'tilt_calc': 'mean',
                'deriva_calc': 'mean'
            }).reset_index()

            # ----------------------------------------------------------------
            # VALIDAÇÃO DE QUALIDADE
            # ----------------------------------------------------------------
            validacao = self._validar_qualidade(
                df,
                resumo_faixas,
                params['limites'],
                feedback
            )

            # ----------------------------------------------------------------
            # MONTAGEM DO RELATÓRIO
            # ----------------------------------------------------------------
            resultado.extend(self._criar_relatorio_arquivo(
                nome_arquivo,
                df,
                resumo_faixas,
                validacao,
                params['limites']
            ))

        except pd.errors.ParserError as e:
            resultado.append(
                f"\n{self.tr('[ERRO]')} {nome_arquivo}: " +
                self.tr(f"Arquivo mal formatado: {str(e)}")
            )
            feedback.reportError(self.tr(f"Erro de parse em {nome_arquivo}: {e}"))

        except IOError as e:
            resultado.append(
                f"\n{self.tr('[ERRO]')} {nome_arquivo}: " +
                self.tr(f"Erro de leitura: {str(e)}")
            )
            feedback.reportError(self.tr(f"Erro de I/O em {nome_arquivo}: {e}"))

        except Exception as e:
            resultado.append(
                f"\n{self.tr('[ERRO CRÍTICO]')} {nome_arquivo}: {str(e)}"
            )
            feedback.reportError(self.tr(f"Erro inesperado em {nome_arquivo}: {e}"))

        return resultado

    def _ler_arquivo(self, caminho, params, feedback):
        """
        Lê arquivo CSV/TXT com tratamento de erros.

        Args:
            caminho (str): Caminho do arquivo
            params (dict): Parâmetros de configuração
            feedback: Objeto de feedback

        Returns:
            pd.DataFrame: DataFrame com os dados
        """
        df = pd.read_csv(
            caminho,
            sep=params['separador'],
            decimal=params['decimal'],
            engine='python',
            skipinitialspace=True,
            encoding='utf-8',
            on_bad_lines='warn'
        )

        # Remover espaços dos nomes das colunas
        df.columns = df.columns.str.strip()

        return df

    def _validar_colunas(self, df, params, feedback):
        """
        Valida se as colunas necessárias existem no DataFrame.

        Args:
            df (pd.DataFrame): DataFrame a validar
            params (dict): Parâmetros com nomes das colunas
            feedback: Objeto de feedback

        Returns:
            bool: True se colunas existem, False caso contrário
        """
        colunas_necessarias = [
            params['colunas']['id'],
            params['colunas']['omega'],
            params['colunas']['phi'],
            params['colunas']['kappa']
        ]

        colunas_faltantes = [
            col for col in colunas_necessarias if col not in df.columns
        ]

        if colunas_faltantes:
            feedback.reportError(
                self.tr(f"Colunas não encontradas: {colunas_faltantes}")
            )
            return False

        return True

    def _padronizar_colunas(self, df, params):
        """
        Renomeia colunas para nomes padronizados internos.

        Args:
            df (pd.DataFrame): DataFrame original
            params (dict): Parâmetros com mapeamento de colunas

        Returns:
            pd.DataFrame: DataFrame com colunas renomeadas
        """
        mapeamento = {
            params['colunas']['id']: 'ID',
            params['colunas']['omega']: 'W',
            params['colunas']['phi']: 'P',
            params['colunas']['kappa']: 'K'
        }

        return df.rename(columns=mapeamento)

    def _calcular_metricas(self, df, params, feedback, nome_arquivo):
        """
        Calcula tilt e deriva para cada foto.

        Cálculos:
            - Tilt: √(ω² + φ²)
            - Deriva: |κ - median(κ)| normalizado para 0-180°

        Args:
            df (pd.DataFrame): DataFrame com dados brutos
            params (dict): Parâmetros de configuração
            feedback: Objeto de feedback
            nome_arquivo (str): Nome do arquivo para mensagens

        Returns:
            pd.DataFrame: DataFrame com colunas de métricas adicionadas
        """
        # Converter para numérico
        for col in ['W', 'P', 'K']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Remover linhas com valores inválidos
        linhas_antes = len(df)
        df = df.dropna(subset=['W', 'P', 'K'])
        linhas_depois = len(df)

        if linhas_antes > linhas_depois:
            removidas = linhas_antes - linhas_depois
            feedback.pushWarning(
                self.tr(f"{removidas} linhas com valores inválidos removidas em {nome_arquivo}")
            )

        # Validar ranges de ângulos
        omega_fora = df[df['W'].abs() > 180]
        phi_fora = df[df['P'].abs() > 180]
        kappa_fora = df[(df['K'] < 0) | (df['K'] > 360)]

        if len(omega_fora) > 0:
            feedback.pushWarning(
                self.tr(f"{len(omega_fora)} valores de OMEGA fora do range esperado (-180° a 180°)")
            )

        if len(phi_fora) > 0:
            feedback.pushWarning(
                self.tr(f"{len(phi_fora)} valores de PHI fora do range esperado (-180° a 180°)")
            )

        if len(kappa_fora) > 0:
            feedback.pushWarning(
                self.tr(f"{len(kappa_fora)} valores de KAPPA fora do range esperado (0° a 360°)")
            )

        # Calcular Tilt: √(ω² + φ²)
        df['tilt_calc'] = np.sqrt(df['W']**2 + df['P']**2)

        # Calcular Deriva: |κ - median(κ)| normalizado
        medias_k = df.groupby('Faixa')['K'].transform('median')
        diffs = (df['K'] - medias_k).abs()
        df['deriva_calc'] = np.where(diffs > 180, 360 - diffs, diffs)

        return df

    def _validar_qualidade(self, df, resumo_faixas, limites, feedback):
        """
        Valida métricas contra limites de qualidade.

        Args:
            df (pd.DataFrame): DataFrame com métricas calculadas
            resumo_faixas (pd.DataFrame): Resumo por faixa
            limites (dict): Limites de qualidade
            feedback: Objeto de feedback

        Returns:
            dict: Dicionário com DataFrames de violações
        """
        return {
            'tilt_foto': df[df['tilt_calc'] > limites['tilt_foto']],
            'deriva_foto': df[df['deriva_calc'] > limites['deriva_foto']],
            'tilt_faixa': resumo_faixas[resumo_faixas['tilt_calc'] > limites['tilt_faixa']],
            'deriva_faixa': resumo_faixas[resumo_faixas['deriva_calc'] > limites['deriva_faixa']]
        }

    def _criar_relatorio_arquivo(self, nome_arquivo, df, resumo, validacao, limites):
        """
        Cria o relatório de análise de um arquivo.

        Args:
            nome_arquivo (str): Nome do arquivo
            df (pd.DataFrame): DataFrame completo
            resumo (pd.DataFrame): Resumo por faixa
            validacao (dict): Resultados da validação
            limites (dict): Limites de qualidade

        Returns:
            list: Lista de strings do relatório
        """
        linhas = [
            "",
            self.tr("ANÁLISE: {}").format(nome_arquivo),
            "-" * 60,
            "",
            self.tr("📊 ESTATÍSTICAS GERAIS"),
            f"  • Fotos analisadas: {len(df)}",
            f"  • Faixas identificadas: {len(resumo)}",
            "",
            f"  • Tilt - Mínimo: {df['tilt_calc'].min():.2f}°",
            f"  • Tilt - Máximo: {df['tilt_calc'].max():.2f}°",
            f"  • Tilt - Média: {df['tilt_calc'].mean():.2f}°",
            "",
            f"  • Deriva - Mínima: {df['deriva_calc'].min():.2f}°",
            f"  • Deriva - Máxima: {df['deriva_calc'].max():.2f}°",
            f"  • Deriva - Média: {df['deriva_calc'].mean():.2f}°",
            "",
            "-" * 30,
            self.tr("✅ VALIDAÇÃO DE TILT"),
            "-" * 30,
        ]

        # Tilt por Foto
        if len(validacao['tilt_foto']) > 0:
            linhas.append(
                f"  [!] {len(validacao['tilt_foto'])} " +
                self.tr(f"FOTOS com Tilt > {limites['tilt_foto']}°")
            )
            linhas.append(validacao['tilt_foto'][['ID', 'tilt_calc']].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Tilt Foto Aprovado')}")

        linhas.append("")

        # Tilt por Faixa
        if len(validacao['tilt_faixa']) > 0:
            linhas.append(
                f"  [!] {len(validacao['tilt_faixa'])} " +
                self.tr(f"FAIXAS com Tilt Médio > {limites['tilt_faixa']}°")
            )
            linhas.append(validacao['tilt_faixa'].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Tilt Faixa Aprovado')}")

        linhas.extend([
            "",
            "-" * 30,
            self.tr("✅ VALIDAÇÃO DE DERIVA"),
            "-" * 30,
        ])

        # Deriva por Foto
        if len(validacao['deriva_foto']) > 0:
            linhas.append(
                f"  [!] {len(validacao['deriva_foto'])} " +
                self.tr(f"FOTOS com Deriva > {limites['deriva_foto']}°")
            )
            linhas.append(validacao['deriva_foto'][['ID', 'deriva_calc']].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Deriva Foto Aprovada')}")

        linhas.append("")

        # Deriva por Faixa
        if len(validacao['deriva_faixa']) > 0:
            linhas.append(
                f"  [!] {len(validacao['deriva_faixa'])} " +
                self.tr(f"FAIXAS com Deriva Média > {limites['deriva_faixa']}°")
            )
            linhas.append(validacao['deriva_faixa'].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Deriva Faixa Aprovada')}")

        return linhas

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