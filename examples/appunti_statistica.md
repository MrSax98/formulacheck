# Appunti di statistica (esempio con errori voluti)

Questo file mostra come funziona `formulacheck`. Contiene formule corrette,
due errori inseriti di proposito, un caso non decidibile, una formula senza test
e citazioni vere e inventate.

## Varianza di una Bernoulli

Se $X \sim \text{Bernoulli}(p)$ allora

$$
\operatorname{Var}(X) = p(1-p)
$$

```check
id: var-bernoulli
kind: monte-carlo
claim: "Var(X) = p(1-p), con p = 0.3"
setup:
  X: bernoulli(p)
  p: 0.3
expect: variance(X) == p*(1-p)
```

## Errore voluto: varianza dell'esponenziale

La media di una esponenziale di parametro $\lambda$ è $1/\lambda$ e la varianza è $1/\lambda$
(**sbagliato**: la varianza è $1/\lambda^2$).

$$
\operatorname{Var}(T) = \frac{1}{\lambda}
$$

```check
id: var-exp-sbagliata
kind: monte-carlo
claim: "Var(T) = 1/lambda, con lambda = 2"
setup:
  T: exponential(lam)
  lam: 2
expect: variance(T) == 1/lam
```

## Identità algebriche

$$
(a+b)^2 = a^2 + 2ab + b^2
$$

```check
id: quadrato-binomio
kind: symbolic
symbols: [a, b]
lhs: (a+b)**2
rhs: a**2 + 2*a*b + b**2
```

Errore voluto: dimenticare il doppio prodotto.

$$
(a+b)^2 = a^2 + b^2
$$

```check
id: quadrato-binomio-sbagliato
kind: symbolic
symbols: [a, b]
lhs: (a+b)**2
rhs: a**2 + b**2
```

## Somma dei primi n interi

$$
\sum_{k=1}^{n} k = \frac{n(n+1)}{2}
$$

```check
id: somma-gauss
kind: symbolic
symbols: {n: natural, k: natural}
lhs: Sum(k, k, 1, n)
rhs: n*(n+1)/2
```

## Caso non decidibile

Il test numerico non trova controesempi, ma sympy non riesce a dimostrare l'identità:
il report la segna come `inconclusive` e **non** come superata.

$$
\tan(2x) = \frac{2\tan x}{1-\tan^2 x}
$$

```check
id: tangente-doppio-angolo
kind: symbolic
symbols: {x: real}
lhs: tan(2*x)
rhs: 2*tan(x)/(1-tan(x)**2)
```

## Una formula senza test

La disuguaglianza di Chebyshev afferma

$$
P(|X-\mu| \ge k\sigma) \le \frac{1}{k^2}
$$

e non ha ancora un blocco `check`: il report la segnala come non coperta.

## Riferimenti

- Efron, B. (1979). Bootstrap methods: another look at the jackknife. Annals of Statistics 7(1), 1-26.
- Tibshirani, R. (1996). Regression shrinkage and selection via the lasso. Journal of the Royal Statistical Society B.
- Rossi, M. (2021). Una teoria inesistente delle varianze campionarie. doi:10.9999/fake.12345
