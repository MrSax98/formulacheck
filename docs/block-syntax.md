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
| `timeout` | no | seconds (1–120, default 20) |

Unknown fields are an error, so typos do not pass silently. Numbers may be written as `0.001`
or `1e-3`.

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
* Method: first up to 8 random points are tested (seeded; respects assumptions), evaluated with
  30 significant digits. Any mismatch is a `fail` with the counterexample. Then sympy tries
  `simplify(lhs - rhs) == 0` and `equals()`. If sympy proves the identity the result is `pass`;
  if no counterexample exists but sympy cannot prove it, the result is `inconclusive`.
* Points where an expression is undefined (poles, branch problems) are skipped. If fewer than 3
  points are usable and sympy cannot prove the identity, the result is `inconclusive`.
* Numbers are exact: `1/2` is one half and `0.3` is 3/10, not floating-point approximations.
* A side that is undefined (`0*oo`, `oo - oo`, the "limit" of `sin(x)` at infinity) is an
  `error`. A side that is infinite (a divergent sum or integral) is compared exactly: `pass` only
  if both sides are the same infinity.
* Optional: `rtol` (default 1e-9), `atol` (default 1e-25, which only absorbs rounding), `seed`
  (default 0).

Functions: `sqrt exp log sin cos tan asin acos atan sinh cosh tanh abs min max factorial binomial`
and calculus helpers `Sum(f, k, lo, hi)`, `Product(f, k, lo, hi)`, `Integral(f, x, lo, hi)`,
`Derivative(f, x)`, `Limit(f, x, point)` (two-sided: an error if the left and right limits
differ), `LimitRight(f, x, point)` and `LimitLeft(f, x, point)`. The bound variable (`k`, `x`)
must be declared in `symbols`. Constants: `pi`, `oo`. Powers use `**` (not `^`).

## `kind: numeric`

Checks `lhs == rhs` at the points you list.

```check
id: sqrt-square
kind: numeric
lhs: sqrt(x)**2
rhs: x
points: [{x: 4}, {x: 2.5}, {x: pi/2}]
```

Optional: `rtol` (1e-9), `atol` (1e-25). The same elementary functions as `symbolic`; the
calculus helpers (`Sum`, `Integral`, ...) need a bound variable, so use them in a `symbolic`
check. Point values can be numbers or constant expressions such as `pi/2`.

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
  maximum`. `variance`, `std` and `cov` use the population formula (divide by n), so identities
  such as `variance(X) == mean(X**2) - mean(X)**2` hold exactly on the sample.
* Events use `<, <=, >, >=`, combined with `&` (and) and `|` (or). Put each comparison in
  parentheses: `prob((X > 0) & (X < 1))`. Python reads `X > 0 & X < 1` differently, so the tool
  rejects it.
* How it decides: both sides are estimated on the whole sample. The claim, including any
  statistic defined in `setup` (e.g. `s2: variance(X)`), is also evaluated on 50 independent
  batches, and the spread of the batch values gives the standard error. It passes if the
  whole-sample difference is within `tol` standard errors of zero. The report prints the z-score
  and the smallest difference that could be detected. A pass is statistical evidence, not a proof.
* If the value is the same in every batch, its uncertainty cannot be measured (for example a
  very rare event that never happens in the sample): the result is `inconclusive`. If the two
  sides agree to rounding error on every batch, the claim is an identity on the data and passes.
  If `setup` contains no random variable at all, the two numbers are compared exactly.
* Memory is limited: `n` times the number of `setup` entries may be at most about 30 million.
* Claims about moments that do not exist (the mean of a Cauchy, `t(1)`, or the variance of
  `t(2)`) give meaningless results: the simulation cannot detect that the quantity is undefined.
* A result that is not a finite number (`log(0)`, division by zero, overflow) is an `error`.

## Safety

Expressions are parsed with `ast` and evaluated with a whitelist: numbers, names you declared,
`+ - * / **`, and the functions above. No attribute access, subscripts, comprehensions, lambdas,
strings, imports or `eval`. Exponents (including powers of huge integers), sample sizes, memory,
expression sizes and function arguments are bounded. YAML is loaded with a safe loader that also
rejects aliases (`*name`); a block may be at most 20,000 characters (longer blocks are an error,
never silently cut). Slow computations are stopped by a time limit: in-process on Linux and
macOS, by terminating a worker process on Windows. Terminal output shows control characters
instead of executing them.
