import json

from sage.all import PolynomialRing, QQ


ring = PolynomialRing(QQ, "x")
x = ring.gen()
polynomial = x**4 - 1
factorization = polynomial.factor()
assert factorization.value() == polynomial
assert len(factorization) == 3

print(
    json.dumps(
        {
            "schema_version": "openlabs.sage_exact_output.v1",
            "status": "passed",
            "evidence_class": "exact_symbolic_computation",
            "claims": [
                {
                    "claim_id": "factor-x4-minus-one",
                    "statement": "x^4 - 1 has exactly three irreducible factors over Q.",
                    "exact": True,
                    "value": str(factorization),
                }
            ],
        },
        sort_keys=True,
    )
)
