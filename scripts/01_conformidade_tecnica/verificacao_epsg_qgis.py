# -*- coding: utf-8 -*-

"""
SCRIPT PARA VERIFICAR O EPSG DE IMAGENS TIFF EM LOTE (COM SUBPASTAS)
======================================================================
COMO USAR:
1. Copie e cole este código no terminal Python do QGIS (Plugins > Terminal Python).
2. Altere o caminho na variável 'caminho_da_pasta_mae' abaixo.
3. O script irá verificar esta pasta e TODAS as suas subpastas.
4. O EPSG desejado já está definido como 4674 (SIRGAS 2000), mas pode ser alterado.
5. Clique em 'Executar Script'. A lista de arquivos será impressa no console.
"""

import os
# A biblioteca 'osgeo' (GDAL/OGR) é padrão no QGIS.
from osgeo import gdal, osr

# --------------------------------------------------------------------------
# ▼▼▼ EDITAR AQUI ▼▼▼
# Cole o caminho completo para a sua pasta MÃE abaixo.
caminho_da_pasta_mae = r'Z:\LOTE01\ORTO\ENT_04A\REV_00\RGIR'

# Defina o código EPSG que você deseja verificar.
epsg_desejado = 4674
# ▲▲▲ EDITAR AQUI ▲▲▲
# --------------------------------------------------------------------------


def verificar_epsg_tiff_recursivo(pasta_mae, epsg_alvo):
    """
    Verifica recursivamente o CRS de todos os arquivos TIFF em uma pasta mãe
    e suas subpastas, comparando com um EPSG alvo.
    """
    if not os.path.isdir(pasta_mae):
        print(f"ERRO: O caminho especificado não é uma pasta válida: '{pasta_mae}'")
        return

    print(f"Iniciando verificação de EPSG na pasta mãe: {pasta_mae}")
    print(f"Procurando por arquivos com EPSG: {epsg_alvo} (SIRGAS 2000)\n")
    
    # Listas para categorizar os arquivos
    arquivos_corretos = []
    arquivos_com_epsg_diferente = []
    arquivos_sem_epsg = []
    arquivos_com_erro = []
    total_verificados = 0

    # Desativa o log de erros do GDAL no console para uma saída mais limpa
    gdal.UseExceptions()
    gdal.PushErrorHandler('CPLQuietErrorHandler')

    for dirpath, _, filenames in os.walk(pasta_mae):
        for nome_arquivo in filenames:
            if nome_arquivo.lower().endswith(('.tif', '.tiff')):
                total_verificados += 1
                caminho_completo = os.path.join(dirpath, nome_arquivo)
                caminho_relativo = os.path.relpath(caminho_completo, pasta_mae)
                
                try:
                    dataset = gdal.Open(caminho_completo, gdal.GA_ReadOnly)
                    if dataset is None:
                        arquivos_com_erro.append((caminho_relativo, "GDAL não conseguiu abrir o arquivo."))
                        continue
                    
                    # Pega a projeção em formato WKT (Well-Known Text)
                    wkt = dataset.GetProjection()
                    
                    if not wkt:
                        arquivos_sem_epsg.append(caminho_relativo)
                    else:
                        # Cria um objeto de referência espacial a partir do WKT
                        spatial_ref = osr.SpatialReference()
                        spatial_ref.ImportFromWkt(wkt)
                        
                        # Tenta extrair o código EPSG
                        codigo_epsg_encontrado = spatial_ref.GetAuthorityCode(None)
                        if codigo_epsg_encontrado:
                            codigo_epsg_encontrado = int(codigo_epsg_encontrado) # Converte para número

                        # Compara com o EPSG alvo
                        if codigo_epsg_encontrado == epsg_alvo:
                            arquivos_corretos.append(caminho_relativo)
                        else:
                            nome_srs = spatial_ref.GetAuthorityName(None) or "N/A"
                            info_encontrada = f"EPSG:{codigo_epsg_encontrado} ({nome_srs})"
                            arquivos_com_epsg_diferente.append((caminho_relativo, info_encontrada))
                    
                    # Libera o arquivo
                    dataset = None

                except Exception as e:
                    arquivos_com_erro.append((caminho_relativo, str(e)))

    # Reativa o log de erros padrão
    gdal.PopErrorHandler()

    # --- Exibição dos Resultados ---
    print("==================================================")
    print("          RESULTADO DA VERIFICAÇÃO DE EPSG")
    print("==================================================")
    print(f"Total de arquivos TIFF verificados: {total_verificados}\n")

    if arquivos_com_epsg_diferente:
        print(f"🟡 ATENÇÃO: Arquivos com EPSG diferente de {epsg_alvo}:")
        print("--------------------------------------------------------------------------")
        for caminho, epsg_info in arquivos_com_epsg_diferente:
            print(f"- Arquivo: {caminho:<50} | Encontrado: {epsg_info}")
        print("--------------------------------------------------------------------------\n")

    if arquivos_sem_epsg:
        print("🟠 ATENÇÃO: Arquivos sem sistema de referência de coordenadas (CRS) definido:")
        print("--------------------------------------------------------------------------")
        for caminho in arquivos_sem_epsg:
            print(f"- Arquivo: {caminho}")
        print("--------------------------------------------------------------------------\n")
        
    if arquivos_com_erro:
        print("🔴 ERRO: Não foi possível processar os seguintes arquivos:")
        print("--------------------------------------------------------------------------")
        for caminho, erro in arquivos_com_erro:
            print(f"- Arquivo: {caminho:<50} | Motivo: {erro}")
        print("--------------------------------------------------------------------------\n")
    
    num_corretos = len(arquivos_corretos)
    if num_corretos > 0:
        print(f"✅ Boa notícia: {num_corretos} arquivo(s) está(ão) com o EPSG {epsg_alvo} correto.")
    
    if num_corretos == total_verificados and total_verificados > 0:
        print("\n🎉 Perfeito! Todos os arquivos TIFF verificados estão com o CRS correto!")

    print("\nVerificação de EPSG concluída.")


# --- Execução do Script ---
verificar_epsg_tiff_recursivo(caminho_da_pasta_mae, epsg_desejado)