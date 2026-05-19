# Arquitetura de produção

Este projeto começou como um dashboard Streamlit baseado em Excel. A nova base
separa regras de negócio em módulos puros para permitir a evolução para banco,
API, jobs assíncronos e cache sem redesenhar a interface.

## Fluxo recomendado

1. O usuário envia dados pelo site.
2. A API valida nickname, período, data e capturas.
3. O registro entra em `registros_periodicos` como `pendente` ou `validado`.
4. Um job marca jogadores alterados e recalcula snapshots afetados.
5. O dashboard consulta snapshots materializados e carrega séries detalhadas sob demanda.

## O que pré-calcular

- Ranking geral por maior captura registrada.
- Ranking de média diária preservando a regra atual de pares positivos.
- Melhor média por jogador.
- Estatísticas por estado.
- Distribuição por faixas de captura.
- Métricas do hero.

## O que calcular em tempo real

- Busca por nickname.
- Filtro por estado sobre resultados já materializados.
- Séries históricas de poucos jogadores selecionados no gráfico.
- Paginação.

## Índices críticos

- `registros_periodicos (jogador_id, data_referencia)`
- `registros_periodicos (periodo_tipo, data_referencia)`
- `ranking_itens (snapshot_id, posicao)`
- `jogadores (mostrar, ativo)`
- `jogadores (state)`

## Estratégia de escala

O cálculo atual de média diária é mantido em `src.metrics.averages`, mas deve
rodar em background quando houver muitos dados. Para dezenas de milhares de
jogadores, o dashboard não deve recalcular rankings durante o carregamento da
página; ele deve ler tabelas materializadas ou snapshots.
