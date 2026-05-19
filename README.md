# Ranking BR - Pokemon GO

Dashboard Streamlit para acompanhar rankings de jogadores, capturas totais,
evolucao historica, medias diarias, estatisticas por estado e distribuicao por
faixas de captura.

## Como rodar em modo Excel

```powershell
pip install -r requirements.txt
streamlit run app.py
```

O app usa o arquivo `data/nofullautoinsidebuildings.xlsx` como fonte legada.
Execute os comandos a partir da raiz do projeto para que o caminho do arquivo
seja resolvido corretamente.

Tambem e possivel forcar a fonte Excel:

```powershell
$env:DATA_SOURCE="excel"
python -m streamlit run app.py
```

## Como rodar em modo banco

Configure `DATABASE_URL` com uma URL PostgreSQL/Supabase. Nao coloque essa URL
no codigo.

```powershell
$env:DATABASE_URL="postgresql://usuario:senha@host:5432/database"
$env:DATA_SOURCE="database"
python -m streamlit run app.py
```

Valores aceitos para `DATA_SOURCE`:

- `excel`: usa sempre o Excel legado.
- `database`: exige banco configurado.
- `auto`: tenta banco quando `DATABASE_URL` existe; se falhar, usa Excel.

Se `DATA_SOURCE` nao for definido, o padrao e `auto`.

## Configuracao de ambiente e secrets

O projeto le configuracoes nesta ordem:

1. variaveis de ambiente do sistema;
2. `.env` local, quando existir;
3. `st.secrets`, usado pelo Streamlit Cloud;
4. fallback seguro.

Variaveis usadas:

- `DATABASE_URL`: URL PostgreSQL/Supabase.
- `DATA_SOURCE`: `excel`, `database` ou `auto`.
- `ENABLE_ADMIN`: `true` ou `false`.
- `ADMIN_PASSWORD`: senha da area admin, obrigatoria quando `ENABLE_ADMIN=true`.

Arquivos importantes:

- `.env`: apenas local, nunca versionar.
- `.env.example`: exemplo seguro, sem senha real.
- `.streamlit/secrets.toml`: secrets locais do Streamlit, tambem ignorado pelo Git.
- `.streamlit/config.toml`: tema e opcoes seguras do Streamlit.

Exemplo seguro para `st.secrets` no Streamlit Cloud:

```toml
DATABASE_URL = "postgresql://postgres:SUA_SENHA@db.seu-projeto.supabase.co:5432/postgres"
DATA_SOURCE = "database"
ENABLE_ADMIN = "true"
ADMIN_PASSWORD = "SUA_SENHA_ADMIN_FORTE"
```

## Como preparar o banco

Execute o schema em `database/schema.sql` no PostgreSQL/Supabase.

Depois, importe o Excel legado:

```powershell
python -c "from src.services.import_excel_to_db import import_excel_to_db; print(import_excel_to_db())"
```

Esse comando usa `DATABASE_URL`, insere jogadores, insere registros historicos e
ignora duplicidades por jogador, tipo de periodo e data.

## Estrutura atual

```txt
app.py                     # camada Streamlit e componentes visuais
src/config.py              # caminhos centrais do projeto
src/data/loaders.py        # leitura e normalizacao do Excel legado
src/metrics/               # rankings, medias, estados, faixas e formatacao
src/validation/            # validacao de futuros inputs pelo site/API
src/database/              # conexao PostgreSQL e repositorios
src/services/              # fonte de dados, importacao e submissao de registros
database/schema.sql        # modelo relacional proposto para producao
docs/production-architecture.md
tests/test_metrics.py      # regressao das regras atuais
```

## Regras preservadas

- Apenas jogadores com `MOSTRAR == YES` entram no dashboard.
- O ranking geral usa a maior quantidade registrada de capturas por jogador.
- A media diaria usa todos os pares positivos de datas por jogador.
- `Apenas mensais` significa pares com ate 32 dias.
- Os filtros por nickname e estado preservam o comportamento visual atual.

## Caminho para producao

A base foi separada para permitir a proxima etapa:

1. importar o Excel para PostgreSQL;
2. receber inputs por API/site;
3. validar e auditar registros;
4. processar rankings em jobs;
5. servir o dashboard a partir de snapshots pre-calculados.

O schema inicial esta em `database/schema.sql` e a proposta de arquitetura esta
em `docs/production-architecture.md`.

## Input futuro pelo site/API

A base de servico ja existe em `src/services/submissions.py`. A funcao principal
e `submit_player_record(payload)`, que valida o payload, evita duplicidade e
salva como registro `pendente` para revisao/processamento.

## Envio publico de dados

O formulario publico fica separado do dashboard principal. Ele aparece no
sidebar como `Enviar dados` e tambem pode ser aberto com `?page=enviar-dados`.

Esse fluxo so funciona em modo banco:

```powershell
$env:DATA_SOURCE="database"
python -m streamlit run app.py
```

Campos do envio publico:

- nickname
- estado
- data do registro
- total de capturas
- observacao opcional

Todo envio publico entra obrigatoriamente como `pendente`. O jogador nao escolhe
status, nao escolhe tipo de periodo e nao consegue aprovar o proprio registro.
O tipo de periodo publico e sempre `mensal`. O servico bloqueia duplicidade
pendente ou validada para o mesmo jogador, data e tipo de periodo.

Fluxo completo:

1. jogador envia o registro em `Enviar dados`;
2. sistema salva como `pendente`;
3. admin revisa em `Admin` > `Registros pendentes`;
4. admin aprova para `validado` ou rejeita para `rejeitado`;
5. apenas registros `validado` entram no dashboard, rankings e metricas.

## Area administrativa no Streamlit

A area admin e opcional e fica escondida por padrao. Para ativar, configure no
arquivo `.env` local:

```txt
ENABLE_ADMIN=true
ADMIN_PASSWORD=uma_senha_forte
```

Nao coloque `ADMIN_PASSWORD` no Git. O arquivo `.env` ja esta no `.gitignore`.

Com o app rodando em modo banco, abra a sidebar do Streamlit e expanda `Admin`.
Digite a senha e preencha:

- nickname
- estado
- data do registro
- total de capturas
- tipo de periodo: `mensal` ou `semanal`
- status: `validado` ou `pendente`
- observacao opcional

Registros com status `validado` entram no dashboard. Registros `pendente` ficam
salvos para revisao e nao entram nos rankings atuais. O fluxo publico futuro
continua usando `pendente` por padrao.

### Revisao de pendentes

Na mesma area `Admin`, a secao `Registros pendentes` lista os envios com status
`pendente`. O admin pode:

- ver contato informado e observacao do envio;
- editar estado, data, capturas, periodo e observacao;
- aprovar, mudando o status para `validado`;
- rejeitar, mudando o status para `rejeitado`;
- fazer exclusao logica, que tambem marca como `rejeitado` e registra auditoria.

Status:

- `pendente`: salvo, aguardando revisao, nao entra no dashboard.
- `validado`: aprovado, entra nos rankings e metricas.
- `rejeitado`: recusado, mantido para historico/auditoria, nao entra no dashboard.

Toda aprovacao, rejeicao ou edicao registra auditoria em `auditoria_registros`.

## Deploy no Streamlit Cloud

1. Suba o repositorio sem `.env` e sem `.streamlit/secrets.toml`.
2. No Supabase, execute `database/schema.sql`.
3. Importe os dados legados, se necessario:

```powershell
python -c "from src.services.import_excel_to_db import import_excel_to_db; print(import_excel_to_db())"
```

4. No Streamlit Cloud, crie o app apontando para `app.py`.
5. Em `App settings` > `Secrets`, configure:

```toml
DATABASE_URL = "postgresql://postgres:SUA_SENHA@db.seu-projeto.supabase.co:5432/postgres"
DATA_SOURCE = "database"
ENABLE_ADMIN = "true"
ADMIN_PASSWORD = "SUA_SENHA_ADMIN_FORTE"
```

6. Faça o deploy.
7. Acesse o dashboard normalmente.
8. Use `Enviar dados` para submissao publica.
9. Use `Admin` para aprovar ou rejeitar registros pendentes.

Para deploy publico sem admin, use:

```toml
ENABLE_ADMIN = "false"
```

Nesse caso, os envios publicos continuam entrando como `pendente`, mas a revisao
precisa ser feita por outro ambiente com admin habilitado.

## Checklist de producao

Antes de publicar, rode:

```powershell
python -m unittest discover -s tests
python scripts/production_check.py
```

O `production_check.py` verifica:

- variaveis de ambiente principais;
- conexao com o banco;
- tabelas principais;
- quantidade de jogadores;
- quantidade de registros;
- existencia de pelo menos um registro `validado`;
- se `.env` nao esta versionado;
- se `.env.example` parece seguro.

## Testes

```powershell
python -m unittest discover -s tests
```
