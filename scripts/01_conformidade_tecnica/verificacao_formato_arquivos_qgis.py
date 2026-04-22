import os
from osgeo import gdal

# ==========================================
# INSIRA O CAMINHO DA SUA PASTA AQUI ABAIXO
# ==========================================
pasta_alvo = r"Y:\LOTE01\FOTO\ENT_01\REV_00\RGB_16bits"


gdal.UseExceptions()

def verificar_integridade_imagens_v2(diretorio):
    extensoes_alvo = ('.tif', '.tiff', '.geotif', '.geotiff')
    arquivos_invalidos = []
    total_verificados = 0
    pastas_lidas = 0

    print(f"Iniciando varredura profunda no diretório:\n{diretorio}\n")
    print("Aguarde, processando a árvore de pastas...\n")

    # O parâmetro followlinks=True força o Python a entrar em links simbólicos/atalhos de rede
    for raiz, _, arquivos in os.walk(diretorio, followlinks=True):
        pastas_lidas += 1
        
        # DESCOMENTE A LINHA ABAIXO (remova o #) se quiser ver no console cada pasta que ele acessa:
        # print(f"Lendo: {raiz} -> {len(arquivos)} arquivo(s) no total (todas as extensões)")

        for arquivo in arquivos:
            if arquivo.lower().endswith(extensoes_alvo):
                total_verificados += 1
                caminho_completo = os.path.join(raiz, arquivo)
                
                try:
                    dataset = gdal.Open(caminho_completo, gdal.GA_ReadOnly)
                    if dataset is None:
                        arquivos_invalidos.append((caminho_completo, "O GDAL não conseguiu abrir o arquivo."))
                        continue
                        
                    if dataset.RasterCount == 0:
                        arquivos_invalidos.append((caminho_completo, "O arquivo foi aberto, mas não possui bandas (RasterCount = 0)."))
                    
                    dataset = None
                    
                except Exception as e:
                    erro_msg = str(e).strip()
                    arquivos_invalidos.append((caminho_completo, f"Erro GDAL: {erro_msg}"))

    # --- GERAÇÃO DO RELATÓRIO ---
    print("\n" + "=" * 50)
    print(" " * 12 + "RELATÓRIO DE VARREDURA")
    print("=" * 50)
    print(f"Total de pastas verificadas: {pastas_lidas}")
    print(f"Total de imagens TIF/GeoTIFF verificadas: {total_verificados}\n")
    
    if total_verificados == 0:
        print("Resultado: Nenhuma imagem encontrada. Verifique se as imagens estão baixadas localmente (não apenas na nuvem) ou questões de permissão.")
    elif not arquivos_invalidos:
        print("Resultado: SUCESSO! Todas as imagens verificadas estão no formato correto.")
    else:
        print(f"Resultado: ATENÇÃO! Foram encontrados problemas em {len(arquivos_invalidos)} arquivo(s):\n")
        for arq, motivo in arquivos_invalidos:
            print(f"-> Arquivo: {arq}")
            print(f"   Motivo: {motivo}\n")
    print("=" * 50)

# Executa a função
verificar_integridade_imagens_v2(pasta_alvo)