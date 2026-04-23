# -*- coding: utf-8 -*-

"""
Plugin QGIS para Análise Espacial de Sobreposição (Longitudinal e Lateral)

Este algoritmo automatiza a verificação geométrica do recobrimento entre fotos 
aéreas brutas. Diferente de verificações de metadados, este script realiza 
cálculos de interseção espacial entre polígonos (footprints).

Regras de Auditoria:
    - Validação de CRS: O vetor DEVE estar em coordenadas projetadas (UTM).
    - Tolerância Bidirecional: Valores fora do intervalo [Alvo ± Tolerância] 
      são reprovados.
    - Análise Lateral Robusta: Utiliza UnaryUnion para tratar faixas adjacentes.

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 22/04/2026
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsWkbTypes,
    QgsField,
    QgsSpatialIndex,
    QgsGeometry,
    QgsPointXY,
    QgsUnitTypes,
    QgsFeatureSink
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
import os
from datetime import datetime


class AnaliseSobreposicaoEspacial(QgsProcessingAlgorithm):
    """
    Algoritmo para cálculo e auditoria de sobreposição de voo aerofotogramétrico.
    """

    # Constantes de Parâmetros
    INPUT_LAYER = 'INPUT_LAYER'
    FIELD_NAME = 'FIELD_NAME'
    LONG_TARGET = 'LONG_TARGET'
    LAT_TARGET = 'LAT_TARGET'
    TOLERANCE = 'TOLERANCE'
    OUTPUT_LAYER = 'OUTPUT_LAYER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return AnaliseSobreposicaoEspacial()

    def name(self):
        return 'analise_sobreposicao_fotos'

    def displayName(self):
        return self.tr("Fotos Brutas - Vetor - Sobreposição Longitudinal e Lateral")

    def group(self):
        return self.tr('Fiscalização Mapeamento SEI')

    def groupId(self):
        return 'fiscalizacao_sei'

    def initAlgorithm(self, config=None):
        # 1. Camada de Entrada
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr("Camada de Polígonos (Footprints)"),
                types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        # 2. Selecionar Campo do Nome do Arquivo
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_NAME,
                self.tr("Campo com o nome da imagem/arquivo"),
                parentLayerParameterName=self.INPUT_LAYER
            )
        )

        # 3 e 4. Alvos de Sobreposição
        self.addParameter(QgsProcessingParameterNumber(self.LONG_TARGET, self.tr("Sobreposição Longitudinal Alvo (%)"), defaultValue=60))
        self.addParameter(QgsProcessingParameterNumber(self.LAT_TARGET, self.tr("Sobreposição Lateral Alvo (%)"), defaultValue=30))

        # 5. Tolerância
        self.addParameter(QgsProcessingParameterNumber(self.TOLERANCE, self.tr("Limite de Tolerância (± %)"), defaultValue=3))

        # 6 e 7. Saídas
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LAYER, self.tr("Camada de Auditoria Espacial")))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_REPORT, self.tr("Relatório de Reprovações (.txt)"), fileFilter='Text files (*.txt)'))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        campo_id = self.parameterAsString(parameters, self.FIELD_NAME, context)
        long_alvo = self.parameterAsDouble(parameters, self.LONG_TARGET, context)
        lat_alvo = self.parameterAsDouble(parameters, self.LAT_TARGET, context)
        tolerancia = self.parameterAsDouble(parameters, self.TOLERANCE, context)
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # ======================================
        # VALIDAÇÃO DE CRS (UTM)
        # ======================================
        if source.crs().isGeographic():
            raise QgsProcessingException(self.tr("ERRO: A camada deve estar em coordenadas UTM (Métricas). O CRS atual é Geográfico."))
        
        if source.crs().mapUnits() != QgsUnitTypes.DistanceMeters:
             raise QgsProcessingException(self.tr("ERRO: A unidade do CRS deve ser metros. Verifique a projeção do vetor."))

        # Limites Calculados
        lim_long = (long_alvo - tolerancia, long_alvo + tolerancia)
        lim_lat = (lat_alvo - tolerancia, lat_alvo + tolerancia)

        # Preparar Campos de Saída
        fields = source.fields()
        new_fields = [
            QgsField('sob_long_N', QVariant.Double), QgsField('sob_long_S', QVariant.Double),
            QgsField('sob_lat_L', QVariant.Double), QgsField('sob_lat_O', QVariant.Double),
            QgsField('qc_long', QVariant.String), QgsField('qc_lat', QVariant.String)
        ]
        for field in new_fields: fields.append(field)

        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT_LAYER, context, fields, source.wkbType(), source.crs())

        # Indexação Espacial
        index = QgsSpatialIndex(source.getFeatures())
        features = list(source.getFeatures())
        total = len(features)
        
        reprovacoes = {} # {nome_foto: [lista_de_problemas]}

        for i, feat in enumerate(features):
            if feedback.isCanceled(): break

            geom = feat.geometry()
            centroide = geom.centroid().asPoint()
            fid = feat.id()
            
            # Tratamento caso o campo seja nulo
            nome_foto = str(feat[campo_id]) if feat[campo_id] else f"Feição_{fid}"
            
            # Cálculos de Sobreposição (N, S, L, O)
            val_n = self._calc_overlap(geom, centroide, index, features, 'N', fid)
            val_s = self._calc_overlap(geom, centroide, index, features, 'S', fid)
            val_l = self._calc_overlap_lateral(geom, centroide, index, features, 'L', fid)
            val_o = self._calc_overlap_lateral(geom, centroide, index, features, 'O', fid)

            # Lógica de QC com Tolerância
            status_long = self._validar(max(val_n, val_s), lim_long)
            status_lat = self._validar(max(val_l, val_o), lim_lat)

            # Registro para o Relatório
            erros = []
            if status_long: erros.append(f"Longitudinal ({max(val_n, val_s):.1f}%) -> {status_long}")
            if status_lat: erros.append(f"Lateral ({max(val_l, val_o):.1f}%) -> {status_lat}")
            
            if erros:
                reprovacoes[nome_foto] = erros

            # Salvar na Camada
            out_feat = feat
            out_feat.setFields(fields)
            out_feat.setAttribute('sob_long_N', val_n)
            out_feat.setAttribute('sob_long_S', val_s)
            out_feat.setAttribute('sob_lat_L', val_l)
            out_feat.setAttribute('sob_lat_O', val_o)
            out_feat.setAttribute('qc_long', status_long if status_long else 'OK')
            out_feat.setAttribute('qc_lat', status_lat if status_lat else 'OK')
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

            feedback.setProgress(int((i / total) * 100))

        # Gerar Relatório TXT
        self._gerar_relatorio_txt(caminho_relatorio, reprovacoes, long_alvo, lat_alvo, tolerancia)

        return {self.OUTPUT_LAYER: dest_id, self.OUTPUT_REPORT: caminho_relatorio}

    # ======================================
    # MÉTODOS AUXILIARES
    # ======================================

    def _validar(self, valor, limites):
        """Verifica se o valor está fora do intervalo de tolerância."""
        if valor < limites[0]: return "Reprovado (Abaixo da Tolerância)"
        if valor > limites[1]: return "Reprovado (Acima da Tolerância)"
        return None

    def _calc_overlap(self, geom, centro, index, all_feats, direcao, fid):
        """Cálculo longitudinal (Simplificado por vizinho mais próximo na direção)."""
        offset = 50 # metros para busca de vizinho
        
        if direcao == 'N': pt = QgsPointXY(centro.x(), centro.y() + offset)
        elif direcao == 'S': pt = QgsPointXY(centro.x(), centro.y() - offset)
        else: return 0.0
        
        ponto_busca = QgsGeometry.fromPointXY(pt)
        ids_vizinhos = index.intersects(ponto_busca.boundingBox())
        
        inter_area = 0.0
        for vid in ids_vizinhos:
            if vid == fid: continue # Pula a si mesma
            vizinho = next((f for f in all_feats if f.id() == vid), None)
            if vizinho and vizinho.geometry().intersects(geom):
                inter_area = max(inter_area, vizinho.geometry().intersection(geom).area())
        
        return (inter_area / geom.area()) * 100 if geom.area() > 0 else 0

    def _calc_overlap_lateral(self, geom, centro, index, all_feats, direcao, fid):
        """Cálculo lateral usando UnaryUnion para robustez."""
        offset = 500 # busca maior para lateral
        
        if direcao == 'L': pt = QgsPointXY(centro.x() + offset, centro.y())
        elif direcao == 'O': pt = QgsPointXY(centro.x() - offset, centro.y())
        else: return 0.0
        
        ponto_busca = QgsGeometry.fromPointXY(pt)
        ids_vizinhos = index.intersects(ponto_busca.boundingBox())
        
        geometrias_intersecao = []
        for vid in ids_vizinhos:
            if vid == fid: continue # Pula a si mesma
            vizinho = next((f for f in all_feats if f.id() == vid), None)
            if vizinho and vizinho.geometry().intersects(geom):
                geometrias_intersecao.append(vizinho.geometry().intersection(geom))
        
        if not geometrias_intersecao: return 0.0
        uniao = QgsGeometry.unaryUnion(geometrias_intersecao)
        return (uniao.area() / geom.area()) * 100 if geom.area() > 0 else 0

    def _gerar_relatorio_txt(self, path, reprovacoes, long, lat, tol):
        """Gera o relatório de auditoria final."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        with open(path, 'w', encoding='utf-8') as f:
            f.write("===============================================================\n")
            f.write("       RELATÓRIO DE AUDITORIA DE SOBREPOSIÇÃO ESPACIAL\n")
            f.write("===============================================================\n")
            f.write(f"Data: {agora}\n")
            f.write(f"Configuração Alvo: Longitudinal {long}% | Lateral {lat}% (Tolerância ±{tol}%)\n")
            f.write(f"Total de Fotos com Inconformidade: {len(reprovacoes)}\n")
            f.write("---------------------------------------------------------------\n\n")

            if not reprovacoes:
                f.write("✓ SUCESSO: Todas as fotos estão dentro dos limites de tolerância.\n")
            else:
                f.write(f"{'FOTO / IMAGEM':<40} | {'INCONFORMIDADES DETECTADAS'}\n")
                f.write("-" * 80 + "\n")
                for foto, erros in sorted(reprovacoes.items()):
                    f.write(f"{foto:<40} | {' e '.join(erros)}\n")
            
            f.write("\n---------------------------------------------------------------\n")
            f.write("Fim do Relatório de Fiscalização SEI.\n")