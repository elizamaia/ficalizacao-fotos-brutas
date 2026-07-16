# -*- coding: utf-8 -*-
"""
Plugin QGIS para Análise de Consistência na Altura de Voo

Este algoritmo processa relatórios de voo (TXT, CSV ou XLS) contendo as cotas
planejadas e executadas, calculando a variação percentual para o controle de qualidade
e garantia da consistência do GSD.

Cálculos:
    - Diferença Percentual: abs(executado - planejado) / planejado * 100

Autor: Eliza Silva Maia 
Data: 2026
"""

from qgis.core import (
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


class AnaliseConsistenciaAlturaVoo(QgsProcessingAlgorithm):
    """
    Algoritmo de análise da consistência altimétrica de voo aerofotogramétrico.
    
    Acessa relatórios em diretório alvo, calcula a diferença percentual 
    entre a cota executada e nominal e compila um relatório listando imagens reprovadas.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    COL_ID = 'COL_ID'
    COL_PLANEJADO = 'COL_PLANEJADO'
    COL_EXECUTADO = 'COL_EXECUTADO'

    DELIMITER = 'DELIMITER'
    DECIMAL = 'DECIMAL'

    LIMIT_TOLERANCIA = 'LIMIT_TOLERANCIA'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================

    def tr(self, string):
        """Traduz string usando o sistema de internacionalização do QGIS."""
        return QCoreApplication.translate('AnaliseConsistenciaAlturaVoo', string)

    def createInstance(self):
        """Cria uma nova instância do algoritmo."""
        return AnaliseConsistenciaAlturaVoo()

    def name(self):
        """Retorna o identificador único do algoritmo."""
        return 'fisc_sei_ft_relatorio_consistencia_altura_voo'

    def displayName(self):
        """Retorna o nome exibido do algoritmo."""
        return self.tr('Fotos Brutas - Relatório - Consistência na Altura de Voo')

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
        """Inicializa os parâmetros do algoritmo."""
        
        # 1. ARQUIVOS (PASTA DE ENTRADA)
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com os Relatórios de Voo (.txt, .csv, .xls, .xlsx)'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # 2. MAPEAMENTO DE COLUNAS
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_ID,
                self.tr('Nome da Coluna de Identificação da Foto'),
                defaultValue='PHOTO_ID'
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.COL_PLANEJADO,
                self.tr('Nome da Coluna: Altura Planejada'),
                defaultValue='Z_PLAN'
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.COL_EXECUTADO,
                self.tr('Nome da Coluna: Altura Executada'),
                defaultValue='Z_EXEC'
            )
        )

        # 3. CONFIGURAÇÃO DE SEPARADORES
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DELIMITER,
                self.tr('Separador de Colunas (apenas TXT/CSV)'),
                options=['Ponto e Vírgula (;)', 'Vírgula (,)'],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DECIMAL,
                self.tr('Separador Decimal (apenas TXT/CSV)'),
                options=['Ponto (.)', 'Vírgula (,)'],
                defaultValue=0
            )
        )

        # 4. LIMITES DE QUALIDADE
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIMIT_TOLERANCIA,
                self.tr('Tolerância Máxima de Variação (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0,
                minValue=0.1
            )
        )

        # 5. ARQUIVO DE SAÍDA
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Relatório de Saída em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    # =========================================================================
    # MÉTODO PRINCIPAL DE PROCESSAMENTO
    # =========================================================================

    def processAlgorithm(self, parameters, context, feedback):
        """Executa a rotina de validação."""
        params = self._recuperar_parametros(parameters, context)
        lista_arquivos = self._listar_arquivos(params['pasta'], feedback)

        buffer_relatorio = [self._criar_cabecalho(params)]
        total_arquivos = len(lista_arquivos)

        for i, caminho_arquivo in enumerate(lista_arquivos):
            if feedback.isCanceled():
                break

            feedback.setProgress(int((i / total_arquivos) * 100))
            resultado = self._processar_arquivo(caminho_arquivo, params, feedback)
            buffer_relatorio.extend(resultado)

        self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

        feedback.pushInfo(self.tr(f"✓ Processamento concluído: {total_arquivos} arquivo(s)"))
        return {self.OUTPUT_REPORT: params['arquivo_saida']}

    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================

    def _recuperar_parametros(self, parameters, context):
        """Recupera e organiza os parâmetros de entrada."""
        return {
            'pasta': self.parameterAsString(parameters, self.INPUT_FOLDER, context),
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context),
            'colunas': {
                'id': self.parameterAsString(parameters, self.COL_ID, context).strip(),
                'planejado': self.parameterAsString(parameters, self.COL_PLANEJADO, context).strip(),
                'executado': self.parameterAsString(parameters, self.COL_EXECUTADO, context).strip()
            },
            'separador': ';' if self.parameterAsEnum(parameters, self.DELIMITER, context) == 0 else ',',
            'decimal': '.' if self.parameterAsEnum(parameters, self.DECIMAL, context) == 0 else ',',
            'tolerancia': self.parameterAsDouble(parameters, self.LIMIT_TOLERANCIA, context)
        }

    def _listar_arquivos(self, pasta, feedback):
        """Lista os relatórios válidos dentro do diretório."""
        arquivos = (
            glob.glob(os.path.join(pasta, "*.txt")) +
            glob.glob(os.path.join(pasta, "*.csv")) +
            glob.glob(os.path.join(pasta, "*.xls")) +
            glob.glob(os.path.join(pasta, "*.xlsx"))
        )

        if not arquivos:
            raise QgsProcessingException(self.tr(f"Nenhum arquivo válido encontrado em: {pasta}"))
        return arquivos

    def _criar_cabecalho(self, params):
        """Gera o cabeçalho padronizado do relatório de auditoria."""
        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE CONTROLE DE QUALIDADE: CONSISTÊNCIA DA ALTURA DE VOO"),
            self.tr(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 80,
            self.tr("PARÂMETROS DE CONFIGURAÇÃO UTILIZADOS:"),
            f"  • Coluna de Identificação: '{params['colunas']['id']}'",
            f"  • Coluna Altura Planejada: '{params['colunas']['planejado']}'",
            f"  • Coluna Altura Executada: '{params['colunas']['executado']}'",
            f"  • Índice de Qualidade: <= {params['tolerancia']}% de variação",
            "=" * 80,
            ""
        ]
        return "\n".join(linhas)

    def _processar_arquivo(self, caminho_arquivo, params, feedback):
        """Controlador de processamento isolado por arquivo (try/except robusto)."""
        nome_arquivo = os.path.basename(caminho_arquivo)
        resultado = []

        try:
            df = self._ler_arquivo(caminho_arquivo, params)

            if not self._validar_colunas(df, params, feedback):
                return [f"\n[!] {nome_arquivo}: Falha - Colunas obrigatórias ausentes."]

            df = self._padronizar_colunas(df, params)
            df = self._calcular_metricas(df, params, feedback, nome_arquivo)
            
            validacao = self._validar_qualidade(df, params['tolerancia'])
            resultado.extend(self._criar_relatorio_arquivo(nome_arquivo, df, validacao, params['tolerancia']))

        except pd.errors.ParserError as e:
            msg = f"Arquivo mal formatado: {str(e)}"
            resultado.append(f"\n[!] {nome_arquivo}: {msg}")
            feedback.reportError(msg)
        except IOError as e:
            msg = f"Erro de I/O (leitura): {str(e)}"
            resultado.append(f"\n[!] {nome_arquivo}: {msg}")
            feedback.reportError(msg)
        except Exception as e:
            msg = f"Erro crítico: {str(e)}"
            resultado.append(f"\n[!] {nome_arquivo}: {msg}")
            feedback.reportError(msg)

        return resultado

    def _ler_arquivo(self, caminho, params):
        """Lê os arquivos de acordo com a extensão (suporta txt, csv, xls, xlsx)."""
        extensao = os.path.splitext(caminho)[1].lower()
        if extensao in ['.xls', '.xlsx']:
            df = pd.read_excel(caminho)
            df.columns = df.columns.astype(str).str.strip()
            return df
        else:
            df = pd.read_csv(
                caminho, sep=params['separador'], decimal=params['decimal'],
                engine='python', skipinitialspace=True, encoding='utf-8', on_bad_lines='warn'
            )
            df.columns = df.columns.str.strip()
            return df

    def _validar_colunas(self, df, params, feedback):
        """Checa a existência das colunas indicadas pelo usuário."""
        colunas_necessarias = [
            params['colunas']['id'],
            params['colunas']['planejado'],
            params['colunas']['executado']
        ]
        faltantes = [c for c in colunas_necessarias if c not in df.columns]
        if faltantes:
            feedback.reportError(self.tr(f"Colunas não encontradas: {faltantes}"))
            return False
        return True

    def _padronizar_colunas(self, df, params):
        """Padroniza nomenclaturas internamente para o script."""
        mapeamento = {
            params['colunas']['id']: 'ID',
            params['colunas']['planejado']: 'PLAN',
            params['colunas']['executado']: 'EXEC'
        }
        return df.rename(columns=mapeamento)

    def _calcular_metricas(self, df, params, feedback, nome_arquivo):
        """Calcula a variação percentual absoluta."""
        df['PLAN'] = pd.to_numeric(df['PLAN'], errors='coerce')
        df['EXEC'] = pd.to_numeric(df['EXEC'], errors='coerce')
        
        # Limpeza de nulos e de planos zerados para evitar erro matemático de divisão
        df = df.dropna(subset=['PLAN', 'EXEC'])
        df = df[df['PLAN'] != 0].copy()
        
        df['DIFF_PERC'] = (df['EXEC'] - df['PLAN']).abs() / df['PLAN'] * 100
        return df

    def _validar_qualidade(self, df, tolerancia):
        """Localiza e filtra as fotos que foram reprovadas no limiar matemático."""
        return df[df['DIFF_PERC'] > tolerancia].copy()

    def _criar_relatorio_arquivo(self, nome_arquivo, df, validacao, tolerancia):
        """Gera o sumário textual com formatação padronizada para as saídas."""
        linhas = [
            "",
            self.tr(f"ANÁLISE: {nome_arquivo}"),
            "-" * 60,
            f"  • Total de fotos avaliadas: {len(df)}"
        ]

        if len(validacao) > 0:
            linhas.append(f"  [!] REPROVADAS ({len(validacao)} fotos com variação > {tolerancia}%):")
            # Ordena decrescente pelas que tiveram pior diferença
            validacao = validacao.sort_values(by='DIFF_PERC', ascending=False)
            
            # Formata saída das colunas para visualização fácil
            validacao['RELATO'] = validacao.apply(
                lambda row: f"    - Foto {row['ID']}: Planejado={row['PLAN']} | Executado={row['EXEC']} | Variação={row['DIFF_PERC']:.2f}%",
                axis=1
            )
            linhas.extend(validacao['RELATO'].tolist())
        else:
            linhas.append(f"  ✓ Todas as fotos foram aprovadas (nenhuma variação > {tolerancia}%).")

        return linhas

    def _escrever_relatorio(self, caminho_saida, buffer):
        """Exporta os resultados finais compilados para .txt."""
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(self.tr(f"Erro ao escrever relatório final: {str(e)}"))