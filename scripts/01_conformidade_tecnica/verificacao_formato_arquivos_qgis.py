import os
from osgeo import gdal


# ==========================================
# INSIRA O CAMINHO DA SUA PASTA AQUI ABAIXO
# ==========================================
pasta_alvo = r"Y:\LOTE01\FOTO\ENT_01\REV_00\RGB_16bits\20230820"

gdal.UseExceptions()

def auditar_lote_imagens(diretorio):
    extensoes_alvo = ('.tif', '.tiff', '.geotif', '.geotiff')
    
    arquivos_corrompidos = []
    intrusos_por_extensao = {} # Vai contar quantos arquivos de cada formato errado existem
    
    total_tifs_verificados = 0
    total_intrusos = 0
    pastas_lidas = 0

    print(f"Iniciando auditoria completa no diretório:\n{diretorio}\n")
    print("Aguarde, processando a árvore de pastas...\n")

    for raiz, _, arquivos in os.walk(diretorio, followlinks=True):
        pastas_lidas += 1
        
        for arquivo in arquivos:
            caminho_completo = os.path.join(raiz, arquivo)
            
            # Pega a extensão do arquivo (ex: '.jpeg', '.txt')
            extensao = os.path.splitext(arquivo)[1].lower()
            
            # Se não tem extensão, agrupa como 'sem extensão'
            if not extensao:
                extensao = "[sem extensão]"

            # SE FOR TIFF -> Faz a validação profunda com GDAL
            if extensao in extensoes_alvo:
                total_tifs_verificados += 1
                
                try:
                    dataset = gdal.Open(caminho_completo, gdal.GA_ReadOnly)
                    if dataset is None:
                        arquivos_corrompidos.append((caminho_completo, "O GDAL não conseguiu abrir o arquivo."))
                        continue
                        
                    if dataset.RasterCount == 0:
                        arquivos_corrompidos.append((caminho_completo, "O arquivo não possui bandas (RasterCount = 0)."))
                    
                    dataset = None
                    
                except Exception as e:
                    erro_msg = str(e).strip()
                    arquivos_corrompidos.append((caminho_completo, f"Erro GDAL: {erro_msg}"))
            
            # SE NÃO FOR TIFF -> É um formato intruso/incorreto
            else:
                total_intrusos += 1
                if extensao in intrusos_por_extensao:
                    intrusos_por_extensao[extensao] += 1
                else:
                    intrusos_por_extensao[extensao] = 1

    # --- GERAÇÃO DO RELATÓRIO DE AUDITORIA ---
    print("=" * 60)
    print(" " * 15 + "RELATÓRIO DE AUDITORIA DE ENTREGA")
    print("=" * 60)
    print(f"Pastas verificadas: {pastas_lidas}")
    print(f"Imagens TIF/GeoTIFF avaliadas: {total_tifs_verificados}")
    print(f"Arquivos em OUTROS formatos (Intrusos): {total_intrusos}")
    print("-" * 60)
    
    # 1. Avaliação dos Intrusos (Formatos errados)
    if total_intrusos > 0:
        print("⚠️ ALERTA: Foram encontrados arquivos fora do formato padrão (.tif):")
        for ext, quantidade in intrusos_por_extensao.items():
            print(f"   -> {quantidade} arquivo(s) com formato {ext}")
        print("-" * 60)
    
    # 2. Avaliação dos TIFFs (Corrompidos)
    if total_tifs_verificados == 0:
        print("❌ FALHA CRÍTICA: Nenhuma imagem TIF/GeoTIFF foi encontrada no lote.")
    elif arquivos_corrompidos:
        print(f"❌ ATENÇÃO: Encontrados {len(arquivos_corrompidos)} TIFF(s) corrompido(s) ou inválido(s):")
        for arq, motivo in arquivos_corrompidos:
            print(f"   -> Arquivo: {arq}")
            print(f"      Motivo: {motivo}")
    else:
        print("✅ SUCESSO: Todos os TIFFs/GeoTIFFs entregues estão íntegros e abrem perfeitamente.")
        
    print("=" * 60)

auditar_lote_imagens(pasta_alvo)