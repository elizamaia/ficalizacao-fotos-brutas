# Controle de Qualidade Integrado de Fotografias Aéreas Brutas

Este repositório possui scripts na linguagem Python elaborados para fins de fiscalização de fotografias aéreas brutas de forma automatizada.

---

## Sobre a Pesquisa

O projeto propõe um método para otimizar o controle de qualidade (CQ) de levantamentos aerofotogramétricos, na fase de geração de fotografias aéreas brutas (sem ortorretificação), reduzindo a subjetividade humana e o tempo de processamento. A pesquisa está dividida em duas etapas principais:

### Etapa 01: Validação da Conformidade Técnica
Nesta etapa, estão reunidos os parâmetros que analisam os metadados das fotografias e a integridade técnica dos arquivos, garantindo que o levantamento siga os padrões cartográficos e os requisitos de voo estabelecidos.

* **Sobreposição longitudinal e lateral**: Verificação da sobreposição de fotos em uma mesma faixa de voo e entre diferentes faixas de voo.
* **Ângulos de atitude**: Verificação da estabilidade do voo através dos ângulos de Roll, Pitch e Yaw.
* **Consistência na Altura de Voo**: Verificação da variabilidade da altitude do voo numa mesma faixa.
* **Sistema de Referência (EPSG)**: Verificação do código EPSG para garantir georreferenciamento padrão.
* **Conformidade radiométrica**: Verificação da profundidade de bits.
* **Conformidade espectral**: Verificação da existência de todas as bandas da composição.
* **GSD (Ground Sample Distance)**: Verificação da resolução espacial nominal do voo.

### Etapa 02: Análise Visual Automatizada
Esta etapa foca na análise do conteúdo da imagem propriamente dito que geralmente tem sido feita através de inspeção manual. Nessa etapa serão utilizadas técnicas de processamento digital de imagens e Deep Learning para identificar falhas qualitativas que prejudicam os produtos cartográficos finais.

* **Arrastamento de imagem**: Verificação de borrões causados pelo movimento da aeronave ou baixa velocidade do obturador.
* **Brumas, nevoeiros, nuvens e fumaças**: Verificação da existência desses fenômenos nas imagens.
* **Sombras e iluminação**: Verificação da redução de contraste.
* **Ruídos**: Verificação de pixels aleatórios com diferenciação de brilho ou cor dos seus vizinhos.
* **Artefatos físicos**: Verificação de anomalias decorrentes de artefatos físicos como poeiras no sensor, bloqueio do sensor, manchas, listras.
* **Consistência e balanço de cores**: Verificação de desequilíbrio de cor.

---

## Organização do Repositório

* **scripts/01_conformidade_tecnica/**: Rotinas para extração de metadados e verificação dos parâmetros técnicos.
* **scripts/02_analise_visual_dl/**: Scripts para pré-processamento, treinamento e inferência de modelos de análise visual.

---

## Propriedade Intelectual e Citação

**Copyright (c) 2026 Eliza Silva Maia - PPEC/UFBA**

Este código é parte integrante da pesquisa de mestrado intitulada:
"Controle de Qualidade Integrado de Fotografias Aéreas Brutas: um método automatizado para validação da conformidade técnica e análise visual". 

Todos os direitos reservados. O uso, reprodução ou distribuição deste material sem autorização prévia é proibido. Para fins acadêmicos, cite a obra original (**colocar citação pra obra**).