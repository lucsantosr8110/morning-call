# Morning Call automático (GitHub Pages)

Preserva a tipografia, a paleta e a composição de jornal do HTML original. Gera uma edição **07:30, de segunda a sexta, fuso America/Sao_Paulo**, publica em GitHub Pages e arquiva JSON + HTML por dia.

## Publicar

1. Crie um repositório **público** vazio no GitHub, por exemplo `morning-call`.
2. Descompacte e envie **todos os arquivos e pastas**, incluindo `.github/workflows/daily.yml`, para a raiz da branch `main` do repositório.
3. Em **Settings → Pages → Build and deployment → Source**, selecione **GitHub Actions**.
4. Em **Settings → Actions → General → Workflow permissions**, habilite **Read and write permissions** (necessário para salvar o histórico por commits). Se políticas do repositório impedirem escrita, configure uma credencial de escrita ou ajuste o fluxo.
5. Em **Actions → Atualizar Morning Call → Run workflow**, faça a primeira execução manual. Abra a URL indicada em **Settings → Pages**; o endereço costuma ser `https://SEU_USUARIO.github.io/morning-call/`.
6. A execução ocorrerá a cada dia útil às **07h30 em Brasília**. Agendamentos do GitHub podem atrasar ou ser cancelados sob carga; monitore falhas em Actions. Em repositórios públicos, agendamentos podem ser desativados após 60 dias sem atividade.

## Pré-visualização no computador

```powershell
cd C:\caminho\para\morning-call-auto
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe src\generate.py --demo
start .\site\preview.html
```

`--demo` gera dados **fictícios explicitamente rotulados no terminal** apenas para testar visual; não gera `index.html` e não deve ser publicado. `--preview` consulta feeds e cotações reais e pode produzir página incompleta. `python src/generate.py` é o modo de publicação: **falha e preserva a edição anterior** se não houver ao menos três cotações válidas e uma notícia válida.

## Dados e restrições

- **Cotações:** Yahoo Finance Chart API, endpoint **não oficial**, com potencial de 429, bloqueio ou mudanças. Valores datados; não são garantia de tempo real nem de precisão institucional. Rejeita zero, infinito, observação com mais de 5 dias, timestamp futuro e variações superiores a 35%. Se indisponível, mostra `Indisponível`, sem reaproveitar números falsamente como atuais.
- **Notícias:** RSS Google Notícias (agregador; interpretado com XML da biblioteca padrão), pesquisa direcionada; mantém apenas itens com HTTPS, data dentro de 30 horas e título válido. A página mantém hyperlink da notícia e veículo, não inventa resumo, explicação causal ou sentimento. **Links do Google Notícias podem redirecionar ao veículo**. O Google RSS pode mudar e não é API contratual.
- **Agenda:** `config/events.json` começa vazia, intencionalmente. Para adicionar evento confirmado, use `[{"datetime":"2026-10-14T09:00:00-03:00","region":"BR","title":"Nome do evento","relevance":"Alta","source_url":"https://site-oficial.gov.br/evento"}]`. Ajuste data e fonte para evento real; entradas sem HTTPS e fuso são ignoradas. Não são inventados eventos.
- **Histórico:** `archive/YYYY-MM-DD.json` (base de dados auditável), `site/editions/YYYY-MM-DD.html` (consulta histórica). `site/index.html` é a última edição válida; máximo de 60 edições mostradas no menu, mas arquivos anteriores permanecem no repositório.
- **IA:** esta versão deliberadamente **não gera interpretações por IA**: manchetes são mantidas com fonte, e impactos aparecem como não validados, para evitar afirmações financeiras sem lastro. Integração posterior requer busca no conteúdo primário, checagem de evidências e revisão.

## Operação e diagnóstico

- Acesse `site/status.json` no repositório ou `/status.json` no site para conferir última execução bem-sucedida.
- Em caso de falha, examine os logs de `Actions` (falha de provedor, ausência de manchetes, qualidade insuficiente). O workflow não sobrescreve a última edição válida se a validação falhar.
- Para não depender do serviço não oficial de cotações, substitua a função `get_quotes` por provedor contratado (licença de redistribuição necessária se o jornal for público).
- Não altere `site/index.html` manualmente: ele é gerado. Edite `templates/index.html.j2` e `templates/style.css`.

## Segurança e limitações

Nenhum segredo é necessário. Não armazene tokens ou credenciais no repositório. Execução em Actions exige permissão de escrita e Pages; cuide da proteção da branch se ativá-la. O agendamento é de melhor esforço, não um SLA. O projeto não valida o conteúdo completo das matérias: somente título, URL e data do feed. Dados de mercado e notícias devem ser reconfirmados nas fontes antes de decisões financeiras.
