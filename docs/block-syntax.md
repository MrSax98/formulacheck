# `check` block reference

A `check` block is a fenced code block whose info string is `check`, with a YAML mapping inside.
It attaches to the **last display equation** (`$$...$$` or `\[...\]`) above it. Several blocks
can attach to the same equation. Math inside other code fences is ignored.

````markdown
$$ \operatorname{Var}(X) = p(1-p) $$

```check
id: var-bernoulli
kind: monte-carlo
setup:
  X: bernoulli(p)
  p: 0.3
expect: variance(X) == p*(1-p)
```
````

## Common fields

| field | required | meaning |
|---|---|---|
| `id` | yes | unique name inside the file |
| `kind` | yes | `symbolic`, `numeric` or `monte-carlo` |
| `claim` | no | free text shown in the report |
| `timeout` | no | seconds (1–120, default 20); Unix only |

Unknown fields are an error, so typos do not pass silently.

## Verdicts

| verdict | meaning |
|---|---|
| `pass` | proved (symbolic), true at every listed point (numeric), or statistically consistent (Monte Carlo) |
| `fail` | a counterexample or a statistically significant discrepancy was found |
| `inconclusive` | no counterexample, but the tool could not prove it. **Never counted as a pass** |
| `error` | the block is invalid (bad YAML, unknown name, unsafe expression, ...) |

## `kind: symbolic`

Checks `lhs == rhs` for all values of the declared symbols.

```check
id: gauss-sum
kind: symbolic
symbols: {n: natural, k: natural}
lhs: Sum(k, k, 1, n)
rhs: n*(n+1)/2
```

* `symbols`: a list of names (`[a, b]`) or a mapping name -> assumptions. Assumptions:
  `real, positive, negative, nonnegative, nonpositive, integer, natural`
  (comma separated or a list). `assume:` adds assumptions to declared symbols.
* Method: first up to 8 random points are tested (seeded; respects assumptions). Any mismatch is
  a `fail` with the counterexample. Then sympy tries `simplify(lhs - rhs) == 0` and `equals()`.
  If no counterexample exists but sympy cannot prove it, the result is `inconclusive`.
* Optional: `rtol` (default 1e-9), `seed` (default 0).
* Points where an expression is undefined (poles, branch problems) are skipped; fewer than 3
  usable points gives `inconclusive`.

Functions: `sqrt exp log sin cos tan asin acos atan sinh cosh tanh abs min max factorial binomial`
and calculus helpers `Sum(f, k, lo, hi)`, `Product(f, k, lo, hi)`, `Integral(f, x, lo, hi)`,
`Derivative(f, x)`, `Limit(f, x, point)`. Constants: `pi`, `oo`. Powers use `**` (not `^`).

## `kind: numeric`

Checks `lhs == rhs` at the points you list.

```check
id: sqrt-square
kind: numeric
lhs: sqrt(x)**2
rhs: x
points: [{x: 4}, {x: 2.5}, {x: pi/2}]
```

Optional: `rtol` (1e-9), `atol` (1e-12). Same functions as `symbolic`.

## `kind: monte-carlo`

Simulates random variables and tests an equality statistically.

```check
id: exp-mean
kind: monte-carlo
setup:
  T: exponential(lam)
  lam: 2
expect: mean(T) == 1/lam
n: 200000     # 5,000 - 5,000,000 (default 200,000)
tol: 4sigma   # 1sigma - 10sigma, or a plain number (default 4)
seed: 1       # default 1; results are repeatable
```

* `setup` maps names to numbers, expressions, or **one** distribution call. Order does not matter;
  names are resolved by dependency. Each random variable must be declared on its own line
  (`Y: X + Z`, not `Y: X + normal(0, 1)`).
* Distribution parameters must be numbers, not other random variables (no hierarchical models).
* Distributions: `bernoulli(p)`, `binomial(n, p)`, `poisson(lam)`, `geometric(p)` (support 1, 2, ...),
  `uniform(a, b)`, `normal(mu, sigma)` (sigma = standard deviation), `exponential(rate)`,
  `gamma(shape, rate)`, `beta(a, b)`, `t(df)`, `chi2(df)`.
* `expect` is a single `==` between two numbers. Statistics: `mean` (alias `E`), `variance` (`var`),
  `std`, `cov`, `corr`, `quantile(x, q)`, `prob(event)`, plus `sqrt exp log abs sin cos minimum
  maximum`.
* Events use `<, <=, >, >=`, combined with `&` (and) and `|` (or). Put each comparison in
  parentheses: `prob((X > 0) & (X < 1))`. Python reads `X > 0 & X < 1` differently, so the tool
  rejects it.
* How it decides: the claim is evaluated on 50 independent batches; the spread of `lhs - rhs`
  across batches gives a standard error. It passes if the mean difference is within `tol` standard
  errors of zero. The report prints the z-score and the smallest difference that could be
  detected. A pass is statistical evidence, not a proof.
* Claims about moments that do not exist (the mean of a Cauchy, `t(1)`, or the variance of
  `t(2)`) give meaningless results: the simulation cannot detect that the quantity is undefined.
* A result that is not a finite number (`log(0)`, division by zero) is an `error`.

## Safety

Expressions are parsed with `ast` and evaluated with a whitelist: numbers, names you declared,
`+ - * / **`, and the functions above. No attribute access, subscripts, comprehensions, lambdas,
strings, imports or `eval`. Exponents, sample sizes, expression sizes and function arguments are
bounded. YAML is loaded with a safe loader that also rejects aliases (`*name`), and a block may be
at most 20,000 characters. Time limits stop slow computations (Linux and macOS).
