# Bem vindo 👋
Este repositório contém logotipo de partidos políticos do Brasil, em formato SVG.<br>
Atualmente, há versões vetorizadas dos logotipos de 29 dos 30 partidos em atividade no Brasil.

*As logos e marcas pertencem aos respectivos partidos políticos.<br>
Este repositório fornece versões vetoriais para fins informativos, educacionais e de pesquisa.<br>
O uso comercial ou promocional das marcas está sujeito a autorização dos detentores.*

## Como usar?
Você pode fazer download manualmente dos arquivos do repositório para o seu projeto, ou incluir em um `submodule`/`subtree` dentro do seu projeto.

Nós recomendamos incluir como `submodule`, assim, seu repositorio não fica poluido com os arquivos + a necessidade de manualmente sincronizar com atualizações, use esse comando para delegar isso ao git:

*https*
```
git submodule add https://github.com/avoarpj/partidos-brasil-svg.git partidos-brasil-svg
```
*ssh*
```
git submodule add git@github.com:avoarpj/partidos-brasil-svg.git partidos-brasil-svg
```
O último parâmetro é o caminho de onde você quer que o nosso repositório seja incluído, o git criará pastas automaticamente.<br><br>
Lembrando:<br>
Ao usar este repositório como *git submodule*, os arquivos não são copiados para o seu repositório remoto, apenas uma referência a um commit específico.
Se você trabalha em equipe, utilize `git clone --recursive` ou execute `git submodule update --init`.

## Padronização dos nomes
Para cada partido, há uma pasta com o seu acrônimo em caixa alta, dentro dela ficam os arquivos `*.svg`, seguindo os padrões:
- `acronym.svg` - Logotipo principal do partido, geralmente utilizado em campanha ou materiais oficiais
- `acronym_typo.svg` - Logotipo com a "marca" do partido, geralmente é o símbolo ou variações da logo utilizadas em redes sociais (ex: logotipo vertical do Partido Novo ou a onça do Partido Missão).

Futuramente, adicionarei variações com temas escuros, que serão criadas com o sufixo `dark`. O padrão é sempre tema claro.

# Contribuições
Maioria dos vetores foram gerados a partir de softwares especializados (pois a maioria dos partidos não oferecem seus logotipos já vetorizados), portanto, podem haver diferenças sutis.

Especificamente para o Partido Novo (`NOVO/novo_typo.svg`), criei a versão typo do logotipo manualmente seguindo o manual de identidade visual do partido.

Se você é um artista, ou possui versões melhores, variações novas, qualquer logotipo para qualquer partido, considere abrir um PR. Caso o partido não exista ainda, crie a pasta dele de acordo com o padrão dos nomes.

\* Não esqueça de avisar no PR se o seu SVG foi comprimido ou não. Para PRs que não mencionarem compressão do SVG, farei compressão antes de aceitar, pois  os vetores aqui são focados no uso final.