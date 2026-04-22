import os
from osgeo import gdal

# ==========================================
# CONFIGURAÇÕES DA FISCALIZAÇÃO
# ==========================================

# 1. INSIRA O CAMINHO DA SUA PASTA AQUI ABAIXO
pasta_alvo = r"Y:\LOTE01\FOTO\ENT_01\REV_00\CIR_16bits"

# 2. DEFINA A COMPOSIÇÃO ESPERADA ('RGB' ou 'RGIR')
composicao_esperada = 'RGIR' 

# 3. DEFINA A QUANTIDADE DE BANDAS DE CADA COMPOSIÇÃO
# Se o seu produto RGIR for de 4 bandas (RGB + NIR), mantenha 4.
# Se for composição Falsa Cor de 3 bandas (NIR, R, G), mude o 4 para 3.
regras_de_bandas = {
    'RGB': 3,
    'RGIR': 3 
}

# ==========================================

gdal.UseExceptions()

def auditar_bandas_imagens(diretorio, tipo_composicao, regras):
    extensoes_imagem = ('.tif', '.tiff', '.geotif', '.geotiff')
    extensoes_auxiliares = ('.aux', '.tfw', '.xml', '.db', '.ini', '.prj', '.ovr')
    
    bandas_exigidas = regras.get(tipo_composicao.upper())
    
    if not bandas_exigidas:
        print(f"Erro: Tipo de composição '{tipo_composicao}' não reconhecido. Use 'RGB' ou 'RGIR'.")
        return

    arquivos_com_erro_de_banda = []
    arquivos_corrompidos = []
    arquivos_intrusos = []
    
    total_imagens_corretas = 0
    total_auxiliares = 0
    pastas_lidas = 0

    print(f"Iniciando auditoria de composição ({tipo_composicao} - {bandas_exigidas} bandas) no diretório:\n{diretorio}\n")
    print("Aguarde, processando a árvore de pastas...\n")

    for raiz, _, arquivos in os.walk(diretorio, followlinks=True):
        pastas_lidas += 1
        
        for arquivo in arquivos:
            caminho_completo = os.path.join(raiz, arquivo)
            extensao = os.path.splitext(arquivo)[1].lower()
            
            if not extensao:
                extensao = "[sem extensão]"

            # CASO 1: É IMAGEM (TIFF)? -> Verifica a estrutura e conta as bandas
            if extensao in extensoes_imagem:
                try:
                    dataset = gdal.Open(caminho_completo, gdal.GA_ReadOnly)
                    if dataset is None:
                        arquivos_corrompidos.append((caminho_completo, "O GDAL não conseguiu abrir o arquivo."))
                        continue
                    
                    qtd_bandas = dataset.RasterCount
                    
                    # Verifica se tem bandas (corrupção severa)
                    if qtd_bandas == 0:
                        arquivos_corrompidos.append((caminho_completo, "O arquivo não possui bandas (RasterCount = 0)."))
                    # Verifica se a quantidade de bandas bate com a exigência
                    elif qtd_bandas != bandas_exigidas:
                        arquivos_com_erro_de_banda.append((caminho_completo, f"Tem {qtd_bandas} banda(s), mas deveria ter {bandas_exigidas}."))
                    else:
                        total_imagens_corretas += 1
                    
                    dataset = None
                    
                except Exception as e:
                    erro_msg = str(e).strip()
                    arquivos_corrompidos.append((caminho_completo, f"Erro GDAL: {erro_msg}"))
            
            # CASO 2: É ARQUIVO AUXILIAR PERMITIDO? -> Contabiliza
            elif extensao in extensoes_auxiliares:
                total_auxiliares += 1
                
            # CASO 3: OUTROS FORMATOS -> Vai para lista de intrusos
            else:
                arquivos_intrusos.append(caminho_completo)

    # --- GERAÇÃO DO RELATÓRIO DE AUDITORIA ---
    print("=" * 80)
    print(" " * 18 + f"RELATÓRIO DE FISCALIZAÇÃO - COMPOSIÇÃO {tipo_composicao}")
    print("=" * 80)
    print(f"Pastas verificadas: {pastas_lidas}")
    print(f"Imagens com composição CORRETA ({bandas_exigidas} bandas): {total_imagens_corretas}")
    print(f"Arquivos auxiliares válidos: {total_auxiliares}")
    print("-" * 80)
    
    # 1. Falha de Composição (Radiometria Errada)
    if arquivos_com_erro_de_banda:
        print(f"🔴 ERRO DE COMPOSIÇÃO: {len(arquivos_com_erro_de_banda)} imagem(ns) com número de bandas incorreto:")
        for arq, motivo in arquivos_com_erro_de_banda:
            print(f"   -> {arq}")
            print(f"      Problema: {motivo}")
        print("-" * 80)
        
    # 2. Arquivos Corrompidos
    if arquivos_corrompidos:
        print(f"❌ ARQUIVOS CORROMPIDOS: {len(arquivos_corrompidos)} arquivo(s) ilegível(is):")
        for arq, motivo in arquivos_corrompidos:
            print(f"   -> Arquivo: {arq}")
            print(f"      Problema: {motivo}")
        print("-" * 80)

    # 3. Arquivos Intrusos
    if arquivos_intrusos:
        print(f"⚠️ ARQUIVOS INTRUSOS: {len(arquivos_intrusos)} arquivo(s) não permitido(s):")
        for intruso in arquivos_intrusos:
            print(f"   -> {intruso}")
        print("-" * 80)

    # Conclusão
    total_erros = len(arquivos_com_erro_de_banda) + len(arquivos_corrompidos) + len(arquivos_intrusos)
    if total_erros == 0 and total_imagens_corretas > 0:
        print("✅ SUCESSO ABSOLUTO: Todas as imagens possuem a composição exigida e não há arquivos intrusos.")
    elif total_imagens_corretas == 0:
        print("⚠️ ALERTA: Nenhuma imagem válida foi processada.")
        
    print("=" * 80)

# Executa a função
auditar_bandas_imagens(pasta_alvo, composicao_esperada, regras_de_bandas)