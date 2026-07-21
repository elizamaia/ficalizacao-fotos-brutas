# -*- coding: utf-8 -*-
"""
Plugin QGIS para Análise Espacial de Sobreposição (Longitudinal e Lateral)

Este algoritmo avalia poligonais (footprints) de fotografias aéreas brutas para validar as
sobreposições longitudinais e laterais. Ele processa a geometria dos voos e gera uma 
camada de auditoria contendo as porcentagens de sobreposição calculadas e um relatório 
textual (.txt) de conformidade técnica, acusando erros de forma independente para cada direção.

Cálculos:
    - Sobreposição Longitudinal: (Área de interseção com o vizinho mais próximo ao Norte/Sul / Área total) * 100
    - Sobreposição Lateral: (Área de interseção gerada por UnaryUnion com todos vizinhos a Leste/Oeste / Área total) * 100
    - Vetor de Direção: Avaliação de vizinhança baseada no deslocamento (dx, dy) dos centroides.

Autor: Mestrado - Scripts para QGIS (Agente Gerador)
Data: 2026
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
    QgsField,
    QgsFields,
    QgsSpatialIndex,
    QgsGeometry,
    QgsUnitTypes,
    QgsFeatureSink,
    QgsFeature
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
import math
from datetime import datetime


class AnaliseSobreposicaoEspacial(QgsProcessingAlgorithm):

    # =========================================================================
    # DEFINIÇÃO DE CONSTANTES DE PARÂMETROS
    # =========================================================================
    INPUT_LAYER = 'INPUT_LAYER'
    FIELD_NAME = 'FIELD_NAME'
    LONG_TARGET = 'LONG_TARGET'
    LAT_TARGET = 'LAT_TARGET'
    TOLERANCE = 'TOLERANCE'
    OUTPUT_LAYER = 'OUTPUT_LAYER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'

    # =========================================================================
    # MÉTODOS OBRIGATÓRIOS DA API QGIS
    # =========================================================================
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

    # =========================================================================
    # INICIALIZAÇÃO DE PARÂMETROS
    # =========================================================================
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT_LAYER, self.tr("Camada de Polígonos (Footprints)"), types=[QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(self.FIELD_NAME, self.tr("Campo com o nome da imagem/arquivo"), parentLayerParameterName=self.INPUT_LAYER))
        self.addParameter(QgsProcessingParameterNumber(self.LONG_TARGET, self.tr("Sobreposição Longitudinal Alvo (%)"), defaultValue=60))
        self.addParameter(QgsProcessingParameterNumber(self.LAT_TARGET, self.tr("Sobreposição Lateral Alvo (%)"), defaultValue=30))
        self.addParameter(QgsProcessingParameterNumber(self.TOLERANCE, self.tr("Limite de Tolerância (- %)"), defaultValue=3))
        
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LAYER, self.tr("Camada de Auditoria Espacial")))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_REPORT, self.tr("Relatório de Reprovações (.txt)"), fileFilter='Text files (*.txt)'))

    # =========================================================================
    # MÉTODO PRINCIPAL DE PROCESSAMENTO
    # =========================================================================
    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        campo_id = self.parameterAsString(parameters, self.FIELD_NAME, context)
        long_alvo = self.parameterAsDouble(parameters, self.LONG_TARGET, context)
        lat_alvo = self.parameterAsDouble(parameters, self.LAT_TARGET, context)
        tolerancia = self.parameterAsDouble(parameters, self.TOLERANCE, context)
        caminho_relatorio = self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context)

        # --------------------------------------------------------------------
        # VALIDAÇÃO DE CRS (UTM)
        # --------------------------------------------------------------------
        if source.crs().isGeographic() or source.crs().mapUnits() != QgsUnitTypes.DistanceMeters:
            raise QgsProcessingException(self.tr("ERRO CRÍTICO: A camada deve estar em coordenadas planimétricas (UTM - Metros). O código não pode prosseguir."))

        # Limite inferior aceitável
        lim_long_min = long_alvo - tolerancia
        lim_lat_min = lat_alvo - tolerancia

        # --------------------------------------------------------------------
        # PREPARAR CAMPOS DE SAÍDA
        # --------------------------------------------------------------------
        in_fields = source.fields()
        out_fields = QgsFields()
        
        for field in in_fields:
            out_fields.append(field)
            
        new_fields = [
            QgsField('sob_long_N', QVariant.Double), QgsField('sob_long_S', QVariant.Double),
            QgsField('sob_lat_L', QVariant.Double), QgsField('sob_lat_O', QVariant.Double),
            QgsField('qc_long_N', QVariant.String), QgsField('qc_long_S', QVariant.String),
            QgsField('qc_lat_L', QVariant.String), QgsField('qc_lat_O', QVariant.String)
        ]
        
        for field in new_fields: 
            out_fields.append(field)

        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT_LAYER, context, out_fields, source.wkbType(), source.crs())

        feedback.pushInfo("Construindo índice espacial e dicionário...")
        
        index = QgsSpatialIndex(source.getFeatures())
        dicionario_feicoes = {f.id(): f for f in source.getFeatures()}
        total = len(dicionario_feicoes)
        
        reprovacoes = {}

        feedback.pushInfo("Iniciando cálculos analíticos de interseção e merge...")

        for i, (fid, feat) in enumerate(dicionario_feicoes.items()):
            if feedback.isCanceled(): break

            try:
                geom = feat.geometry()
                nome_foto = str(feat[campo_id]) if feat[campo_id] else f"Feicao_{fid}"
                
                val_n, val_s, val_l, val_o = self._calcular_sobreposicoes(geom, fid, index, dicionario_feicoes)

                # Validação independente para cada direção
                status_n = self._validar(val_n, lim_long_min)
                status_s = self._validar(val_s, lim_long_min)
                status_l = self._validar(val_l, lim_lat_min)
                status_o = self._validar(val_o, lim_lat_min)

                erros = []
                if status_n: erros.append(f"Norte ({val_n:.1f}%)")
                if status_s: erros.append(f"Sul ({val_s:.1f}%)")
                if status_l: erros.append(f"Leste ({val_l:.1f}%)")
                if status_o: erros.append(f"Oeste ({val_o:.1f}%)")
                
                if erros:
                    reprovacoes[nome_foto] = erros

                out_feat = QgsFeature(out_fields)
                out_feat.setGeometry(geom)
                
                atributos_completos = feat.attributes() + [
                    val_n, 
                    val_s, 
                    val_l, 
                    val_o,
                    status_n,
                    status_s,
                    status_l,
                    status_o
                ]
                
                out_feat.setAttributes(atributos_completos)
                sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

            except Exception as e:
                feedback.reportError(f"Falha ao processar feição {fid}: {str(e)}")
                reprovacoes[f"Feicao_{fid}"] = [f"ERRO DE PROCESSAMENTO: {str(e)}"]

            feedback.setProgress(int((i / total) * 100))

        self._gerar_relatorio_txt(caminho_relatorio, reprovacoes, long_alvo, lat_alvo, tolerancia)

        return {self.OUTPUT_LAYER: dest_id, self.OUTPUT_REPORT: caminho_relatorio}

    # =========================================================================
    # MÉTODOS AUXILIARES DE CÁLCULO E AUDITORIA
    # =========================================================================
    def _calcular_sobreposicoes(self, geom, fid, index, dict_feicoes):
        centro = geom.centroid().asPoint()
        ids_vizinhos = index.intersects(geom.boundingBox())
        
        cands_norte = []
        cands_sul = []
        geoms_leste = []
        geoms_oeste = []

        area_principal = geom.area()
        if area_principal == 0: return 0.0, 0.0, 0.0, 0.0

        for vid in ids_vizinhos:
            if vid == fid: continue 
            
            viz_geom = dict_feicoes[vid].geometry()
            if not geom.intersects(viz_geom): continue 
            
            viz_centro = viz_geom.centroid().asPoint()
            dx = viz_centro.x() - centro.x()
            dy = viz_centro.y() - centro.y()
            distancia = math.hypot(dx, dy)
            
            if distancia < 0.1: continue 

            if abs(dy) > abs(dx):
                if dy > 0: cands_norte.append((distancia, viz_geom))
                else: cands_sul.append((distancia, viz_geom))
            else:
                if dx > 0: geoms_leste.append(viz_geom)
                else: geoms_oeste.append(viz_geom)

        val_n = val_s = 0.0
        if cands_norte:
            geom_mais_prox_norte = min(cands_norte, key=lambda x: x[0])[1]
            val_n = (geom.intersection(geom_mais_prox_norte).area() / area_principal) * 100
            
        if cands_sul:
            geom_mais_prox_sul = min(cands_sul, key=lambda x: x[0])[1]
            val_s = (geom.intersection(geom_mais_prox_sul).area() / area_principal) * 100

        val_l = val_o = 0.0
        if geoms_leste:
            inters_leste = [geom.intersection(g) for g in geoms_leste]
            merge_leste = QgsGeometry.unaryUnion(inters_leste)
            val_l = (merge_leste.area() / area_principal) * 100
            
        if geoms_oeste:
            inters_oeste = [geom.intersection(g) for g in geoms_oeste]
            merge_oeste = QgsGeometry.unaryUnion(inters_oeste)
            val_o = (merge_oeste.area() / area_principal) * 100

        return val_n, val_s, val_l, val_o

    def _validar(self, valor, limite_inferior):
        """Retorna 'Reprovado' se o valor não atingir a tolerância, senão retorna nulo (None)"""
        if valor < limite_inferior: 
            return "Reprovado"
        return None

    def _gerar_relatorio_txt(self, path, reprovacoes, long, lat, tol):
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("===============================================================\n")
                f.write("       RELATÓRIO DE AUDITORIA DE SOBREPOSIÇÃO ESPACIAL\n")
                f.write("===============================================================\n")
                f.write(f"Data: {agora}\n")
                f.write(f"Requisito Mínimo: Longitudinal {long-tol}% | Lateral {lat-tol}%\n")
                f.write(f"Total de Fotos com Inconformidade: {len(reprovacoes)}\n")
                f.write("---------------------------------------------------------------\n\n")

                if not reprovacoes:
                    f.write("✓ SUCESSO: Todas as fotos atingem ou superam a sobreposição mínima exigida em todas as direções.\n")
                else:
                    f.write(f"{'FOTO / IMAGEM':<40} | {'INCONFORMIDADES DETECTADAS'}\n")
                    f.write("-" * 80 + "\n")
                    for foto, erros in sorted(reprovacoes.items()):
                        f.write(f"{foto:<40} | {' e '.join(erros)}\n")
                
                f.write("\n---------------------------------------------------------------\n")
                f.write("Fim do Relatório de Fiscalização SEI.\n")
        except IOError as e:
            raise QgsProcessingException(f"Erro ao salvar o relatório: {str(e)}")