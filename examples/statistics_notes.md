# Statistics notes (example with deliberate mistakes)

This file shows what `formulacheck` does. It contains correct formulas, two deliberate
mistakes, one identity the tool cannot decide, one formula without a check, and both real
and invented references. Run:

    formulacheck examples/statistics_notes.md --html report.html

## Variance of a Bernoulli variable

If $X \sim \text{Bernoulli}(p)$ then

$$
\operatorname{Var}(X) = p(1-p)
$$

```check
id: bernoulli-variance
kind: monte-carlo
claim: "Var(X) = p(1-p), with p = 0.3"
setup:
  X: bernoulli(p)
  p: 0.3
expect: variance(X) == p*(1-p)
```

## Deliberate mistake: variance of an exponential

The mean of an exponential with rate $\lambda$ is $1/\lambda$, and its variance is $1/\lambda$
(**wrong**: the variance is $1/\lambda^2$).

$$
\operatorname{Var}(T) = \frac{1}{\lambda}
$$

```check
id: exponential-variance-wrong
kind: monte-carlo
claim: "Var(T) = 1/lambda, with lambda = 2"
setup:
  T: exponential(lam)
  lam: 2
expect: variance(T) == 1/lam
```

## Algebraic identities

$$
(a+b)^2 = a^2 + 2ab + b^2
$$

```check
id: square-of-sum
kind: symbolic
symbols: [a, b]
lhs: (a+b)**2
rhs: a**2 + 2*a*b + b**2
```

Deliberate mistake: forgetting the cross term.

$$
(a+b)^2 = a^2 + b^2
$$

```check
id: square-of-sum-wrong
kind: symbolic
symbols: [a, b]
lhs: (a+b)**2
rhs: a**2 + b**2
```

## Sum of the first n integers

$$
\sum_{k=1}^{n} k = \frac{n(n+1)}{2}
$$

```check
id: gauss-sum
kind: symbolic
symbols: {n: natural, k: natural}
lhs: Sum(k, k, 1, n)
rhs: n*(n+1)/2
```

## An identity the tool cannot decide

No counterexample is found, but sympy cannot prove it: the report marks it `inconclusive`,
**not** as a pass.

$$
\tan(2x) = \frac{2\tan x}{1-\tan^2 x}
$$

```check
id: tan-double-angle
kind: symbolic
symbols: {x: real}
lhs: tan(2*x)
rhs: 2*tan(x)/(1-tan(x)**2)
```

## A formula without a check

Chebyshev's inequality states

$$
P(|X-\mu| \ge k\sigma) \le \frac{1}{k^2}
$$

and has no `check` block yet: the report lists it as not covered.

## References

- Efron, B. (1979). Bootstrap methods: another look at the jackknife. Annals of Statistics 7(1), 1-26.
- Tibshirani, R. (1996). Regression shrinkage and selection via the lasso. Journal of the Royal Statistical Society B.
- Smith, J. (2021). A nonexistent theory of sample variances. doi:10.9999/fake.12345
