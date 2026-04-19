# -*- coding: utf-8 -*-

"""
SCRIPT PARA VERIFICAR PROFUNDIDADE DE BITS DE IMAGENS TIFF EM LOTE (COM SUBPASTAS)
==================================================================================
COMO USAR:
1. Copie e cole este código no terminal Python do QGIS (Plugins > Terminal Python).
2. Altere o caminho na variável 'caminho_da_pasta_mae' abaixo para a sua pasta principal.
   - O script irá verificar esta pasta e TODAS as suas subpastas.
   - Exemplo Windows: 'C:/Users/SeuUsuario/Desktop/Projetos_Geo'
   - Exemplo Linux/Mac: '/home/seu_usuario/documentos/projetos_geo'
3. Clique em 'Executar Script' no terminal do QGIS.
4. A lista de arquivos que NÃO são 16 bits será impressa, incluindo seu caminho relativo.
"""

import os
from PIL import Image
from PIL.TiffTags import TAGS

# --------------------------------------------------------------------------
# ▼▼▼ EDITAR AQUI ▼▼▼
# Cole o caminho completo para a sua pasta MÃE abaixo.
caminho_da_pasta_mae = r'Z:\LOTE01\ORTO\ENT_04A\REV_00\RGB'
# ▲▲▲ EDITAR AQUI ▲▲▲
# --------------------------------------------------------------------------


def verificar_bits_tiff_recursivo_qgis(pasta_mae):
    """
    Verifica recursivamente todos os arquivos TIFF em uma pasta mãe e suas subpastas,
    listando aqueles que não são de 16 bits.
    """
    if not os.path.isdir(pasta_mae):
        print(f"ERRO: O caminho especificado não é uma pasta válida.\nVerifique o caminho: '{pasta_mae}'")
        return

    print(f"Iniciando verificação recursiva na pasta mãe: {pasta_mae}\n")
    
    Image.MAX_IMAGE_PIXELS = None
    
    arquivos_nao_16bit = []
    arquivos_com_erro = []
    total_verificados = 0

    # Usa os.walk() para percorrer a árvore de diretórios (pasta mãe e subpastas).
    for dirpath, _, filenames in os.walk(pasta_mae):
        for nome_arquivo in filenames:
            if nome_arquivo.lower().endswith(('.tif', '.tiff')):
                total_verificados += 1
                caminho_completo = os.path.join(dirpath, nome_arquivo)
                # Pega o caminho relativo para uma exibição mais limpa.
                caminho_relativo = os.path.relpath(caminho_completo, pasta_mae)
                
                try:
                    with Image.open(caminho_completo) as img:
                        meta_dict = {TAGS.get(key, key): img.tag_v2.get(key) for key in img.tag_v2}
                        bits_por_amostra = meta_dict.get('BitsPerSample')

                        if bits_por_amostra is None:
                             arquivos_com_erro.append((caminho_relativo, "Tag 'BitsPerSample' não encontrada."))
                             continue

                        if isinstance(bits_por_amostra, tuple):
                            if any(b != 16 for b in bits_por_amostra):
                                arquivos_nao_16bit.append((caminho_relativo, bits_por_amostra))
                        elif bits_por_amostra != 16:
                            arquivos_nao_16bit.append((caminho_relativo, bits_por_amostra))

                except Exception as e:
                    arquivos_com_erro.append((caminho_relativo, str(e)))

    # --- Exibição dos Resultados ---
    print("==================================================")
    print("          RESULTADO DA VERIFICAÇÃO")
    print("==================================================")
    print(f"Total de arquivos TIFF verificados: {total_verificados}")

    if not arquivos_nao_16bit and not arquivos_com_erro:
        print("\n✅ Ótima notícia! Todos os arquivos TIFF encontrados são de 16 bits.")
    
    if arquivos_nao_16bit:
        print("\n🟡 ATENÇÃO: Os seguintes arquivos NÃO são de 16 bits:")
        print("--------------------------------------------------------------------------")
        for caminho, bits in arquivos_nao_16bit:
            print(f"- Arquivo: {caminho:<55} | Bits: {bits}")
        print("--------------------------------------------------------------------------")
    
    if arquivos_com_erro:
        print("\n🔴 ERRO: Não foi possível processar os seguintes arquivos:")
        print("--------------------------------------------------------------------------")
        for caminho, erro in arquivos_com_erro:
            print(f"- Arquivo: {caminho:<55} | Motivo: {erro}")
        print("--------------------------------------------------------------------------")

    print("\nVerificação concluída.")


# --- Execução do Script ---
verificar_bits_tiff_recursivo_qgis(caminho_da_pasta_mae)