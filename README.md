# Controle de Qualidade Integrado de Fotografias Aéreas Brutas

Este repositório possui scripts na linguagem Python elaborados para fins de fiscalização de fotografias aéreas brutas de forma automatizada.

---

## Sobre a Pesquisa

O projeto propõe um método para otimizar o controle de qualidade (CQ) de levantamentos aerofotogramétricos, na fase de geração de fotografias aéreas brutas (sem ortorretificação), reduzindo a subjetividade humana e o tempo de processamento. A pesquisa está dividida em 4 etapas principais:

### Etapa 01: Validação da Conformidade Técnica
Nesta etapa, estão reunidos os parâmetros que analisam os metadados das fotografias e a integridade técnica dos arquivos, garantindo que o levantamento siga os padrões cartográficos e os requisitos de voo estabelecidos.

* **Sobreposição longitudinal e lateral**: Verificação da sobreposição de fotos em uma mesma faixa de voo e entre diferentes faixas de voo.
* **Ângulos de atitude**: Verificação da estabilidade do voo através dos ângulos de Roll, Pitch e Yaw.
* **Consistência na Altura de Voo**: Verificação da variabilidade da altitude do voo numa mesma faixa.
* **Sistema de Referência (EPSG)**: Verificação do código EPSG para garantir georreferenciamento padrão.
* **Conformidade radiométrica**: Verificação da profundidade de bits.
* **Conformidade espectral**: Verificação da existência de todas as bandas da composição.
* **GSD (Ground Sample Distance)**: Verificação da resolução espacial nominal do voo.

### Etapa 02: Anomalias Visuais
Esta etapa foca na análise do conteúdo da imagem propriamente dito que geralmente tem sido feita através de inspeção manual. Nessa etapa serão utilizadas técnicas de processamento digital de imagens e Deep Learning para identificar falhas qualitativas que prejudicam os produtos cartográficos finais.

* **Arrastamento de imagem**: Verificação de borrões causados pelo movimento da aeronave ou baixa velocidade do obturador.
* **Brumas, nevoeiros, nuvens e fumaças**: Verificação da existência desses fenômenos nas imagens.
* **Sombras**: Verificação da redução de contraste.
* **Vazio de dados**: Verificação de pixels sem valores (0,0,0) ou com valores máximos (65535, 65535, 65535).
* **Consistência e balanço de cores**: Verificação de desequilíbrio de cor.
* **Transbordamento espectral**: Verificação de manchas anômalas decorrentes da combinação de bandas.

### Etapa 03: Integração e Concepção do Framework de Decisão
Esta etapa realiza a integração das validações executadas nas Etapas 01 e 02 por meio de um framework de decisão. Apesar dos resultados obtidos nas etapas anteriores estarem consolidados no relatório síntese e no vetor unificado, é necessária uma análise posterior seguindo regras de exceção para cada parâmetro para, assim, se ter um parecer final do bloco de imagens que passaram pela validação.

### Etapa 04: Validação Comparativa
O objeivo desta etapa é validar a metodologia proposta através de uma avaliação comparativa do desempenho do método automatizado integrado desenvolvido em relação ao processo de inspeção manual tradicional, mensurando ganhos de eficácia, objetividade e escalabilidade. Para isso, foram necessárias as participações de 2 (dois) profissionais capacitados na área de fotogrametria e sensoriamento remoto em que cada um foi responsável por realizar um dos métodos de inspeção sobre a amostra selecionada de 60 fotografias aéreas brutas.

---

## Organização do Repositório

* **scripts/01_conformidade_tecnica/**: Rotinas para extração de metadados e verificação dos parâmetros técnicos. Esses scripts foram escritos para serem utilizados na caixa de ferramentas do software de SIG Qgis.
* **scripts/02_analise_visual/**: Scripts para pré-processamento, treinamento e inferência de modelos de análise visual. Esses scipts foram escritos para serem utilizados em algum ambiente de desenvolvimento através de alguma IDE. Por exemplo, nem toda sombra vai impossibilitar a fotointerpretação da imagem para a geração de cartografia de referência.

---

## Propriedade Intelectual e Citação

**Copyright (c) 2026 Eliza Silva Maia - PPEC/UFBA**

Este código é parte integrante da pesquisa de mestrado intitulada:
"Framework Automatizado e Integrado para o Controle de Qualidade de Fotografias Aéreas Brutas: validação da conformidade técnica e detecção de anomalias visuais." 

Todos os direitos reservados. O uso, reprodução ou distribuição deste material sem autorização prévia é proibido. Para fins acadêmicos, cite a obra original (**colocar citação pra obra**).
