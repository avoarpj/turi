# Bandeiras de localidades

`assets/localidades/<UF>/<codigo-IBGE>.svg` mantém a organização municipal por
estado. Bandeiras estaduais ficam em `assets/localidades/<UF>.svg` e a nacional
em `BR.svg`. A importação de `municipios_svg.zip` em 2026-10-09 preservou os bytes
SVG: 4.381 municípios, 27 estados/DF e Brasil. CE, ES e PB usam a variante v2;
o ZIP original mantém todas as variantes. A ausência de arquivo não comprova
que o município não exista; esta coleção não tem cobertura total.

Fons oferece `/assets/localidades/<codigo-IBGE>.svg` sem consultar o banco,
mapeando os dois primeiros dígitos do código de sete dígitos para a UF.
`/assets/localidades/SP.svg` e `/assets/localidades/BR.svg` usam o mesmo resolver.
O caminho físico municipal também continua acessível pela rota explícita
`/assets/localidades/SP/3550308.svg`, validando correspondência entre UF/código.
Rotas explícitas são necessárias porque o mount estático não resolve aliases e
pode ocultar handlers mais específicos se montado no mesmo prefixo.

Arquivos são servidos inline com `image/svg+xml`, cache público de um dia e os
validadores HTTP do File do Litestar. Códigos inválidos ou bandeiras ausentes
retornam 404. Não exige regenerar dados ou índice; reiniciar Fons para as rotas.
Testes HTTP cobrem URL plana, caminho por UF, estados, ausência e preservação
do mount `/assets` para outros arquivos. O ZIP não foi removido.
