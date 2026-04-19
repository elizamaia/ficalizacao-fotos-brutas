#---ATENÇÃO---
#O vetor deve estar em UTM

# --- INÍCIO DO CÓDIGO v6 (Correção no Merge Leste/Oeste) ---

import math
from qgis.core import (
    QgsProject, QgsWkbTypes, QgsField, QgsSpatialIndex, 
    QgsFeature, QgsGeometry
)
from qgis.PyQt.QtCore import QVariant

def calcular_e_avaliar_sobreposicao():
    """
    PARTE 1: Calcula a sobreposição de forma híbrida.
    PARTE 2: Avalia o resultado (QC) com lógica simplificada.
    CORREÇÃO: Usa unaryUnion() para um merge robusto da sobreposição lateral.
    """
    layer = iface.activeLayer()

    if not layer or layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        iface.messageBar().pushMessage("Erro", "Selecione uma camada de polígonos válida.", level=Qgis.Critical)
        return

    # --- 1. CONFIGURAÇÃO DOS CAMPOS ---
    campo_norte = 'sobrep_N'
    campo_sul = 'sobrep_S'
    campo_leste = 'sobrep_L'
    campo_oeste = 'sobrep_O'
    campo_qc_n = 'qc_long_N'
    campo_qc_s = 'qc_long_S'
    campo_qc_l = 'qc_lat_L'
    campo_qc_o = 'qc_lat_O'
    
    provider = layer.dataProvider()
    campos_para_adicionar = []
    todos_campos = [
        campo_norte, campo_sul, campo_leste, campo_oeste,
        campo_qc_n, campo_qc_s, campo_qc_l, campo_qc_o
    ]
    
    for nome_campo in todos_campos:
        if provider.fields().indexFromName(nome_campo) == -1:
            tipo = QVariant.Double if 'sobrep' in nome_campo else QVariant.String
            campos_para_adicionar.append(QgsField(nome_campo, tipo))

    if campos_para_adicionar:
        provider.addAttributes(campos_para_adicionar)
        layer.updateFields()
        print(f"{len(campos_para_adicionar)} campos criados.")

    # --- 2. PREPARAÇÃO ---
    print("Criando índice espacial...")
    spatial_index = QgsSpatialIndex(layer.getFeatures())
    all_features = {f.id(): f for f in layer.getFeatures()}
    print("Mapeamento de feições concluído.")

    # --- 3. CÁLCULO E AVALIAÇÃO ---
    layer.startEditing()
    total_features = len(all_features)
    print(f"Iniciando cálculo e QC para {total_features} feições...")
    
    idx_sobrep_n = layer.fields().indexFromName(campo_norte)
    idx_sobrep_s = layer.fields().indexFromName(campo_sul)
    idx_sobrep_l = layer.fields().indexFromName(campo_leste)
    idx_sobrep_o = layer.fields().indexFromName(campo_oeste)
    idx_qc_n = layer.fields().indexFromName(campo_qc_n)
    idx_qc_s = layer.fields().indexFromName(campo_qc_s)
    idx_qc_l = layer.fields().indexFromName(campo_qc_l)
    idx_qc_o = layer.fields().indexFromName(campo_qc_o)

    for i, current_feature in enumerate(all_features.values()):
        if i % 100 == 0:
            print(f"Processando {i}/{total_features}...")

        current_id = current_feature.id()
        current_geom = current_feature.geometry()
        
        if not current_geom or current_geom.isEmpty(): continue
            
        current_centroid = current_geom.centroid().asPoint()
        current_area = current_geom.area()
        if current_area == 0: continue

        vizinho_n_eleito, vizinho_s_eleito = None, None
        dist_n_min, dist_s_min = float('inf'), float('inf')
        vizinhos_l_geoms, vizinhos_o_geoms = [], []
        
        ids_candidatos = spatial_index.intersects(current_geom.boundingBox())

        for candidato_id in ids_candidatos:
            if candidato_id == current_id: continue
            candidato_feature = all_features[candidato_id]
            candidato_geom = candidato_feature.geometry()
            if not current_geom.intersects(candidato_geom): continue
            candidato_centroid = candidato_geom.centroid().asPoint()
            
            dx = candidato_centroid.x() - current_centroid.x()
            dy = candidato_centroid.y() - current_centroid.y()
            distancia = math.sqrt(dx**2 + dy**2)

            if abs(dy) > abs(dx):
                if dy > 0 and distancia < dist_n_min:
                    dist_n_min = distancia
                    vizinho_n_eleito = candidato_geom
                elif dy < 0 and distancia < dist_s_min:
                    dist_s_min = distancia
                    vizinho_s_eleito = candidato_geom
            else:
                if dx > 0: vizinhos_l_geoms.append(candidato_geom)
                else: vizinhos_o_geoms.append(candidato_geom)
        
        # --- PARTE 1: CALCULAR SOBREPOSIÇÃO ---
        sobrep_n, sobrep_s, sobrep_l, sobrep_o = 0.0, 0.0, 0.0, 0.0

        # Lógica N/S: Vizinho mais próximo (Mantida)
        if vizinho_n_eleito:
            sobrep_n = (current_geom.intersection(vizinho_n_eleito).area() / current_area) * 100
        if vizinho_s_eleito:
            sobrep_s = (current_geom.intersection(vizinho_s_eleito).area() / current_area) * 100

        # Lógica L/O: Merge com unaryUnion() (CORRIGIDA)
        if vizinhos_l_geoms:
            lista_intersecoes_l = [current_geom.intersection(g) for g in vizinhos_l_geoms]
            uniao_l = QgsGeometry.unaryUnion(lista_intersecoes_l)
            if not uniao_l.isEmpty():
                sobrep_l = (uniao_l.area() / current_area) * 100

        if vizinhos_o_geoms:
            lista_intersecoes_o = [current_geom.intersection(g) for g in vizinhos_o_geoms]
            uniao_o = QgsGeometry.unaryUnion(lista_intersecoes_o)
            if not uniao_o.isEmpty():
                sobrep_o = (uniao_o.area() / current_area) * 100
        
        # --- PARTE 2: AVALIAÇÃO DE QC (Lógica Simplificada) ---
        status_n = "Reprovado" if sobrep_n < 58.2 else None
        status_s = "Reprovado" if sobrep_s < 58.2 else None
        status_l = "Reprovado" if sobrep_l < 29.1 else None
        status_o = "Reprovado" if sobrep_o < 29.1 else None

        # --- ATUALIZAR TODOS OS VALORES NA CAMADA ---
        layer.changeAttributeValue(current_id, idx_sobrep_n, float(f'{sobrep_n:.2f}'))
        layer.changeAttributeValue(current_id, idx_sobrep_s, float(f'{sobrep_s:.2f}'))
        layer.changeAttributeValue(current_id, idx_sobrep_l, float(f'{sobrep_l:.2f}'))
        layer.changeAttributeValue(current_id, idx_sobrep_o, float(f'{sobrep_o:.2f}'))
        
        layer.changeAttributeValue(current_id, idx_qc_n, status_n)
        layer.changeAttributeValue(current_id, idx_qc_s, status_s)
        layer.changeAttributeValue(current_id, idx_qc_l, status_l)
        layer.changeAttributeValue(current_id, idx_qc_o, status_o)

    # --- FINALIZAR ---
    layer.commitChanges()
    print("Processamento e QC concluídos com sucesso!")
    iface.messageBar().pushMessage("Sucesso", "Cálculo e avaliação de sobreposição finalizados.", level=Qgis.Success, duration=7)


# --- Executa a função ---
calcular_e_avaliar_sobreposicao()

# --- FIM DO CÓDIGO ---