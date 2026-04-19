# -*- coding: utf-8 -*-
"""
Created on Tue Jul 15 15:37:36 2025

@author: elizamaia
"""

import os
import glob
import rasterio
import torch
import torch.nn.functional as F
import numpy as np
import cv2
import geopandas as gpd
from shapely.geometry import Polygon
from rasterio.enums import Resampling
# from torchvision.transforms import functional as TF # não precisa nesse momento

# =============================================================================
# --- CONFIGURAÇÃO ---
# AJUSTE ESTAS 3 LINHAS
# =============================================================================
MODEL_PATH = 'unet_pytorch_final.pth'  # Caminho para o seu modelo treinado
INPUT_FOLDER = r'V:\LOTE01\FOTO\ENT_03\REV_00\RGIR'  # Pasta principal com as imagens (pode ter subpastas)
OUTPUT_GPKG_PATH = r'D:\NOVO_MAPEAMENTO_2\01_automatizacao\segmentacoes_finais_entr03.gpkg'  # Caminho para o arquivo GeoPackage de saída

# --- PARÂMETROS DO MODELO (devem ser os mesmos do treinamento) ---
IMG_HEIGHT = 256
IMG_WIDTH = 256
NUM_CLASSES = 3  # 0: Fundo, 1: Nuvem, 2: Sombra
IMG_CHANNELS = 3 # 3 para RGIR
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# =============================================================================
# --- ARQUITETURA DO MODELO (precisa ser definida para carregar os pesos) ---
# =============================================================================
class UNet(torch.nn.Module):
    def __init__(self, in_channels, out_classes):
        super().__init__()
        self.conv1 = self.conv_block(in_channels, 64)
        self.pool1 = torch.nn.MaxPool2d(2)
        self.conv2 = self.conv_block(64, 128)
        self.pool2 = torch.nn.MaxPool2d(2)
        self.conv3 = self.conv_block(128, 256)
        self.pool3 = torch.nn.MaxPool2d(2)
        self.conv4 = self.conv_block(256, 512)
        self.pool4 = torch.nn.MaxPool2d(2)
        self.bottleneck = self.conv_block(512, 1024)
        self.upconv4 = torch.nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.dec_conv4 = self.conv_block(1024, 512)
        self.upconv3 = torch.nn.ConvTranspose2d(512, 256, kernel_size=2, stride=2)
        self.dec_conv3 = self.conv_block(512, 256)
        self.upconv2 = torch.nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.dec_conv2 = self.conv_block(256, 128)
        self.upconv1 = torch.nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.dec_conv1 = self.conv_block(128, 64)
        self.out_conv = torch.nn.Conv2d(64, out_classes, kernel_size=1)

    def conv_block(self, in_channels, out_channels):
        return torch.nn.Sequential(
            torch.nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            torch.nn.BatchNorm2d(out_channels),
            torch.nn.ReLU(inplace=True),
            torch.nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
            torch.nn.BatchNorm2d(out_channels),
            torch.nn.ReLU(inplace=True)
        )

    def forward(self, x):
        c1 = self.conv1(x); p1 = self.pool1(c1)
        c2 = self.conv2(p1); p2 = self.pool2(c2)
        c3 = self.conv3(p2); p3 = self.pool3(c3)
        c4 = self.conv4(p3); p4 = self.pool4(c4)
        bottleneck = self.bottleneck(p4)
        u4 = self.upconv4(bottleneck); u4 = torch.cat([u4, c4], dim=1); d4 = self.dec_conv4(u4)
        u3 = self.upconv3(d4); u3 = torch.cat([u3, c3], dim=1); d3 = self.dec_conv3(u3)
        u2 = self.upconv2(d3); u2 = torch.cat([u2, c2], dim=1); d2 = self.dec_conv2(u2)
        u1 = self.upconv1(d2); u1 = torch.cat([u1, c1], dim=1); d1 = self.dec_conv1(u1)
        return self.out_conv(d1)

# =============================================================================
# --- FUNÇÕES DE PROCESSAMENTO ---
# =============================================================================
def preprocess_image(image_path, height, width):
    """Carrega e pré-processa uma única imagem."""
    with rasterio.open(image_path) as src:
        # Lê apenas os 3 primeiros canais (RGIR -> RGI)
        img = src.read(range(1, IMG_CHANNELS + 1), out_shape=(IMG_CHANNELS, height, width), resampling=Resampling.bilinear).astype(np.float32)
        profile = src.profile
    img = img / 65535.0  # Normaliza imagem de 16-bit
    img_tensor = torch.from_numpy(img).unsqueeze(0).to(DEVICE)
    return img_tensor, profile

def postprocess_mask(output, original_height, original_width):
    """Pega a saída do modelo e cria uma máscara de predição final."""
    # Redimensiona a saída do modelo para o tamanho original da imagem
    upsampled_output = F.interpolate(output, size=(original_height, original_width), mode='bilinear', align_corners=False)
    # Pega a classe com maior probabilidade para cada pixel
    mask = torch.argmax(upsampled_output, dim=1)[0].cpu().numpy().astype(np.uint8)
    return mask

def create_polygons_from_mask(mask, transform, image_name):
    """Converte a máscara de pixels em polígonos georreferenciados."""
    polygons_data = []
    # Classes de interesse: 1 para Nuvem, 2 para Sombra
    for class_id, class_name in [(1, 'nuvem'), (2, 'sombra')]:
        # Cria uma máscara binária para a classe atual
        class_mask = (mask == class_id).astype(np.uint8)
        # Encontra os contornos
        contours, _ = cv2.findContours(class_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            # Um polígono precisa de pelo menos 3 vértices
            if contour.shape[0] >= 3:
                # Converte coordenadas de pixel para coordenadas geográficas
                coords = [transform * (point[0], point[1]) for point in contour.reshape(-1, 2)]
                polygon = Polygon(coords)
                # Adiciona o polígono e seus atributos à lista
                if polygon.is_valid:
                    polygons_data.append({'geometry': polygon, 'classe': class_name, 'imagem_origem': image_name})
    return polygons_data

# =============================================================================
# --- SCRIPT PRINCIPAL ---
# =============================================================================
if __name__ == '__main__':
    print("Carregando modelo treinado...")
    model = UNet(in_channels=IMG_CHANNELS, out_classes=NUM_CLASSES)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
    model.to(DEVICE)
    model.eval()

    all_polygons = []
    
    print(f"Buscando imagens na pasta e subpastas de: {INPUT_FOLDER}")
    # Cria uma lista de todos os arquivos de imagem dentro da pasta e suas subpastas
    image_extensions = ('tif', 'tiff', 'jpg', 'jpeg', 'png')
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(INPUT_FOLDER, '**', f'*.{ext}'), recursive=True))

    if not image_files:
        print("AVISO: Nenhum arquivo de imagem encontrado. Verifique o caminho em INPUT_FOLDER.")
    else:
        print(f"Encontradas {len(image_files)} imagens para processar.")

    for image_path in image_files:
        try:
            print(f"Processando: {os.path.basename(image_path)}...")
            img_tensor, img_profile = preprocess_image(image_path, IMG_HEIGHT, IMG_WIDTH)
            
            with torch.no_grad():
                output = model(img_tensor)
            
            mask = postprocess_mask(output, img_profile['height'], img_profile['width'])
            
            polygons = create_polygons_from_mask(mask, img_profile['transform'], os.path.basename(image_path))
            all_polygons.extend(polygons)

        except Exception as e:
            print(f"ERRO ao processar '{os.path.basename(image_path)}': {e}")

    if all_polygons:
        print("\nCriando GeoPackage com todas as poligonais...")
        gdf = gpd.GeoDataFrame(all_polygons, geometry='geometry', crs=img_profile['crs'])
        gdf.to_file(OUTPUT_GPKG_PATH, layer='nuvens_e_sombras', driver='GPKG')
        print(f"✅ Sucesso! Arquivo '{OUTPUT_GPKG_PATH}' criado com {len(gdf)} feições.")
    else:
        print("\nNenhuma nuvem ou sombra foi detectada para gerar poligonais.")

    print("Processamento concluído.")