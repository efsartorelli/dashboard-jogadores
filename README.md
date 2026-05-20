# Ranking BR - Pokemon GO

Dashboard Streamlit + Supabase para rankings de jogadores brasileiros, agora
estruturado como uma plataforma SaaS com autenticacao, perfil, curadoria manual,
limites mensais, plano premium e camada modular de pagamentos.

O visual do dashboard principal foi preservado. As novas funcionalidades ficam
em paginas autenticadas: `Dashboard`, `Perfil` e `Premium`.

## Stack

- Streamlit
- Supabase Auth
- Supabase Postgres
- Python
- Psycopg
- Plotly/Pandas

## Configuracao segura

O projeto usa uma camada centralizada em `src/config/settings.py`.

A ordem de leitura e:

1. Streamlit Secrets (`st.secrets`)
2. variaveis de ambiente
3. `.env` local carregado com `python-dotenv`

Isso permite rodar localmente com `.env` e em producao no Streamlit Cloud sem
versionar credenciais. Nunca commite `.env` ou `.streamlit/secrets.toml`.

### Local

Copie `.env.example` para `.env` e preencha os valores reais apenas no seu
ambiente local:

```txt
DATABASE_URL=
DATA_SOURCE=database
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

`DATA_SOURCE=database` e as chaves do Supabase Auth sao obrigatorios para o
fluxo SaaS. O modo `excel` continua existindo para manutencao do legado, mas a
aplicacao autenticada de producao deve usar banco.

```powershell
pip install -r requirements.txt
python -m streamlit run app.py
```

### Streamlit Cloud

No Streamlit Cloud, abra o app e va em `Settings` > `Secrets`. Cole os valores
no formato TOML abaixo, usando as suas credenciais reais:

```toml
DATABASE_URL = ""
DATA_SOURCE = "database"

SUPABASE_URL = ""
SUPABASE_ANON_KEY = ""

FREE_MONTHLY_INPUT_LIMIT = "5"
PREMIUM_MONTHLY_INPUT_LIMIT = "50"

AUTH_SESSION_REFRESH_MARGIN_SECONDS = "120"
AUTH_SESSION_VALIDATE_INTERVAL_SECONDS = "300"

PAYMENT_PROVIDER = "manual"
PAYMENT_CHECKOUT_URL = ""
PAYMENT_WEBHOOK_SECRET = ""
PAYMENT_SUCCESS_URL = ""
PAYMENT_CANCEL_URL = ""

PREMIUM_PRICE_CENTS = "1990"
PREMIUM_CURRENCY = "BRL"
```

O mesmo modelo fica em `.streamlit/secrets.toml.example`. Se criar um
`.streamlit/secrets.toml` local, mantenha-o fora do Git.

Referencias oficiais: Streamlit recomenda manter secrets fora do repositorio e
usar `st.secrets`/Secrets Management para apps Streamlit:
https://docs.streamlit.io/develop/concepts/connections/secrets-management

## Supabase

Execute no SQL Editor, nesta ordem:

```sql
-- schema base para projetos novos
-- cole database/schema.sql

-- hardening de duplicidade e indices
-- cole database/migrations/001_production_hardening.sql

-- camada SaaS: Auth, profiles, RLS, limites, pagamentos
-- cole database/migrations/002_saas_auth_premium_payments.sql

-- curadoria admin-only para bancos que ja aplicaram a 002
-- cole database/migrations/003_admin_only_curation.sql

-- nickname e localidade do perfil
-- cole database/migrations/004_user_profile_landing_location.sql
```

Depois importe o Excel legado, se necessario:

```powershell
python -c "from src.services.import_excel_to_db import import_excel_to_db; print(import_excel_to_db())"
```

### Roles

Novos usuarios entram como `jogador`. Para liberar curadoria, ajuste no banco:

```sql
update usuarios set role = 'admin' where email = 'seu-email@dominio.com';
```

### Auth, SMTP e Resend

No Supabase, configure `Authentication` > `URL Configuration` com a URL final
do Streamlit Cloud e os redirect URLs usados pelo app. Para envio de email de
confirmacao/recuperacao, configure `Authentication` > `SMTP Settings` com o seu
provedor. Se usar Resend, crie a API key no Resend e cole somente no painel de
SMTP/Auth do Supabase ou em um secret externo apropriado. Nao coloque chaves de
SMTP/Resend no codigo nem no Git.

## Fluxo da aplicacao

1. Usuario cria conta ou entra via Supabase Auth.
2. Streamlit valida/renova o token e cria/atualiza o profile em `usuarios`.
3. `Dashboard` carrega apenas dados globais validados.
4. `Perfil` mostra dados da conta, nickname, localidade, limite mensal, historico e envio de inputs.
5. Envios entram como `pendente`, vinculados ao `auth.users.id`.
6. Moderadores aprovam/rejeitam na aba `Curadoria` dentro do Perfil.
7. Apenas registros `validado` alimentam rankings e metricas.

## Limites e seguranca

- Free: `FREE_MONTHLY_INPUT_LIMIT=5`.
- Premium: `PREMIUM_MONTHLY_INPUT_LIMIT=50` por padrao.
- O limite e validado no Streamlit e tambem no banco por trigger.
- RLS protege profiles, inputs, pagamentos e logs.
- Usuarios comuns veem apenas o proprio historico no Perfil.
- Dados globais do dashboard usam apenas registros aprovados.
- Rate limiting de envios usa `security_events`.
- Secrets ficam em Streamlit Secrets, variaveis de ambiente ou `.env` local.

## Pagamentos

A camada esta preparada para `manual`, `cacto`, `pagseguro` e `stripe`.

Variaveis principais:

```txt
PAYMENT_PROVIDER=cacto
PAYMENT_CHECKOUT_URL=
PAYMENT_WEBHOOK_SECRET=
PAYMENT_SUCCESS_URL=
PAYMENT_CANCEL_URL=
```

Fluxo:

1. Usuario clica em `Fazer upgrade`.
2. App cria um registro em `pagamentos` com `external_reference`.
3. Usuario vai para checkout externo.
4. Provedor chama a camada `src.services.payment_webhooks.handle_payment_webhook`.
5. Webhook assinado marca pagamento como `paid`.
6. `usuarios.is_premium=true` e `premium_status='premium'`.

Em producao, exponha o handler de webhook em uma API pequena separada
(FastAPI, Supabase Edge Function ou serverless). O Streamlit nao deve receber
webhooks diretamente.

## Deploy

1. Configure os secrets no Streamlit Cloud em `Settings` > `Secrets`.
2. Aplique todas as migrations no Supabase.
3. Rode `python scripts/production_check.py`.
4. Configure o deploy apontando para `app.py`.
5. Para servidores proprios, inicie com:

```powershell
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Estrutura

```txt
app.py                       # UI Streamlit e dashboard preservado
src/auth/                    # Supabase Auth REST client e sessao
src/database/                # conexao e repositorios SQL parametrizados
src/services/                # regras de negocio, users, pagamentos, inputs
src/payments/                # adapters Cacto/PagSeguro/Stripe/manual
src/metrics/                 # metricas e rankings existentes
src/validation/              # sanitizacao e validacao dos inputs
database/migrations/         # migrations de producao
scripts/production_check.py  # checklist de deploy
```

## Testes

```powershell
python -m unittest discover -s tests
python scripts/production_check.py
```

`production_check.py` exige banco e variaveis reais para passar em modo
producao. Em desenvolvimento sem Supabase completo, use os testes unitarios.
