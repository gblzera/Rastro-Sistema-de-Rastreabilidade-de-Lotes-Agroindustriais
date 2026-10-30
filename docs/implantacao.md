# Implantação

Pacote 1.6.2 da EAP. O Rastro roda no plano gratuito do [Render](https://render.com), com o banco PostgreSQL no plano gratuito do [Neon](https://neon.tech). As duas contas podem ser criadas com o login do GitHub. Leva cerca de 10 minutos.

O arquivo `render.yaml` na raiz do repositório já descreve o serviço: instala as dependências, sobe a API com um único processo e, se o banco estiver vazio, popula 300 lotes sintéticos na primeira subida.

## 1. Criar o banco no Neon

1. Entre em [console.neon.tech](https://console.neon.tech) com a conta do GitHub.
2. Crie um projeto chamado `rastro`. Na região, escolha a mais próxima do Brasil que aparecer na lista.
3. Na tela do projeto, clique em **Connect** e copie a *connection string*. Ela tem este formato:

   ```
   postgresql://usuario:senha@ep-algo-123456.sa-east-1.aws.neon.tech/neondb?sslmode=require
   ```

Guarde essa string: ela contém a senha do banco e não deve ir para o repositório.

## 2. Publicar no Render

1. Entre em [dashboard.render.com](https://dashboard.render.com) com a conta do GitHub e autorize o acesso ao repositório `Rastro-Sistema-de-Rastreabilidade-de-Lotes-Agroindustriais`.
2. Clique em **New** → **Blueprint** e escolha o repositório. O Render lê o `render.yaml` e mostra o serviço `rastro`.
3. Quando ele pedir `DATABASE_URL`, cole a connection string do Neon.
4. Clique em **Apply** (ou **Deploy Blueprint**). A primeira publicação leva de 3 a 5 minutos.
5. Quando o status ficar **Live**, o endereço aparece no topo da página do serviço, no formato `https://rastro-xxxx.onrender.com`.

Abra o endereço: a interface deve mostrar 300 lotes, 12 destinos e o banco **PostgreSQL** no topo. A documentação da API fica em `/docs`.

### Sem o Neon

Se faltar tempo para criar o banco, deixe `DATABASE_URL` em branco no passo 3. A aplicação usa um SQLite temporário: funciona igual, mas os registros feitos na interface somem quando o serviço reinicia e a base volta aos 300 lotes iniciais. O topo da tela mostra **SQLite** nesse caso.

## Antes de apresentar

- No plano gratuito, o serviço dorme depois de 15 minutos sem acesso e leva cerca de 1 minuto para acordar. Abra o endereço uns 5 minutos antes da apresentação.
- O Neon também suspende o banco quando ninguém usa; a primeira consulta depois disso demora um ou dois segundos a mais.
- Tenha a versão local como plano B (ver [README](../README.md)): ela funciona sem internet.

## Atualizar a versão publicada

Cada `git push` na branch publicada dispara uma nova implantação automática no Render. Os dados no Neon continuam lá; o grafo é reconstruído a partir deles quando o serviço sobe.

Para recomeçar com a base sintética, apague as tabelas no Neon (no **SQL Editor**: `DROP TABLE arestas, vertices, eventos;`) e reinicie o serviço pelo painel do Render. Na subida, o banco vazio é populado de novo.
