# -*- coding: utf-8 -*-
"""
Created on Tue Jul  8 15:15:12 2025

@author: elizamaia
"""

import os
import geopandas as gpd
import rasterio
from rasterio import features
import numpy as np

# --- CONFIGURAÇÃO ---
# AJUSTE ESTAS VARIÁVEIS DE ACORDO COM SEU PROJETO

# 1. Caminho para o seu shapefile único com todas as poligonais
SHAPEFILE_PATH = r'S:\digeo\CARTGEO\PROJETOS\INTERNOS\NOVO_MAPEAMENTO_II\MAT_APOIO\TEMP\nuvens_sombras_lote01_entrega01.shp'

# 2. Pasta raiz onde estão suas fotos aéreas (o script buscará dentro das subpastas)
# Use a pasta que contém as imagens que você quer usar no treino (ex: RGIR)
RASTER_ROOT_FOLDER = r'Y:\LOTE01\FOTO\ENT_01\REV_00\CIR_16bits'

# 3. Pasta onde as máscaras geradas serão salvas
OUTPUT_FOLDER = r'S:\digeo\CARTGEO\PROJETOS\INTERNOS\NOVO_MAPEAMENTO_II\MAT_APOIO\TEMP\mascaras_nuvens_sombras'

# 4. Nomes das colunas (campos) no seu shapefile
#    (verifique os nomes exatos na tabela de atributos do QGIS)
FILENAME_FIELD = 'nome_tif' # Coluna que tem o nome do arquivo da foto (ex: 'foto_123.tif')
CLASS_FIELD = 'tipo_ocorr'         # Coluna que diz se é 'nuvem' ou 'sombra'

# --- FIM DA CONFIGURAÇÃO ---

def find_file(root_folder, filename):
    """Procura recursivamente por um arquivo em uma pasta raiz."""
    for root, dirs, files in os.walk(root_folder):
        if filename in files:
            return os.path.join(root, filename)
    return None

def create_masks():
    """
    Função principal para ler o shapefile e gerar as máscaras para cada foto.
    """
    print(f"Carregando shapefile de: {SHAPEFILE_PATH}")
    try:
        gdf = gpd.read_file(SHAPEFILE_PATH)
    except Exception as e:
        print(f"Erro ao ler o shapefile: {e}")
        return

    # Garante que a pasta de saída exista
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # Pega a lista de nomes de arquivos únicos da coluna especificada
    unique_filenames = gdf[FILENAME_FIELD].unique()
    print(f"Encontradas {len(unique_filenames)} fotos únicas para processar.")

    for i, filename in enumerate(unique_filenames):
        print(f"\nProcessando foto {i+1}/{len(unique_filenames)}: {filename}")

        # Encontra o caminho completo da foto original
        raster_path = find_file(RASTER_ROOT_FOLDER, filename)
        if not raster_path:
            print(f"AVISO: Arquivo de imagem '{filename}' não encontrado. Pulando.")
            continue
        
        print(f"  > Imagem encontrada em: {raster_path}")

        try:
            with rasterio.open(raster_path) as src:
                # Copia os metadados da foto de origem (georreferenciamento, etc.)
                meta = src.meta.copy()
                
                # Atualiza os metadados para a máscara de saída
                # 8-bit é suficiente (0, 1, 2) e economiza espaço
                meta.update(dtype=rasterio.uint8, count=1, compress='lzw')

                output_mask_path = os.path.join(OUTPUT_FOLDER, filename)
                
                with rasterio.open(output_mask_path, 'w+', **meta) as dst:
                    # Começa com uma máscara toda preta (valor 0 para fundo)
                    mask_array = np.zeros(src.shape, dtype=rasterio.uint8)

                    # Filtra os polígonos apenas para o arquivo atual
                    file_gdf = gdf[gdf[FILENAME_FIELD] == filename]

                    # Separa geometrias de sombras e nuvens
                    shadow_geoms = file_gdf[file_gdf[CLASS_FIELD].str.lower() == '02'].geometry
                    cloud_geoms = file_gdf[file_gdf[CLASS_FIELD].str.lower() == '01'].geometry

                    # Queima as sombras primeiro com valor 2
                    if not shadow_geoms.empty:
                        print(f"  > Rasterizando {len(shadow_geoms)} polígonos de sombra...")
                        features.rasterize(
                            shapes=shadow_geoms,
                            out=mask_array,
                            fill=0, # Não muda o que já está lá fora dos polígonos
                            out_shape=src.shape,
                            transform=src.transform,
                            default_value=2
                        )

                    # Queima as nuvens por cima com valor 1
                    if not cloud_geoms.empty:
                        print(f"  > Rasterizando {len(cloud_geoms)} polígonos de nuvem...")
                        features.rasterize(
                            shapes=cloud_geoms,
                            out=mask_array,
                            fill=0,
                            out_shape=src.shape,
                            transform=src.transform,
                            default_value=1
                        )
                    
                    # Escreve o array final no arquivo da máscara
                    dst.write(mask_array, 1)
                    print(f"  > Máscara salva em: {output_mask_path}")

        except Exception as e:
            print(f"ERRO ao processar o arquivo '{filename}': {e}")
            continue

    print("\nProcesso concluído!")

if __name__ == '__main__':
    create_masks()