# Avoar Turi

O projeto agora tem repositório próprio. Consulte o [README da raiz](../../README.md)
para setup UV, core Protobuf, SDS local, assets e comandos instalados.

Consulte [Scripts do Turi](../../docs/turi_scripts.md) para o contrato atual de
`DataScript`, descoberta automática, dependências, metadados Avro e execução
por IDs com `--no-update-venato`. O Turi gera dumps Parquet consultados
diretamente pelos consumidores; a descrição abaixo registra a motivação histórica.

> Turi ingere dados brutos e gera dumps preparados para o banco de dados do Avoar através de cruzamentos e transformações.

Este serviço substitui o `dataloaders` integrado diretamente ao Avoar (feito em Golang + funções pgsql), pois em Python existem ferramentas especializadas na transformação e análise de dados.

A "solução" `dataloaders` envolvia funções diretamente no PostgreSQL para realizar as transformações e inserir os dados, mas, este se mostrou complexa para manutenção e pouco confiável conforme novas features são desenvolvidas, então abandonei e decidi criar o Turi, um serviço isolado e especializado em **criar dumps** prontos para serem inseridos no banco de dados, feito para rodar no diretório do Avoar ou qualquer outra aplicação (não oferece webserver integrado igual o *SDS*).
