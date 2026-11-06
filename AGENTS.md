## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `phuclecong/template-fastapi`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles mapped 1:1 to label strings of the same name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Final step: do not auto commit or push code to git

Keep generated commit message but do not commit or push code automatically, I need to have a final review.
