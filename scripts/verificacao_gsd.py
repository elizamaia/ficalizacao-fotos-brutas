# -*- coding: utf-8 -*-
"""
Plugin QGIS para Fotos Brutas - Vetor - Resolução Espacial (GSD)

Este algoritmo calcula o Ground Sampling Distance (GSD) de fotografias aéreas brutas a partir
dos seus centros perspectivos. Ele extrai a altitude do terreno através de um Modelo Digital de
Terreno (MDT) e calcula a distância real da aeronave até o solo.

Cálculos:
    - Distância Relativa (Aeronave-Solo): Altura do Voo (atributo) - Altitude do Terreno (MDT)
    - GSD: (Largura do Sensor * Distância Relativa) / (Distância Focal * Largura da Imagem)
    - Validação: Reprova fotografias cujo GSD calculado seja superior ao limite de tolerância estipulado.

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 17/07/2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsField,
    QgsFields,
    QgsFeatureSink,
    QgsFeature,
    QgsPointXY
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from datetime import datetime


class AnaliseResolucaoEspacialGSD(QgsProcessingAlgorithm):

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================
    INPUT_VECTOR = 'INPUT_VECTOR'
    INPUT_RASTER = 'INPUT_RASTER'
    FIELD_NAME = 'FIELD_NAME'
    FIELD_FLIGHT_HEIGHT = 'FIELD_FLIGHT_HEIGHT'
    
    SENSOR_WIDTH = 'SENSOR_WIDTH'
    FOCAL_LENGTH = 'FOCAL_LENGTH'
    IMAGE_WIDTH = 'IMAGE_WIDTH'
    GSD_LIMIT = 'GSD_LIMIT'
    
    OUTPUT_LAYER = 'OUTPUT_LAYER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return AnaliseResolucaoEspacialGSD()

    def name(self):
        return 'analise_resolucao_espacial_gsd'

    def displayName(self):
        return self.tr("Fotos Brutas - Vetor - Resolução Espacial (GSD)")

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================
    def initAlgorithm(self, config=None):
        
        # 1. ENTRADA DE DADOS ESPACIAIS
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT_VECTOR, self.tr("Camada de Pontos (Centros Perspectivos)"), types=[QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER, self.tr("Camada Raster (MDT)")))
        
        # 2. MAPEAMENTO DE COLUNAS
        self.addParameter(QgsProcessingParameterField(self.FIELD_NAME, self.tr("Campo com o nome da foto"), parentLayerParameterName=self.INPUT_VECTOR))
        self.addParameter(QgsProcessingParameterField(self.FIELD_FLIGHT_HEIGHT, self.tr("Campo com a Altura do Voo (Z)"), parentLayerParameterName=self.INPUT_VECTOR, type=QgsProcessingParameterField.Numeric))
        
        # 3. PARÂMETROS DA CÂMERA E LIMITES
        self.addParameter(QgsProcessingParameterNumber(self.SENSOR_WIDTH, self.tr("Largura do Sensor (mm)"), type=QgsProcessingParameterNumber.Double, defaultValue=100.5))
        self.addParameter(QgsProcessingParameterNumber(self.FOCAL_LENGTH, self.tr("Distância Focal (mm)"), type=QgsProcessingParameterNumber.Double, defaultValue=70.0))
        self.addParameter(QgsProcessingParameterNumber(self.IMAGE_WIDTH, self.tr("Largura da Imagem (pixels)"), type=QgsProcessingParameterNumber.Integer, defaultValue=23000))
        self.addParameter(QgsProcessingParameterNumber(self.GSD_LIMIT, self.tr("Limite de Tolerância do GSD (cm)"), type=QgsProcessingParameterNumber.Double, defaultValue=27.5))
        
        # 4. ARQUIVOS DE SAÍDA
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LAYER, self.tr("Camada de Auditoria de GSD")))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_REPORT, self.tr("Relatório de Reprovações (.txt)"), fileFilter='Text files (*.txt)'))

    # =========================================================================
    # MÉTODO PRINCIPAL DE PROCESSAMENTO
    # =========================================================================
    def processAlgorithm(self, parameters, context, feedback):
        
        # Recuperação de parâmetros
        vector_layer = self.parameterAsVectorLayer(parameters, self.INPUT_VECTOR, context)
        raster_layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        campo_nome = self.parameterAsString(parameters, self.FIELD_NAME, context)
        campo_altura_voo = self.parameterAsString(parameters, self.FIELD_FLIGHT_HEIGHT, context)
        
        sensor_width = self.parameterAsDouble(parameters, self.SENSOR_WIDTH, context)
        focal_length = self.parameterAsDouble(parameters, self.FOCAL_LENGTH, context)
        image_width = self.parameterAsDouble(parameters, self.IMAGE_WIDTH, context)
        gsd_limit = self.parameterAsDouble(parameters, self.GSD_LIMIT, context)
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # Configuração do provedor do raster para extração de valores
        raster_provider = raster_layer.dataProvider()
        
        # Preparação dos campos de saída
        in_fields = vector_layer.fields()
        out_fields = QgsFields()
        for field in in_fields:
            out_fields.append(field)
            
        new_fields = [
            QgsField('alt_terreno', QVariant.Double),
            QgsField('gsd_calc', QVariant.Double),
            QgsField('qc_gsd', QVariant.String)
        ]
        for field in new_fields: 
            out_fields.append(field)

        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT_LAYER, context, out_fields, vector_layer.wkbType(), vector_layer.crs())

        # Inicialização do processamento
        features = vector_layer.getFeatures()
        total = vector_layer.featureCount()
        reprovacoes = {}
        
        feedback.pushInfo("Iniciando extração do MDT e cálculos de GSD...")

        for i, feat in enumerate(features):
            if feedback.isCanceled(): break

            try:
                geom = feat.geometry()
                ponto_xy = geom.asPoint()
                
                nome_foto = str(feat[campo_nome]) if feat[campo_nome] else f"Feicao_{feat.id()}"
                altura_voo_absoluta = float(feat[campo_altura_voo])
                
                # Extrai a altitude do terreno (MDT)
                alt_terreno = self._extrair_altitude_terreno(raster_provider, ponto_xy)
                
                if alt_terreno is None:
                    raise Exception("Ponto fora da área de cobertura do MDT ou valor 'NoData'.")

                # Cálculos
                distancia_relativa = altura_voo_absoluta - alt_terreno
                gsd = self._calcular_gsd(sensor_width, focal_length, image_width, distancia_relativa)
                
                # Validação
                status_qc = self._validar_gsd(gsd, gsd_limit)
                
                if status_qc:
                    reprovacoes[nome_foto] = f"GSD calculado: {gsd:.2f} cm (Limite: {gsd_limit} cm)"

                # Gravação na nova camada
                out_feat = QgsFeature(out_fields)
                out_feat.setGeometry(geom)
                
                atributos_completos = feat.attributes() + [
                    alt_terreno,
                    round(gsd, 2),
                    status_qc
                ]
                
                out_feat.setAttributes(atributos_completos)
                sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

            except Exception as e:
                feedback.reportError(f"Falha ao processar feição '{nome_foto}' (ID: {feat.id()}): {str(e)}")
                reprovacoes[nome_foto] = f"ERRO DE PROCESSAMENTO: {str(e)}"

            feedback.setProgress(int((i / total) * 100))

        # Geração do relatório
        self._gerar_relatorio_txt(caminho_relatorio, reprovacoes, gsd_limit)

        return {self.OUTPUT_LAYER: dest_id, self.OUTPUT_REPORT: caminho_relatorio}

    # =========================================================================
    # MÉTODOS AUXILIARES DE CÁLCULO E AUDITORIA
    # =========================================================================

    def _extrair_altitude_terreno(self, raster_provider, ponto_xy):
        """Extrai o valor do pixel da banda 1 do raster na coordenada fornecida."""
        valor, res = raster_provider.sample(ponto_xy, 1)
        if res:
            return float(valor)
        return None

    def _calcular_gsd(self, sensor_width, focal_length, image_width, altura_voo_relativa):
        """
        Calcula o GSD (em centímetros).
        Assume-se que a altura de voo relativa está em metros e a largura do sensor e distância focal em milímetros.
        """
        if focal_length == 0 or image_width == 0:
            raise Exception("Distância focal ou largura da imagem não podem ser zero.")
        
        # Conversão da altura para mm para alinhar com o sensor e a focal
        altura_mm = altura_voo_relativa * 1000 
        gsd_mm = (sensor_width * altura_mm) / (focal_length * image_width)
        
        # Retorna em centímetros
        return gsd_mm / 10.0

    def _validar_gsd(self, gsd_calculado, limite):
        """Retorna 'Reprovado' se o GSD exceder a tolerância estabelecida."""
        if gsd_calculado > limite:
            return "Reprovado"
        return None

    def _gerar_relatorio_txt(self, path, reprovacoes, limite):
        """Gera o relatório em .txt, listando apenas os centros perspectivos reprovados."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("===============================================================\n")
                f.write("       RELATÓRIO DE AUDITORIA DE RESOLUÇÃO ESPACIAL (GSD)\n")
                f.write("===============================================================\n")
                f.write(f"Data: {agora}\n")
                f.write(f"Limite Máximo de GSD Tolerável: {limite} cm\n")
                f.write("---------------------------------------------------------------\n\n")

                if not reprovacoes:
                    f.write("✓ SUCESSO: Nenhuma fotografia foi reprovada. Todos os valores de GSD estão dentro do limite tolerável.\n")
                else:
                    f.write(f"Total de Fotos Reprovadas: {len(reprovacoes)}\n\n")
                    f.write(f"{'FOTO / IMAGEM':<40} | {'INCONFORMIDADE DETECTADA'}\n")
                    f.write("-" * 80 + "\n")
                    for foto, erro in sorted(reprovacoes.items()):
                        f.write(f"{foto:<40} | {erro}\n")
                
                f.write("\n---------------------------------------------------------------\n")
                f.write("Fim do Relatório de Fiscalização SEI.\n")
        except IOError as e:
            raise QgsProcessingException(f"Erro ao salvar o relatório: {str(e)}")