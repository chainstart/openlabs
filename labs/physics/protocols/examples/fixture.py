import json
from pathlib import Path

root = Path(__file__).resolve().parent
payload = json.loads((root / "input.json").read_text(encoding="utf-8"))
result = {"speed_m_per_s": payload["distance_m"] / payload["time_s"]}
(root / "output.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
