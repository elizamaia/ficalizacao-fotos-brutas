# -*- coding: utf-8 -*-
"""
Plugin QGIS para Análise de Qualidade de Voo Aerofotogramétrico (Entrada Vetorial)

Este algoritmo processa uma camada vetorial de pontos contendo os ângulos de 
atitude (omega/phi/kappa) e gera um relatório de controle de qualidade baseado
em limites de inclinação (tilt) e deriva (yaw drift).

Cálculos:
    - Tilt: √(ω² + φ²) - magnitude do vetor de inclinação
    - Deriva: |κ - median(κ)| - normalizado para ângulos circulares 0-360°

Autor: Fiscalização Mapeamento SEI
Data: 2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication
import pandas as pd
import numpy as np
from datetime import datetime


class AnaliseQualidadeVooVetor(QgsProcessingAlgorithm):
    """
    Algoritmo de análise de qualidade de voo para fotogrametria.

    Este processador avalia uma camada vetorial de pontos contendo dados de
    atitude de câmeras (omega, phi, kappa) e valida contra limites de
    qualidade especificados pelo usuário.
    """

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================

    # Entrada e Saída
    INPUT_LAYER = 'INPUT_LAYER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # Mapeamento de Campos (Colunas)
    COL_ID = 'COL_ID'
    COL_FAIXA = 'COL_FAIXA'
    COL_OMEGA = 'COL_OMEGA'
    COL_PHI = 'COL_PHI'
    COL_KAPPA = 'COL_KAPPA'

    # Limites de Qualidade
    LIMIT_TILT_PHOTO = 'LIMIT_TILT_PHOTO'
    LIMIT_TILT_STRIP = 'LIMIT_TILT_STRIP'
    LIMIT_DERIVA_PHOTO = 'LIMIT_DERIVA_PHOTO'
    LIMIT_DERIVA_STRIP = 'LIMIT_DERIVA_STRIP'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================

    def tr(self, string):
        """Traduz string usando o sistema de internacionalização do QGIS."""
        return QCoreApplication.translate('AnaliseQualidadeVooVetor', string)

    def createInstance(self):
        """Cria uma nova instância do algoritmo."""
        return AnaliseQualidadeVooVetor()

    def name(self):
        """Retorna o identificador único do algoritmo."""
        return 'relatorio_atitude_vetor'

    def displayName(self):
        """Retorna o nome exibido do algoritmo."""
        return self.tr('Fotos Brutas - Vetor - Ângulos de Atitude (omega/phi/kappa)')

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
        """
        # --------------------------------------------------------------------
        # 1. DADOS DE ENTRADA (CAMADA VETORIAL)
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER,
                self.tr('Camada Vetorial de Pontos (Centros de Câmera)'),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        # --------------------------------------------------------------------
        # 2. MAPEAMENTO DE CAMPOS DA TABELA DE ATRIBUTOS
        # --------------------------------------------------------------------
        self.addParameter(
            QgsProcessingParameterField(
                self.COL_ID,
                self.tr('Campo de Identificação da Foto (Ex: PHOTOID)'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Any
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.COL_FAIXA,
                self.tr('Campo de Identificação da Faixa de Voo'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Any
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.COL_OMEGA,
                self.tr('Campo do Ângulo OMEGA / ROLL'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Numeric
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.COL_PHI,
                self.tr('Campo do Ângulo PHI / PITCH'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Numeric
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.COL_KAPPA,
                self.tr('Campo do Ângulo KAPPA / YAW'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Numeric
            )
        )

        # --------------------------------------------------------------------
        # 3. LIMITES DE QUALIDADE
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
        # 4. ARQUIVO DE SAÍDA
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
        Executa o algoritmo de análise de qualidade extraindo dados da feição vetorial.
        """
        # 1. Recuperação dos parâmetros
        params = self._recuperar_parametros(parameters, context)
        self._validar_parametros(params, feedback)

        # 2. Inicialização da extração
        source = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        if source is None:
            raise QgsProcessingException(self.tr("Erro ao carregar a camada de entrada."))

        nome_camada = source.sourceName()
        total_feicoes = source.featureCount()
        
        if total_feicoes == 0:
            raise QgsProcessingException(self.tr("A camada vetorial selecionada está vazia."))

        buffer_relatorio = []
        buffer_relatorio.append(self._criar_cabecalho(params, nome_camada, total_feicoes))

        try:
            # 3. Leitura e extração para DataFrame Pandas
            df = self._extrair_feicoes_para_dataframe(source, params['colunas'], total_feicoes, feedback)

            # 4. Cálculo de métricas
            df = self._calcular_metricas(df, feedback)

            # Validar se há faixas vazias
            faixas_vazias = df[df['Faixa'].isna() | (df['Faixa'] == '')]
            if len(faixas_vazias) > 0:
                feedback.pushWarning(
                    self.tr(f"{len(faixas_vazias)} feições com o campo Faixa vazio.")
                )

            # 5. Análise por Faixa
            resumo_faixas = df.groupby('Faixa').agg({
                'tilt_calc': 'mean',
                'deriva_calc': 'mean'
            }).reset_index()

            # 6. Validação de Qualidade
            validacao = self._validar_qualidade(
                df,
                resumo_faixas,
                params['limites']
            )

            # 7. Geração da Saída Textual
            buffer_relatorio.extend(self._criar_relatorio_analise(
                nome_camada, df, resumo_faixas, validacao, params['limites']
            ))

            # 8. Escrita no arquivo de saída
            self._escrever_relatorio(params['arquivo_saida'], buffer_relatorio)

            feedback.pushInfo(self.tr(f"✓ Processamento concluído. {total_feicoes} feições avaliadas."))

        except Exception as e:
            feedback.reportError(self.tr(f"Erro inesperado durante o processamento: {str(e)}"))
            raise QgsProcessingException(self.tr(f"Falha na execução: {str(e)}"))

        return {self.OUTPUT_REPORT: params['arquivo_saida']}

    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================

    def _recuperar_parametros(self, parameters, context):
        """Organiza os parâmetros do algoritmo em um dicionário."""
        return {
            'arquivo_saida': self.parameterAsString(parameters, self.OUTPUT_REPORT, context),
            'colunas': {
                'id': self.parameterAsString(parameters, self.COL_ID, context),
                'faixa': self.parameterAsString(parameters, self.COL_FAIXA, context),
                'omega': self.parameterAsString(parameters, self.COL_OMEGA, context),
                'phi': self.parameterAsString(parameters, self.COL_PHI, context),
                'kappa': self.parameterAsString(parameters, self.COL_KAPPA, context)
            },
            'limites': {
                'tilt_foto': self.parameterAsDouble(parameters, self.LIMIT_TILT_PHOTO, context),
                'tilt_faixa': self.parameterAsDouble(parameters, self.LIMIT_TILT_STRIP, context),
                'deriva_foto': self.parameterAsDouble(parameters, self.LIMIT_DERIVA_PHOTO, context),
                'deriva_faixa': self.parameterAsDouble(parameters, self.LIMIT_DERIVA_STRIP, context)
            }
        }

    def _validar_parametros(self, params, feedback):
        """Valida os limites informados (devem ser positivos)."""
        for chave, valor in params['limites'].items():
            if valor <= 0:
                raise QgsProcessingException(
                    self.tr(f"O limite '{chave}' deve ser maior que zero.")
                )

    def _extrair_feicoes_para_dataframe(self, source, colunas, total_feicoes, feedback):
        """Itera sobre a camada vetorial e constrói um pandas DataFrame."""
        dados = []
        step = 100.0 / total_feicoes if total_feicoes > 0 else 0

        for current, feature in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break

            # Extração limpa dos atributos da tabela
            row = {
                'ID': str(feature[colunas['id']]),
                'Faixa': str(feature[colunas['faixa']]).strip(),
                'W': feature[colunas['omega']],
                'P': feature[colunas['phi']],
                'K': feature[colunas['kappa']]
            }
            dados.append(row)
            
            # Atualizar barra de progresso (0-50% reservado para extração)
            feedback.setProgress(int(current * step * 0.5))
            
        df = pd.DataFrame(dados)
        
        # Garantir tipo numérico para os ângulos
        for col in ['W', 'P', 'K']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        return df

    def _calcular_metricas(self, df, feedback):
        """Calcula tilt e deriva baseando-se nos atributos extraídos."""
        # Limpeza de linhas inválidas
        linhas_antes = len(df)
        df = df.dropna(subset=['W', 'P', 'K'])
        linhas_depois = len(df)

        if linhas_antes > linhas_depois:
            feedback.pushWarning(
                self.tr(f"{linhas_antes - linhas_depois} feições com valores de ângulo nulos foram ignoradas.")
            )

        # Checagem de Range
        omega_fora = df[df['W'].abs() > 180]
        phi_fora = df[df['P'].abs() > 180]
        kappa_fora = df[(df['K'] < 0) | (df['K'] > 360)]

        if len(omega_fora) > 0:
            feedback.pushWarning(self.tr(f"{len(omega_fora)} valores de OMEGA fora do range esperado (-180° a 180°)."))
        if len(phi_fora) > 0:
            feedback.pushWarning(self.tr(f"{len(phi_fora)} valores de PHI fora do range esperado (-180° a 180°)."))
        if len(kappa_fora) > 0:
            feedback.pushWarning(self.tr(f"{len(kappa_fora)} valores de KAPPA fora do range esperado (0° a 360°)."))

        # Cálculos matemáticos
        df['tilt_calc'] = np.sqrt(df['W']**2 + df['P']**2)
        
        medias_k = df.groupby('Faixa')['K'].transform('median')
        diffs = (df['K'] - medias_k).abs()
        df['deriva_calc'] = np.where(diffs > 180, 360 - diffs, diffs)

        return df

    def _validar_qualidade(self, df, resumo_faixas, limites):
        """Valida as métricas processadas contra os limites fornecidos."""
        return {
            'tilt_foto': df[df['tilt_calc'] > limites['tilt_foto']],
            'deriva_foto': df[df['deriva_calc'] > limites['deriva_foto']],
            'tilt_faixa': resumo_faixas[resumo_faixas['tilt_calc'] > limites['tilt_faixa']],
            'deriva_faixa': resumo_faixas[resumo_faixas['deriva_calc'] > limites['deriva_faixa']]
        }

    def _criar_cabecalho(self, params, nome_camada, total_feicoes):
        """Cria o bloco de cabeçalho do arquivo texto de saída."""
        linhas = [
            "=" * 80,
            self.tr("RELATÓRIO DE CONTROLE DE QUALIDADE DE VOO (VETORIAL)"),
            self.tr(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"),
            "=" * 80,
            self.tr("DADOS DE ENTRADA:"),
            f"  • Camada Analisada: '{nome_camada}'",
            f"  • Total de Feições Originais: {total_feicoes}",
            "",
            self.tr("MAPEAMENTO DE CAMPOS:"),
            f"  • ID: {params['colunas']['id']}",
            f"  • Faixa: {params['colunas']['faixa']}",
            f"  • Omega: {params['colunas']['omega']}",
            f"  • Phi: {params['colunas']['phi']}",
            f"  • Kappa: {params['colunas']['kappa']}",
            "",
            self.tr("LIMITES DE QUALIDADE CONFIGURADOS:"),
            f"  • Tilt (Foto): {params['limites']['tilt_foto']}°",
            f"  • Tilt (Faixa): {params['limites']['tilt_faixa']}°",
            f"  • Deriva (Foto): {params['limites']['deriva_foto']}°",
            f"  • Deriva (Faixa): {params['limites']['deriva_faixa']}°",
            "=" * 80,
            ""
        ]
        return "\n".join(linhas)

    def _criar_relatorio_analise(self, nome_camada, df, resumo, validacao, limites):
        """Estrutura as tabelas e apontamentos do relatório final."""
        linhas = [
            self.tr("📊 ESTATÍSTICAS GERAIS CALCULADAS"),
            f"  • Pontos (Fotos) com dados válidos: {len(df)}",
            f"  • Total de Faixas distintas identificadas: {len(resumo)}",
            "",
            f"  • Tilt - Mínimo: {df['tilt_calc'].min():.2f}° | Máximo: {df['tilt_calc'].max():.2f}° | Média Geral: {df['tilt_calc'].mean():.2f}°",
            f"  • Deriva - Mínima: {df['deriva_calc'].min():.2f}° | Máxima: {df['deriva_calc'].max():.2f}° | Média Geral: {df['deriva_calc'].mean():.2f}°",
            "",
            "-" * 60,
            self.tr("✅ VALIDAÇÃO DO ÂNGULO DE TILT"),
            "-" * 60,
        ]

        if len(validacao['tilt_foto']) > 0:
            linhas.append(f"  [!] {len(validacao['tilt_foto'])} FOTOS reprovadas (Tilt > {limites['tilt_foto']}°):")
            linhas.append(validacao['tilt_foto'][['ID', 'Faixa', 'tilt_calc']].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Todas as fotos aprovadas no parâmetro de Tilt.')}")
        linhas.append("")

        if len(validacao['tilt_faixa']) > 0:
            linhas.append(f"  [!] {len(validacao['tilt_faixa'])} FAIXAS reprovadas (Tilt Médio > {limites['tilt_faixa']}°):")
            linhas.append(validacao['tilt_faixa'].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Todas as faixas aprovadas no parâmetro de Tilt Médio.')}")

        linhas.extend([
            "",
            "-" * 60,
            self.tr("✅ VALIDAÇÃO DO ÂNGULO DE DERIVA (YAW DRIFT)"),
            "-" * 60,
        ])

        if len(validacao['deriva_foto']) > 0:
            linhas.append(f"  [!] {len(validacao['deriva_foto'])} FOTOS reprovadas (Deriva > {limites['deriva_foto']}°):")
            linhas.append(validacao['deriva_foto'][['ID', 'Faixa', 'deriva_calc']].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Todas as fotos aprovadas no parâmetro de Deriva.')}")
        linhas.append("")

        if len(validacao['deriva_faixa']) > 0:
            linhas.append(f"  [!] {len(validacao['deriva_faixa'])} FAIXAS reprovadas (Deriva Média > {limites['deriva_faixa']}°):")
            linhas.append(validacao['deriva_faixa'].to_string(index=False))
        else:
            linhas.append(f"  ✓ {self.tr('Todas as faixas aprovadas no parâmetro de Deriva Média.')}")

        return linhas

    def _escrever_relatorio(self, caminho_saida, buffer):
        """Gera o arquivo TXT em disco."""
        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write('\n'.join(buffer))
        except IOError as e:
            raise QgsProcessingException(
                self.tr(f"Erro de I/O ao tentar escrever o relatório final em '{caminho_saida}': {str(e)}")
            )