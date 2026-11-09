# Turi

Leia `docs/development_notes.md` antes de implementar. Use `uv add/remove`, `uv sync` e `uv run`; mantenha o lock consistente.

Preserve os produtores em `apps/turi/src`, as regras de identidade, schemas e multiplicidades. Core é uma dependência externa Protobuf: não copie contratos antigos para `avoar/core`. Venato em `avoar/infra/venato` é copiado sem alterações. SDS é executado localmente por callbacks do Downloader; não requer servidor.

Preserve espaço visual entre etapas de funções e não compacte código existente. Registre decisões e validações na memória. Não rode o ETL completo nem regenere assets para validar mudanças de código; use fixtures e smoke tests sem rede.
