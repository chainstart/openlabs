import json

from sage.all import RealBallField


precision = 160
balls = RealBallField(precision)
pi_ball = balls.pi()
lower = pi_ball.lower()
upper = pi_ball.upper()
assert lower > 3
assert upper < 4

print(
    json.dumps(
        {
            "schema_version": "openlabs.arb_certificate_output.v1",
            "status": "passed",
            "evidence_class": "certified_ball_arithmetic",
            "certificates": [
                {
                    "certificate_id": "pi-between-three-and-four",
                    "statement": "The Arb enclosure proves 3 < pi < 4.",
                    "precision_bits": precision,
                    "intervals": [
                        {
                            "quantity": "pi",
                            "lower": str(lower),
                            "upper": str(upper),
                        }
                    ],
                }
            ],
        },
        sort_keys=True,
    )
)
