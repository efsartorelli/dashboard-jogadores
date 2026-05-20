# Arquitetura de produção

Este projeto começou como um dashboard Streamlit baseado em Excel. A nova base
separa regras de negócio em módulos puros para permitir a evolução para banco,
API, jobs assíncronos e cache sem redesenhar a interface.

## Fluxo recomendado

1. O usuario entra pelo Supabase Auth.
2. O app cria ou atualiza `usuarios`, vinculado a `auth.users`.
3. O usuario envia dados pelo Perfil.
4. O backend valida nickname, periodo, data, capturas, rate limit e limite mensal.
5. O registro entra em `registros_periodicos` como `pendente`.
6. Moderadores revisam manualmente; aprovados viram `validado`, rejeitados ficam no historico.
7. Um job futuro marca jogadores alterados e recalcula snapshots afetados.
8. O dashboard consulta dados validados/snapshots e carrega series detalhadas sob demanda.

## Camada SaaS

- `usuarios`: profile, role, status premium e limite mensal.
- `usuarios.nickname`, `usuarios.pais`, `usuarios.estado` e `usuarios.cidade`
  identificam o jogador e a localidade usada nos envios.
- `security_events`: rate limiting, antiflood e trilha de eventos sensiveis.
- `pagamentos`: checkout externo, referencia idempotente, status e payload bruto.
- `payment_webhook_logs`: logs idempotentes de webhooks assinados.
- RLS protege dados pessoais, pagamentos, historico de inputs e escrita de curadoria.
- A curadoria administrativa fica restrita a `role = 'admin'`.
- Triggers impedem que usuarios comuns alterem `role`, `is_premium` ou limite mensal.
- Trigger de insert em `registros_periodicos` bloqueia bypass do limite mensal no banco.

## Pagamentos

O Streamlit inicia o checkout e grava `pagamentos.external_reference`. A confirmacao
deve chegar por um endpoint separado chamando
`src.services.payment_webhooks.handle_payment_webhook(provider, raw_body, headers)`.
Esse handler valida assinatura HMAC, evita duplicidade por `provider/event_id`,
marca pagamentos pagos e ativa `usuarios.is_premium`.

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
- `registros_periodicos (jogador_id, periodo_tipo, data_referencia)` unico parcial
  para `status IN ('pendente', 'validado')`
- `ranking_itens (snapshot_id, posicao)`
- `jogadores (mostrar, ativo)`
- `jogadores (state)`

## Estratégia de escala

O cálculo atual de média diária é mantido em `src.metrics.averages`, mas deve
rodar em background quando houver muitos dados. Para dezenas de milhares de
jogadores, o dashboard não deve recalcular rankings durante o carregamento da
página; ele deve ler tabelas materializadas ou snapshots.
