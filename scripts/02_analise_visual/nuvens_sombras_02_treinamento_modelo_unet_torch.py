# -*- coding: utf-8 -*-
"""
Created on Fri Jul 11 17:21:53 2025

@author: elizamaia
"""

import os
import numpy as np
import rasterio
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix, classification_report
import seaborn as sns
import time

# =============================================================================
# --- CONFIGURAÇÃO ---
# AJUSTE ESTAS VARIÁVEIS ANTES DE RODAR
# =============================================================================

# 1. Caminhos para as pastas
# IMAGES_FOLDER deve ser a pasta PAI que contém as subpastas com as imagens
IMAGES_FOLDER = r'Y:\LOTE01\FOTO\ENT_01\REV_00\CIR_16bits'
MASKS_FOLDER = r'S:\digeo\CARTGEO\PROJETOS\INTERNOS\NOVO_MAPEAMENTO_II\MAT_APOIO\TEMP\mascaras_nuvens_sombras'

# 2. Parâmetros do modelo e das imagens
IMG_HEIGHT = 256
IMG_WIDTH = 256
IMG_CHANNELS = 3 # 3 para RGIR
NUM_CLASSES = 3  # 0: Fundo, 1: Nuvem, 2: Sombra
VALIDATION_SPLIT = 0.2

# 3. Parâmetros de treinamento
EPOCHS = 50
BATCH_SIZE = 4 # Comece com um valor baixo (4 ou 2) para garantir que funcione
LEARNING_RATE = 1e-4
MODEL_SAVE_PATH = 'unet_pytorch_final.pth'

# =============================================================================
# --- FUNÇÃO AUXILIAR DE BUSCA ---
# FUNÇÃO DE BUSCA ADICIONADA PARA ENCONTRAR ARQUIVOS EM SUBPASTAS
# =============================================================================

def find_file(root_folder, filename):
    """Procura recursivamente por um arquivo com nome EXATO em uma pasta raiz."""
    if not filename: return None
    for root, dirs, files in os.walk(root_folder):
        if filename in files:
            return os.path.join(root, filename)
    return None

# =============================================================================
# --- DATASET E PRÉ-PROCESSAMENTO (VERSÃO OTIMIZADA) ---
# =============================================================================

from rasterio.enums import Resampling

class SegmentationDataset(Dataset):
    def __init__(self, image_paths, mask_paths, height, width):
        self.image_paths = image_paths
        self.mask_paths = mask_paths
        self.height = height
        self.width = width

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        # Define a forma de saída (Canais, Altura, Largura)
        out_shape_img = (3, self.height, self.width)
        out_shape_mask = (self.height, self.width)

        # Carregar imagem RGIR (16-bit) JÁ REDIMENSIONADA
        with rasterio.open(self.image_paths[idx]) as src:
            img = src.read(
                out_shape=out_shape_img,
                resampling=Resampling.bilinear  # Método de reamostragem para imagens
            ).astype(np.float32)
        
        # Carregar máscara (8-bit) JÁ REDIMENSIONADA
        with rasterio.open(self.mask_paths[idx]) as src:
            mask = src.read(
                1, # Apenas a primeira banda
                out_shape=out_shape_mask,
                resampling=Resampling.nearest # 'Nearest' para não criar valores intermediários (0.5, 1.5, etc.)
            ).astype(np.int64)

        # Normalizar imagem de 16-bit para [0, 1]
        img = img / 65535.0

        # Converter para Tensores do PyTorch
        img_tensor = torch.from_numpy(img)
        mask_tensor = torch.from_numpy(mask)

        # As imagens já foram redimensionadas, não precisamos mais do torchvision.transforms
        return img_tensor, mask_tensor

# =============================================================================
# --- ARQUITETURA U-NET EM PYTORCH ---
# =============================================================================

class UNet(nn.Module):
    def __init__(self, in_channels, out_classes):
        super().__init__()
        # Bloco de contração (Encoder)
        self.conv1 = self.conv_block(in_channels, 64)
        self.pool1 = nn.MaxPool2d(2)
        self.conv2 = self.conv_block(64, 128)
        self.pool2 = nn.MaxPool2d(2)
        self.conv3 = self.conv_block(128, 256)
        self.pool3 = nn.MaxPool2d(2)
        self.conv4 = self.conv_block(256, 512)
        self.pool4 = nn.MaxPool2d(2)
        
        # Camada de gargalo
        self.bottleneck = self.conv_block(512, 1024)
        
        # Bloco de expansão (Decoder)
        self.upconv4 = nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.dec_conv4 = self.conv_block(1024, 512)
        self.upconv3 = nn.ConvTranspose2d(512, 256, kernel_size=2, stride=2)
        self.dec_conv3 = self.conv_block(512, 256)
        self.upconv2 = nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.dec_conv2 = self.conv_block(256, 128)
        self.upconv1 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.dec_conv1 = self.conv_block(128, 64)
        
        # Camada de saída
        self.out_conv = nn.Conv2d(64, out_classes, kernel_size=1)

    def conv_block(self, in_channels, out_channels):
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        # Encoder
        c1 = self.conv1(x)
        p1 = self.pool1(c1)
        c2 = self.conv2(p1)
        p2 = self.pool2(c2)
        c3 = self.conv3(p2)
        p3 = self.pool3(c3)
        c4 = self.conv4(p3)
        p4 = self.pool4(c4)
        
        bottleneck = self.bottleneck(p4)
        
        # Decoder com skip connections
        u4 = self.upconv4(bottleneck)
        u4 = torch.cat([u4, c4], dim=1)
        d4 = self.dec_conv4(u4)
        
        u3 = self.upconv3(d4)
        u3 = torch.cat([u3, c3], dim=1)
        d3 = self.dec_conv3(u3)
        
        u2 = self.upconv2(d3)
        u2 = torch.cat([u2, c2], dim=1)
        d2 = self.dec_conv2(u2)
        
        u1 = self.upconv1(d2)
        u1 = torch.cat([u1, c1], dim=1)
        d1 = self.dec_conv1(u1)
        
        return self.out_conv(d1)

# =============================================================================
# --- LÓGICA DE TREINAMENTO ---
# =============================================================================

# 1. Mapear os arquivos (LÓGICA ATUALIZADA)
if __name__ == '__main__':
    print("Mapeando arquivos de imagem e máscara...")
    image_paths = []
    mask_paths = []
    mask_filenames = sorted([f for f in os.listdir(MASKS_FOLDER) if f.endswith(('.tif', '.tiff'))])
    
    for mask_name in mask_filenames:
        image_path = find_file(IMAGES_FOLDER, mask_name)
        if image_path:
            image_paths.append(image_path)
            mask_paths.append(os.path.join(MASKS_FOLDER, mask_name))
        else:
            print(f"AVISO: Máscara '{mask_name}' não encontrou imagem correspondente em '{IMAGES_FOLDER}'.")
    
    if not image_paths:
        raise ValueError("ERRO CRÍTICO: Nenhum par de imagem/máscara foi encontrado.")
    
    print(f"Encontrados {len(image_paths)} pares de imagem/máscara.")
    
    # 2. Criar e dividir o Dataset
    full_dataset = SegmentationDataset(image_paths, mask_paths, IMG_HEIGHT, IMG_WIDTH)
    val_size = int(VALIDATION_SPLIT * len(full_dataset))
    if val_size == 0 and len(full_dataset) > 0: val_size = 1 # Garante que haja pelo menos 1 amostra de validação
    train_size = len(full_dataset) - val_size
    train_ds, val_ds = random_split(full_dataset, [train_size, val_size])
    
    # 3. Criar os DataLoaders
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=4, pin_memory=True)
    print(f"Tamanho do dataset de treino: {len(train_ds)}, Validação: {len(val_ds)}")
    
    # 4. Configurar o Treinamento
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = UNet(in_channels=IMG_CHANNELS, out_classes=NUM_CLASSES).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    # 5. Loop de Treinamento
    best_val_loss = float('inf')
    history = {'train_loss': [], 'val_loss': []}
    
    for epoch in range(EPOCHS):
        start_time = time.time()
        model.train()
        running_loss = 0.0
        for images, masks in train_loader:
            images, masks = images.to(device), masks.to(device)
            
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, masks)
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item() * images.size(0)
        
        epoch_loss = running_loss / len(train_ds)
        history['train_loss'].append(epoch_loss)
    
        # Validação
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for images, masks in val_loader:
                images, masks = images.to(device), masks.to(device)
                outputs = model(images)
                loss = criterion(outputs, masks)
                val_loss += loss.item() * images.size(0)
        
        epoch_val_loss = val_loss / len(val_ds)
        history['val_loss'].append(epoch_val_loss)
    
        end_time = time.time()
        epoch_duration = end_time - start_time
        
        print(f"Epoch {epoch+1}/{EPOCHS}.. "
              f"Train Loss: {epoch_loss:.4f}.. "
              f"Val Loss: {epoch_val_loss:.4f}.. "
              f"Duration: {epoch_duration:.2f}s")
        
        # Salvar o melhor modelo
        if epoch_val_loss < best_val_loss:
            print(f"Validation loss decreased ({best_val_loss:.4f} --> {epoch_val_loss:.4f}). Saving model...")
            torch.save(model.state_dict(), MODEL_SAVE_PATH)
            best_val_loss = epoch_val_loss
    
    print("Treinamento concluído.")
    
    # =============================================================================
    # --- ANÁLISE DE PERFORMANCE ---
    # =============================================================================
    
    print("\nCarregando o melhor modelo salvo para avaliação detalhada...")
    # Carrega o modelo com a mesma arquitetura e depois os pesos salvos
    model_eval = UNet(in_channels=IMG_CHANNELS, out_classes=NUM_CLASSES)
    model_eval.load_state_dict(torch.load(MODEL_SAVE_PATH))
    model_eval.to(device)
    model_eval.eval()
    
    y_true = []
    y_pred = []
    
    with torch.no_grad():
        for images, masks in val_loader:
            images = images.to(device)
            outputs = model_eval(images)
            preds = torch.argmax(outputs, dim=1).cpu().numpy()
            
            y_true.extend(masks.numpy().flatten())
            y_pred.extend(preds.flatten())
    
    print("\n--- Relatório de Classificação Detalhado ---\n")
    target_names = ['Classe 0 (Fundo)', 'Classe 1 (Nuvem)', 'Classe 2 (Sombra)']
    print(classification_report(y_true, y_pred, target_names=target_names, zero_division=0))
    
    print("\n--- Matriz de Confusão ---\n")
    conf_matrix = confusion_matrix(y_true, y_pred)
    plt.figure(figsize=(10, 8))
    sns.heatmap(conf_matrix, annot=True, fmt='d', cmap='Blues', 
                xticklabels=target_names, yticklabels=target_names)
    plt.ylabel('Classe Real (Verdadeira)')
    plt.xlabel('Classe Prevista pelo Modelo')
    plt.title('Matriz de Confusão no Conjunto de Validação')
    plt.show()