# formulacheck — Specifica del progetto (v1)

Stato: **approvata** e implementata nella versione 0.1.0. Le differenze rispetto al testo
originale sono elencate nella sezione 15.

## 1. Obiettivo

Un linter da riga di comando per appunti in Markdown con LaTeX (matematica e statistica).
Controlla in modo **deterministico** due cose:

1. le formule e le proprietà dichiarate in blocchi `check` (simbolico, numerico, Monte Carlo);
2. l'esistenza e la coerenza dei metadati delle citazioni (Crossref / OpenAlex).

Produce un report HTML con un esito per ogni controllo e una metrica di copertura
(quante equazioni in display hanno un check).

**Problema.** Gli appunti scritti o rivisti con un LLM contengono formule sbagliate e
riferimenti inventati. Oggi lo studente li ricalcola a mano. Per le citazioni esistono già
molti tool; per le formule negli appunti non ne ho trovato uno dedicato
(vedi Fase 1: Math-Verify e le pipeline dei benchmark coprono solo il confronto
tra espressioni, non un flusso end-to-end su file di appunti).

## 2. Utenti e casi d'uso

- Studente STEM che usa un LLM per scrivere o rivedere compendi e vuole sapere
  quali formule reggono prima dell'esame.
- Chi mantiene appunti in Git e vuole un controllo ripetibile (stesso input, stesso esito).

Caso d'uso tipico: `formulacheck appunti/ --html report.html`.

## 3. Ambito

**Dentro (MVP):**
- parsing di file `.md` e blocchi ```` ```check ```` in YAML;
- tre tipi di verifica: `symbolic`, `numeric`, `monte-carlo`;
- controllo citazioni: DOI, arXiv id, voci in una sezione "Riferimenti" / file `.bib`;
- report HTML autonomo (senza JavaScript esterno) e riepilogo a terminale;
- codice di uscita utilizzabile in script e CI.

**Fuori (non-obiettivi):**
- tradurre automaticamente LaTeX in test (il blocco lo scrive l'utente o un LLM *fuori* dal tool);
- verificare che una fonte *sostenga* l'affermazione (richiede un LLM, darebbe falsi verdetti);
- dimostrare teoremi o controllare derivazioni passo-passo;
- controllo di carte Anki, file `.tex`, interfaccia web (roadmap).

## 4. Formato dei blocchi `check`

Il blocco si **attacca all'ultima equazione in display** (`$$...$$`) che lo precede.
Il report mostra fianco a fianco la formula originale e il test, per la revisione umana.

```check
id: var-bernoulli
kind: monte-carlo        # symbolic | numeric | monte-carlo
claim: "Var(X) = p(1-p)" # testo libero, solo per il report
setup:
  X: bernoulli(p)
  p: 0.3
expect: variance(X) == p*(1-p)
n: 200000                # opzionale
tol: 4sigma              # opzionale (default 4sigma)
seed: 1                  # opzionale (default fisso)
```

Campi per tipo:

| kind | campi obbligatori | esito |
|---|---|---|
| `symbolic` | `lhs`, `rhs`, `symbols` (+ `assume` opz.) | `pass` se `simplify(lhs-rhs)==0`; se non decidibile, prova controllo numerico e restituisce `inconclusive` (non `pass`) |
| `numeric` | `lhs`, `rhs`, `points` (valori di prova), `rtol` opz. | `pass`/`fail` sui punti dati, con controesempio |
| `monte-carlo` | `setup`, `expect` | `pass` se la differenza sta entro `tol` errori standard |

**Esiti:** `pass`, `fail` (con controesempio o z-score), `inconclusive`
(non si può decidere: mai trattato come successo), `error` (blocco non valido).

## 5. Sicurezza: linguaggio di espressioni limitato

- Le espressioni (`lhs`, `rhs`, `expect`, `setup`) non passano da `eval`/`parse_expr`.
  Un parser basato su `ast` con **whitelist** di nodi e nomi; niente attributi, import,
  comprehension, accessi a file o rete.
- Whitelist di funzioni: `sqrt, exp, log, sin, cos, abs, sum, binomial, factorial, …`
  e statistiche `mean, variance, std, cov, corr, quantile, prob`.
- Distribuzioni ammesse: `bernoulli, binomial, poisson, geometric, uniform, normal,
  exponential, gamma, beta, t, chi2`.
- Limiti: tetto a `n`, timeout per `simplify` (processo separato), dimensione massima del blocco.
- Un file `.md` ostile non deve poter eseguire codice: questo è un requisito con test dedicati.

## 6. Citazioni

- Estrae DOI, arXiv id e voci da una sezione "Riferimenti"/"Bibliografia" o da un `.bib` indicato.
- Interroga Crossref e OpenAlex; confronta **titolo** (somiglianza con soglia),
  **cognome del primo autore** e **anno**.
- Esiti: `verified`, `mismatch` (esiste ma i metadati non coincidono), `not-found`, `unparseable`.
- Cache su disco, modalità `--offline`. Nessun indirizzo email inviato di default:
  il `mailto` per il pool "educato" di Crossref è opzionale, via variabile d'ambiente.
- Limite dichiarato: non dice se la fonte sostiene l'affermazione.

## 7. Stack e architettura

- Python ≥ 3.11. Dipendenze: `sympy`, `numpy`, `PyYAML`, `markdown-it-py`, `httpx`, `jinja2`.
  CLI con `argparse` (nessuna dipendenza in più). Strumenti di sviluppo: `pytest`, `ruff`, `mypy`.
- Niente Docker (non serve), niente servizi esterni oltre alle API di Crossref/OpenAlex.
- Moduli: `parser` (Markdown → equazioni e blocchi), `expr` (parser sicuro),
  `checks` (symbolic/numeric/monte_carlo), `citations`, `report` (HTML + terminale), `cli`.

Struttura:

```
formulacheck/
  src/formulacheck/{parser,expr,citations,report,cli}.py  + checks/
  tests/            (fixture con formule vere, false e malevole)
  examples/         (appunti dimostrativi con errori voluti)
  docs/             (sintassi dei blocchi, come far scrivere i check a un LLM)
  .github/workflows/ci.yml
  pyproject.toml  README.md  LICENSE (MIT)  .env.example  CHANGELOG.md
```

`.env.example` contiene solo variabili opzionali (es. `FORMULACHECK_MAILTO`); nessun segreto richiesto.

## 8. Tolleranza statistica (Monte Carlo)

Seme fisso (riproducibile), `n` predefinito 200 000, soglia predefinita 4σ calcolata
dall'errore standard campionario. Il report mostra lo z-score effettivo. Un `pass` Monte Carlo
è **evidenza statistica, non una dimostrazione**; il report lo dichiara.

## 9. Test e qualità

- Unit test su ogni tipo di check, sul parser sicuro e sulle citazioni (risposte HTTP registrate,
  nessuna rete in CI).
- Test di mutazione sui check: ogni formula corretta della fixture, resa errata di proposito,
  deve produrre `fail`.
- Test di sicurezza: blocchi con `__import__`, accessi ad attributi, `n` enorme, `simplify` patologico.
- Linting `ruff`, type checking `mypy`, CI GitHub Actions (Linux e macOS, Python 3.11–3.13).
- Prova end-to-end su `examples/` con esito atteso confrontato.

## 10. Limiti noti (da dichiarare nel README)

- Il blocco `check` può contenere lo stesso errore della formula, soprattutto se scritto da un LLM:
  per questo il report mostra formula e test affiancati e la copertura è una metrica separata.
- Verifica solo ciò che è dichiarato in un blocco; il resto è "non coperto".
- Le citazioni di libri e dispense senza DOI possono risultare `not-found`.

## 11. Pubblicazione

Repository GitHub **pubblica**, licenza **MIT**, README in **inglese** (esempi anche in italiano).
Nome: `formulacheck` (libero su PyPI al momento del controllo). La repo viene creata solo
dopo l'approvazione di questa specifica e con le integrazioni GitHub effettivamente disponibili
(oggi il server GitHub richiede autorizzazione; in alternativa `gh` da terminale, da verificare).

## 12. Roadmap

- v0.2: audit di carte Anki contro la pagina sorgente; file `.tex`.
- v0.3: hook pre-commit e GitHub Action pronta; prompt/skill per far scrivere i check a un LLM.
- Poi: verdetti per passi di derivazione.

## 13. Criteri di accettazione dell'MVP

1. `formulacheck examples/ --html out.html` produce un report con esiti attesi
   (formule vere → `pass`, formule volutamente errate → `fail`, non decidibili → `inconclusive`).
2. Tutti i test passano; `ruff` e `mypy` senza errori; CI verde.
3. I test di sicurezza non permettono esecuzione di codice dal `.md`.
4. README: installazione, uso, sintassi dei blocchi, limiti.
5. Installazione pulita da zero in un ambiente virtuale, verificata.

## 14. Registro delle decisioni

| Decisione | Scelta | Motivo |
|---|---|---|
| Idea | Verificatore di formule | Gap non coperto; uso diretto per l'autore |
| Ambito | Formule + citazioni | Scelto dall'utente |
| Traduzione LaTeX → test | Blocchi `check` espliciti | Verdetto deterministico, nessuna API key |
| Tipi di verifica | Simbolico, numerico, Monte Carlo | Scelto dall'utente |
| Sintassi | YAML dichiarativo | Facile da generare e validare |
| Esecuzione | Espressioni limitate (ast whitelist) | `.md` generati da LLM non fidati |
| Citazioni | Esistenza + metadati coerenti | Il "supporto all'affermazione" richiede un LLM |
| Interfaccia | CLI + report HTML | Scelto dall'utente |
| Pubblicazione | Pubblica, MIT, README inglese | Scelto dall'utente |
| Nome | `formulacheck` | Scelto dall'utente |

## 15. Differenze emerse in fase di implementazione

| Punto della specifica | Implementazione | Motivo |
|---|---|---|
| §7 `markdown-it-py` per il parsing | Scanner a righe interno | Servono solo equazioni in display e blocchi recintati: una dipendenza in meno |
| §5 timeout in un processo separato | `SIGALRM` nel processo su Linux/macOS; processo worker terminabile su Windows (o con `FORMULACHECK_ISOLATE=1`) | Più veloce dove possibile, ma utilizzabile ovunque |
| §6 quattro esiti per le citazioni | Aggiunto `unchecked` (offline o errore di rete) | Un errore di rete non deve mai diventare `not-found` |
| §5 funzione `sum` | `Sum(f, k, a, b)`, più `Product`, `Integral`, `Derivative`, `Limit` | Nomi coerenti con sympy |
| §9 risposte HTTP registrate | Risposte simulate con `httpx.MockTransport` | Test deterministici e senza rete |
| — | Loader YAML senza alias, blocchi di al massimo 20.000 caratteri | Emerso dalla revisione: gli alias YAML possono generare strutture enormi |
| — | Le cartelle nascoste e di dipendenze (`.venv`, `node_modules`, ...) non vengono analizzate | `formulacheck .` deve funzionare anche in un progetto reale |
| §11 pubblicazione | Aggiunti GitHub Action, hook pre-commit, `python -m formulacheck`, workflow di rilascio su PyPI con trusted publishing, CI anche su Windows | Richiesta: facile da usare e da trovare per chiunque |
