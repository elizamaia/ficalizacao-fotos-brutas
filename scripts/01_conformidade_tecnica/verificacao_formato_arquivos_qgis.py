import os
from osgeo import gdal

# ==========================================
# 1. INSIRA O CAMINHO DA SUA PASTA AQUI ABAIXO
# ==========================================
pasta_alvo = r"Y:\LOTE01\FOTO\ENT_01\REV_00\RGB_16bits\20230820"

# ==========================================

gdal.UseExceptions()

def auditar_lote_imagens(diretorio):
    extensoes_imagem = ('.tif', '.tiff', '.geotif', '.geotiff')
    extensoes_auxiliares = ('.aux', '.tfw', '.xml', '.db', '.ini')
    
    arquivos_corrompidos = []
    arquivos_intrusos = [] # Lista que vai guardar o nome de cada arquivo errado
    
    total_tifs_verificados = 0
    total_auxiliares = 0
    pastas_lidas = 0

    print(f"Iniciando auditoria completa no diretório:\n{diretorio}\n")
    print("Aguarde, processando a árvore de pastas...\n")

    for raiz, _, arquivos in os.walk(diretorio, followlinks=True):
        pastas_lidas += 1
        
        for arquivo in arquivos:
            caminho_completo = os.path.join(raiz, arquivo)
            extensao = os.path.splitext(arquivo)[1].lower()
            
            if not extensao:
                extensao = "[sem extensão]"

            # CASO 1: É IMAGEM (TIFF)? -> Faz a validação profunda com GDAL
            if extensao in extensoes_imagem:
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
            
            # CASO 2: É ARQUIVO AUXILIAR PERMITIDO? -> Apenas contabiliza
            elif extensao in extensoes_auxiliares:
                total_auxiliares += 1
                
            # CASO 3: É QUALQUER OUTRA COISA? -> Vai para a lista de erros/intrusos
            else:
                arquivos_intrusos.append(caminho_completo)

    # --- GERAÇÃO DO RELATÓRIO DE AUDITORIA ---
    print("=" * 80)
    print(" " * 25 + "RELATÓRIO DE FISCALIZAÇÃO")
    print("=" * 80)
    print(f"Pastas verificadas: {pastas_lidas}")
    print(f"Imagens TIF/GeoTIFF avaliadas: {total_tifs_verificados}")
    print(f"Arquivos auxiliares válidos (.aux, .tfw, .xml): {total_auxiliares}")
    print("-" * 80)
    
    # 1. Avaliação dos Intrusos (Formatos não permitidos)
    if arquivos_intrusos:
        print(f"⚠️ ALERTA: Foram encontrados {len(arquivos_intrusos)} arquivo(s) não permitidos (intrusos/erros):")
        for intruso in arquivos_intrusos:
            print(f"   -> {intruso}")
        print("-" * 80)
    
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
        
    print("=" * 80)

# Executa a função
auditar_lote_imagens(pasta_alvo)