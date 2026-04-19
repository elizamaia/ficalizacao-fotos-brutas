# -*- coding: utf-8 -*-

from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, # <--- Novo componente específico para Salvar
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterString,
                       QgsProcessingParameterEnum,
                       QgsProcessingException)
import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime

class AnaliseQualidadeVoo(QgsProcessingAlgorithm):
    # --- DEFINIÇÃO DOS NOMES DAS VARIÁVEIS ---
    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_REPORT = 'OUTPUT_REPORT'
    
    # Configuração de Colunas
    COL_ID = 'COL_ID'
    COL_OMEGA = 'COL_OMEGA'
    COL_PHI = 'COL_PHI'
    COL_KAPPA = 'COL_KAPPA'
    
    # Configuração de Separadores
    DELIMITER = 'DELIMITER'
    DECIMAL = 'DECIMAL'

    # Configuração de Faixa
    STRIP_START = 'STRIP_START'
    STRIP_END = 'STRIP_END'
    
    # Limites
    LIMIT_TILT_PHOTO = 'LIMIT_TILT_PHOTO'
    LIMIT_TILT_STRIP = 'LIMIT_TILT_STRIP'
    LIMIT_DERIVA_PHOTO = 'LIMIT_DERIVA_PHOTO'
    LIMIT_DERIVA_STRIP = 'LIMIT_DERIVA_STRIP'

    def tr(self, string):
        return string

    def createInstance(self):
        return AnaliseQualidadeVoo()

    def name(self):
        return 'relatorio_atitude_omega_phi_kappa'

    def displayName(self):
        return 'Fotos Brutas - Relatório - Ângulos de Atitude (omega/phi/kappa)'

    def group(self):
        return 'Fiscalização Mapeamento SEI'

    def groupId(self):
        return 'fiscalizacao_sei'

    def initAlgorithm(self, config=None):
        # 1. ARQUIVOS (PASTA)
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr('Pasta com os Relatórios de Voo'),
                behavior=QgsProcessingParameterFile.Folder
            )
        )

        # 2. MAPEAMENTO DE COLUNAS
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_ID,
                self.tr('Nome da Coluna da FOTO (Ex: PHOTOID)'),
                defaultValue='PHOTOID'
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_OMEGA,
                self.tr('Nome da Coluna OMEGA / ROLL'),
                defaultValue='OMEGA'
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_PHI,
                self.tr('Nome da Coluna PHI / PITCH'),
                defaultValue='PHI'
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.COL_KAPPA,
                self.tr('Nome da Coluna KAPPA / YAW'),
                defaultValue='KAPPA'
            )
        )

        # 3. CONFIGURAÇÃO DE TEXTO
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DELIMITER,
                self.tr('Separador de Colunas'),
                options=['Ponto e Vírgula (;)', 'Vírgula (,)'],
                defaultValue=0
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DECIMAL,
                self.tr('Separador Decimal'),
                options=['Ponto (.)', 'Vírgula (,)'],
                defaultValue=0
            )
        )
        
        # 4. CONFIGURAÇÃO DE FAIXA
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STRIP_START,
                self.tr('Índice Inicial da Faixa (Recorte do Nome)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STRIP_END,
                self.tr('Índice Final da Faixa (Recorte do Nome)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=4
            )
        )

        # 5. LIMITES DE QUALIDADE
        self.addParameter(QgsProcessingParameterNumber(self.LIMIT_TILT_PHOTO, self.tr('Limite Tilt (Foto)'), type=QgsProcessingParameterNumber.Double, defaultValue=3.0))
        self.addParameter(QgsProcessingParameterNumber(self.LIMIT_TILT_STRIP, self.tr('Limite Tilt (Média Faixa)'), type=QgsProcessingParameterNumber.Double, defaultValue=2.0))
        self.addParameter(QgsProcessingParameterNumber(self.LIMIT_DERIVA_PHOTO, self.tr('Limite Deriva (Foto)'), type=QgsProcessingParameterNumber.Double, defaultValue=3.0))
        self.addParameter(QgsProcessingParameterNumber(self.LIMIT_DERIVA_STRIP, self.tr('Limite Deriva (Média Faixa)'), type=QgsProcessingParameterNumber.Double, defaultValue=1.0))

        # 6. SAÍDA (USANDO FileDestination PARA EVITAR ERROS)
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                self.tr('Salvar Relatório Final em (.txt)'),
                fileFilter='Arquivos de Texto (*.txt)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # --- RECUPERAR INPUTS ---
        pasta = self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        arquivo_saida = self.parameterAsString(parameters, self.OUTPUT_REPORT, context)
        
        c_id = self.parameterAsString(parameters, self.COL_ID, context).strip()
        c_omega = self.parameterAsString(parameters, self.COL_OMEGA, context).strip()
        c_phi = self.parameterAsString(parameters, self.COL_PHI, context).strip()
        c_kappa = self.parameterAsString(parameters, self.COL_KAPPA, context).strip()

        sep_idx = self.parameterAsEnum(parameters, self.DELIMITER, context)
        separador = ';' if sep_idx == 0 else ','
        
        dec_idx = self.parameterAsEnum(parameters, self.DECIMAL, context)
        decimal_char = '.' if dec_idx == 0 else ','

        f_ini = self.parameterAsInt(parameters, self.STRIP_START, context)
        f_fim = self.parameterAsInt(parameters, self.STRIP_END, context)
        
        lim_t_ph = self.parameterAsDouble(parameters, self.LIMIT_TILT_PHOTO, context)
        lim_t_st = self.parameterAsDouble(parameters, self.LIMIT_TILT_STRIP, context)
        lim_d_ph = self.parameterAsDouble(parameters, self.LIMIT_DERIVA_PHOTO, context)
        lim_d_st = self.parameterAsDouble(parameters, self.LIMIT_DERIVA_STRIP, context)

        lista = glob.glob(os.path.join(pasta, "*.txt")) + glob.glob(os.path.join(pasta, "*.csv"))
        
        if not lista:
            raise QgsProcessingException(f"Nenhum arquivo encontrado em: {pasta}")

        with open(arquivo_saida, 'w', encoding='utf-8') as f:
            f.write(f"RELATORIO DE CONTROLE DE QUALIDADE UNIVERSAL\nData: {datetime.now()}\n")
            f.write(f"Parametros: Sep='{separador}' | Dec='{decimal_char}' | Colunas='{c_id}, {c_omega}..'\n")
            f.write("="*80 + "\n")

        def registrar(texto):
            feedback.pushInfo(texto)
            try:
                with open(arquivo_saida, 'a', encoding='utf-8') as f:
                    f.write(texto + "\n")
            except: pass

        total = len(lista)
        for i, arq in enumerate(lista):
            if feedback.isCanceled(): break
            feedback.setProgress(int((i/total)*100))

            try:
                df = pd.read_csv(arq, sep=separador, decimal=decimal_char, engine='python', skipinitialspace=True)
                df.columns = df.columns.str.strip()
                
                colunas_usuario = [c_id, c_omega, c_phi, c_kappa]
                colunas_faltantes = [c for c in colunas_usuario if c not in df.columns]
                
                if colunas_faltantes:
                    registrar(f"\n[ERRO] {os.path.basename(arq)}: Colunas não encontradas: {colunas_faltantes}")
                    continue

                renomear = {c_id: 'ID', c_omega: 'W', c_phi: 'P', c_kappa: 'K'}
                df = df.rename(columns=renomear)

                for col in ['W', 'P', 'K']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df = df.dropna(subset=['W', 'P', 'K'])

                df['Faixa'] = df['ID'].astype(str).str.strip().str[f_ini:f_fim]

                # Calculos
                df['tilt_calc'] = np.sqrt(df['W']**2 + df['P']**2)
                
                medias_k = df.groupby('Faixa')['K'].transform('median')
                diffs = (df['K'] - medias_k).abs()
                df['deriva_calc'] = np.where(diffs > 180, 360 - diffs, diffs)

                resumo = df.groupby('Faixa').agg({
                    'tilt_calc': 'mean',
                    'deriva_calc': 'mean'
                }).reset_index()

                # Validacao
                ruins_t_ph = df[df['tilt_calc'] > lim_t_ph]
                ruins_d_ph = df[df['deriva_calc'] > lim_d_ph]
                
                ruins_t_st = resumo[resumo['tilt_calc'] > lim_t_st]
                ruins_d_st = resumo[resumo['deriva_calc'] > lim_d_st]

                # Reportar
                registrar(f"\nANÁLISE: {os.path.basename(arq)}")
                registrar("-" * 60)

                if len(ruins_t_ph) > 0:
                    registrar(f"[!] {len(ruins_t_ph)} FOTOS com Tilt > {lim_t_ph}")
                    registrar(ruins_t_ph[['ID', 'tilt_calc']].to_string(index=False))
                else: registrar("[OK] Tilt Foto Aprovado.")

                if len(ruins_t_st) > 0:
                    registrar(f"[!] {len(ruins_t_st)} FAIXAS com Tilt Médio > {lim_t_st}")
                    registrar(ruins_t_st.to_string(index=False))
                else: registrar("[OK] Tilt Faixa Aprovado.")

                registrar("-" * 30)
                
                if len(ruins_d_ph) > 0:
                    registrar(f"[!] {len(ruins_d_ph)} FOTOS com Deriva > {lim_d_ph}")
                    registrar(ruins_d_ph[['ID', 'deriva_calc']].to_string(index=False))
                else: registrar("[OK] Deriva Foto Aprovada.")

                if len(ruins_d_st) > 0:
                    registrar(f"[!] {len(ruins_d_st)} FAIXAS com Deriva Média > {lim_d_st}")
                    registrar(ruins_d_st.to_string(index=False))
                else: registrar("[OK] Deriva Faixa Aprovada.")

            except Exception as e:
                registrar(f"[ERRO CRITICO] {os.path.basename(arq)}: {str(e)}")

        return {self.OUTPUT_REPORT: arquivo_saida}