"""Harvest and screen disordered experimental structures from the COD."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .open_data import CachedHTTPClient, HTTPArtifact, OpenDataError
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_COD = "https://www.crystallography.net/cod"
_USER_AGENT = "matfactory/0.2 (auditable hidden-order screening)"
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class CODHarvestProtocol:
    harvest_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    cache_dir: Path
    selected_dir: Path
    discovery_template: Path
    queries: tuple[dict[str, str], ...]
    max_downloads: int
    max_selected: int
    max_workers: int
    min_interval_seconds: float
    timeout_seconds: float
    max_retries: int
    occupancy_tolerance: float
    max_expected_ordered_atoms: int
    composition_block_absolute_atoms: float
    excluded_elements: tuple[str, ...]
    max_per_reduced_formula: int


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def load_cod_harvest_protocol(path: Path | str) -> CODHarvestProtocol:
    """Validate a courteous, bounded COD harvesting protocol."""
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("COD harvest schema_version must be '1.0'")
    harvest_id = payload.get("harvest_id")
    if not isinstance(harvest_id, str) or not _SAFE_ID.fullmatch(harvest_id):
        raise ValueError("harvest_id must be a safe lowercase identifier")
    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries must be a non-empty list")
    normalized_queries: list[dict[str, str]] = []
    for row in queries:
        if not isinstance(row, dict) or not row:
            raise TypeError("each COD query must be a non-empty object")
        normalized_queries.append({str(key): str(value) for key, value in row.items()})

    def integer(field: str, minimum: int, maximum: int) -> int:
        value = payload.get(field)
        if not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
        return value

    def positive(field: str, *, allow_zero: bool = False) -> float:
        value = payload.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{field} must be numeric")
        number = float(value)
        if (allow_zero and number < 0) or (not allow_zero and number <= 0):
            raise ValueError(f"{field} must be positive")
        return number

    max_downloads = integer("max_downloads", 1, 500)
    max_selected = integer("max_selected", 1, 100)
    if max_selected > max_downloads:
        raise ValueError("max_selected cannot exceed max_downloads")
    excluded = payload.get("excluded_elements", [])
    if not isinstance(excluded, list) or any(
        not isinstance(item, str) or not item for item in excluded
    ):
        raise ValueError("excluded_elements must be a string list")
    discovery_template = _repo_path(str(payload.get("discovery_template", "")))
    if not discovery_template.is_file():
        raise FileNotFoundError(f"discovery template not found: {discovery_template}")

    return CODHarvestProtocol(
        harvest_id=harvest_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/screening/{harvest_id}"))
        ),
        cache_dir=_repo_path(str(payload.get("cache_dir", f"cache/cod/{harvest_id}"))),
        selected_dir=_repo_path(
            str(payload.get("selected_dir", f"data/structures/candidates/{harvest_id}"))
        ),
        discovery_template=discovery_template,
        queries=tuple(normalized_queries),
        max_downloads=max_downloads,
        max_selected=max_selected,
        max_workers=integer("max_workers", 1, 4),
        min_interval_seconds=positive("min_interval_seconds", allow_zero=True),
        timeout_seconds=positive("timeout_seconds"),
        max_retries=integer("max_retries", 1, 5),
        occupancy_tolerance=positive("occupancy_tolerance"),
        max_expected_ordered_atoms=integer("max_expected_ordered_atoms", 1, 512),
        composition_block_absolute_atoms=positive("composition_block_absolute_atoms"),
        excluded_elements=tuple(sorted(set(excluded))),
        max_per_reduced_formula=integer("max_per_reduced_formula", 1, 5),
    )


def _metadata_url(query: dict[str, str]) -> str:
    params = {**query, "format": "json"}
    return f"{_COD}/result?{urllib.parse.urlencode(params)}"


def _cif_url(cod_id: str) -> str:
    if not re.fullmatch(r"\d{7}", cod_id):
        raise ValueError(f"invalid COD identifier {cod_id!r}")
    return f"{_COD}/{cod_id}.cif"


def _clean_formula(value: str) -> str:
    return re.sub(r"^\s*-\s*|\s*-\s*$", "", value).strip()


def expected_composition_from_metadata(row: dict[str, Any]) -> dict[str, float]:
    """Prefer author-declared formula times Z over rounded site arithmetic."""
    from pymatgen.core import Composition

    formula = row.get("formula")
    z_value = row.get("Z")
    if isinstance(formula, str) and formula.strip() and z_value not in {None, ""}:
        try:
            z = float(z_value)
            composition = Composition(_clean_formula(formula))
            return {
                str(element): float(amount) * z
                for element, amount in composition.get_el_amt_dict().items()
            }
        except (TypeError, ValueError):
            pass
    cell_formula = row.get("cellformula")
    if isinstance(cell_formula, str) and cell_formula.strip():
        composition = Composition(_clean_formula(cell_formula))
        return {
            str(element): float(amount)
            for element, amount in composition.get_el_amt_dict().items()
        }
    return {}


def _parse_cif(text: str, occupancy_tolerance: float) -> tuple[Any, list[str]]:
    from pymatgen.io.cif import CifParser

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parser = CifParser.from_str(text, occupancy_tolerance=occupancy_tolerance)
        structures = parser.parse_structures(primitive=False)
    if len(structures) != 1:
        raise ValueError(f"expected one structure, found {len(structures)}")
    messages = list(dict.fromkeys(str(item.message) for item in caught))
    return structures[0], messages


def _site_summary(structure: Any) -> dict[str, int]:
    disordered = 0
    mixed = 0
    vacancy = 0
    for site in structure:
        if site.is_ordered:
            continue
        disordered += 1
        if len(site.species) > 1:
            mixed += 1
        if sum(float(value) for value in site.species.values()) < 1.0 - 1e-8:
            vacancy += 1
    return {
        "n_disordered_sites": disordered,
        "n_mixed_species_sites": mixed,
        "n_vacancy_bearing_sites": vacancy,
    }


def _composition_error(
    observed: dict[str, float], expected: dict[str, float]
) -> tuple[dict[str, float], float | None]:
    if not expected:
        return {}, None
    delta = {
        element: float(observed.get(element, 0.0) - expected.get(element, 0.0))
        for element in sorted(set(observed) | set(expected))
    }
    return delta, max(abs(value) for value in delta.values())


def screen_cod_cif(
    row: dict[str, Any],
    text: str,
    protocol: CODHarvestProtocol,
) -> dict[str, Any]:
    """Classify one CIF without relaxing or changing its occupancies."""
    structure, parser_warnings = _parse_cif(text, protocol.occupancy_tolerance)
    observed = {
        str(element): float(amount)
        for element, amount in structure.composition.get_el_amt_dict().items()
    }
    expected = expected_composition_from_metadata(row)
    delta, maximum_error = _composition_error(observed, expected)
    disorder = _site_summary(structure)
    elements = sorted(observed)
    expected_atoms = sum(expected.values()) if expected else sum(observed.values())
    blockers: list[str] = []
    if disorder["n_disordered_sites"] == 0:
        blockers.append("ordered-average-structure")
    if expected_atoms > protocol.max_expected_ordered_atoms:
        blockers.append("ordered-cell-too-large")
    excluded = sorted(set(elements) & set(protocol.excluded_elements))
    if excluded:
        blockers.append("excluded-elements:" + ",".join(excluded))
    if (
        maximum_error is not None
        and maximum_error > protocol.composition_block_absolute_atoms
    ):
        blockers.append("declared-versus-site-composition-mismatch")

    from pymatgen.core import Composition

    reduced_formula = (
        Composition(expected).reduced_formula
        if expected
        else structure.composition.reduced_formula
    )
    disorder_fraction = disorder["n_disordered_sites"] / max(len(structure), 1)
    atom_efficiency = 1.0 - min(
        expected_atoms / protocol.max_expected_ordered_atoms, 1.0
    )
    score = (
        5.0 * (disorder["n_mixed_species_sites"] > 0)
        + 4.0 * (disorder["n_vacancy_bearing_sites"] > 0)
        + 2.0
        * (
            disorder["n_mixed_species_sites"] > 0
            and disorder["n_vacancy_bearing_sites"] > 0
        )
        + 3.0 * disorder_fraction
        + 4.0 * atom_efficiency
        + 1.0 * bool(row.get("doi"))
        - 0.2 * len(parser_warnings)
        - float(maximum_error or 0.0)
    )
    return {
        "cod_id": str(row.get("file")),
        "source_url": f"{_COD}/{row.get('file')}.html",
        "cif_url": _cif_url(str(row.get("file"))),
        "title": row.get("title"),
        "authors": row.get("authors"),
        "journal": row.get("journal"),
        "year": row.get("year"),
        "doi": row.get("doi"),
        "reported_formula": row.get("formula"),
        "reduced_formula": reduced_formula,
        "space_group": row.get("sg"),
        "space_group_number": row.get("sgNumber"),
        "elements": elements,
        "n_expanded_sites": len(structure),
        "average_occupied_atoms": sum(observed.values()),
        "expected_ordered_atoms": expected_atoms,
        "expected_composition_per_cell": dict(sorted(expected.items())),
        "observed_composition": dict(sorted(observed.items())),
        "composition_delta": delta,
        "maximum_composition_error_atoms": maximum_error,
        **disorder,
        "parser_warnings": parser_warnings,
        "screening_score": score,
        "blockers": blockers,
        "passes_automatic_screen": not blockers,
        "manual_novelty_review_required": True,
    }


def _fetch_cifs(
    rows: list[dict[str, Any]],
    protocol: CODHarvestProtocol,
    client: CachedHTTPClient,
) -> tuple[dict[str, HTTPArtifact], list[dict[str, str]]]:
    artifacts: dict[str, HTTPArtifact] = {}
    failures: list[dict[str, str]] = []

    def fetch(row: dict[str, Any]) -> tuple[str, HTTPArtifact]:
        cod_id = str(row["file"])
        return cod_id, client.get_text(
            _cif_url(cod_id),
            suffix=f".{cod_id}.cif",
            accept="chemical/x-cif,text/plain",
        )

    with ThreadPoolExecutor(max_workers=protocol.max_workers) as executor:
        futures = {executor.submit(fetch, row): str(row["file"]) for row in rows}
        for future in as_completed(futures):
            cod_id = futures[future]
            try:
                fetched_id, artifact = future.result()
                artifacts[fetched_id] = artifact
            except (OpenDataError, OSError, ValueError) as exc:
                failures.append(
                    {
                        "cod_id": cod_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    failures.sort(key=lambda item: item["cod_id"])
    return artifacts, failures


def _select_diverse(
    records: list[dict[str, Any]], protocol: CODHarvestProtocol
) -> list[dict[str, Any]]:
    passing = [row for row in records if row["passes_automatic_screen"]]
    passing.sort(
        key=lambda row: (
            -float(row["screening_score"]),
            float(row["expected_ordered_atoms"]),
            str(row["cod_id"]),
        )
    )
    counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for row in passing:
        formula = str(row["reduced_formula"])
        if counts.get(formula, 0) >= protocol.max_per_reduced_formula:
            continue
        counts[formula] = counts.get(formula, 0) + 1
        selected.append(row)
        if len(selected) >= protocol.max_selected:
            break
    return selected


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT))
    except ValueError:
        return str(path.resolve())


def _write_candidate_protocol(
    selected: list[dict[str, Any]], protocol: CODHarvestProtocol
) -> Path:
    payload = _read_json(protocol.discovery_template)
    payload["study_id"] = f"{protocol.harvest_id}-audit"
    payload["title"] = "COD hidden-order candidate audit"
    payload["hypothesis"] = (
        "Recent experimental Li/Na average structures with partial occupancy "
        "contain exact-composition ordered realizations that change symmetry or topology."
    )
    payload["root_dir"] = f"runs/discovery/{protocol.harvest_id}-audit"
    payload["budget"]["max_candidates"] = max(len(selected), 1)
    payload["candidates"] = []
    for row in selected:
        cif_path = protocol.selected_dir / f"cod-{row['cod_id']}.cif"
        notes = (
            f"{row.get('title') or ''} ({row.get('year') or 'year unknown'}); "
            f"automated score={row['screening_score']:.3f}; DOI={row.get('doi') or 'none'}; "
            "requires primary-paper and database novelty review before GPU work"
        )
        payload["candidates"].append(
            {
                "candidate_id": f"cod-{row['cod_id']}",
                "path": _relative_or_absolute(cif_path),
                "source_url": row["source_url"],
                "source_license": "COD public domain dedication",
                "role": "external-cod-screening-candidate",
                "eligible_for_novelty": False,
                "expected_composition_per_cell": row["expected_composition_per_cell"],
                "notes": notes,
            }
        )
    target = protocol.selected_dir / "discovery_protocol.json"
    atomic_write_json(target, payload)
    return target


def build_cod_harvest(
    path: Path | str,
    *,
    client: CachedHTTPClient | None = None,
) -> tuple[dict[str, Any], dict[str, HTTPArtifact]]:
    """Fetch metadata/CIFs, apply input gates, and rank diverse candidates."""
    protocol = load_cod_harvest_protocol(path)
    http = client or CachedHTTPClient(
        cache_dir=protocol.cache_dir,
        user_agent=_USER_AGENT,
        min_interval_seconds=protocol.min_interval_seconds,
        timeout_seconds=protocol.timeout_seconds,
        max_retries=protocol.max_retries,
    )
    metadata: dict[str, dict[str, Any]] = {}
    metadata_sources: list[dict[str, Any]] = []
    for query_index, query in enumerate(protocol.queries):
        url = _metadata_url(query)
        payload, artifact = http.get_json(url)
        if not isinstance(payload, list):
            raise TypeError(f"COD query {query_index} did not return a list")
        metadata_sources.append(
            {
                "query_index": query_index,
                "query": query,
                "url": url,
                "sha256": artifact.sha256,
                "cache_path": str(artifact.content_path),
                "from_cache": artifact.from_cache,
                "result_count": len(payload),
            }
        )
        for row in payload:
            if not isinstance(row, dict):
                continue
            cod_id = str(row.get("file") or "")
            if not re.fullmatch(r"\d{7}", cod_id):
                continue
            if row.get("duplicateof") or row.get("status"):
                continue
            metadata.setdefault(cod_id, row)

    rows = [metadata[key] for key in sorted(metadata)[: protocol.max_downloads]]
    cif_artifacts, download_failures = _fetch_cifs(rows, protocol, http)
    records: list[dict[str, Any]] = []
    parse_failures: list[dict[str, str]] = []
    for row in rows:
        cod_id = str(row["file"])
        artifact = cif_artifacts.get(cod_id)
        if artifact is None:
            continue
        try:
            screened = screen_cod_cif(row, artifact.text, protocol)
            screened["cif_sha256"] = artifact.sha256
            screened["cache_path"] = str(artifact.content_path)
            screened["from_cache"] = artifact.from_cache
            records.append(screened)
        except (TypeError, ValueError, IndexError) as exc:
            parse_failures.append(
                {
                    "cod_id": cod_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    records.sort(key=lambda item: str(item["cod_id"]))
    parse_failures.sort(key=lambda item: item["cod_id"])
    selected = _select_diverse(records, protocol)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "report_kind": "cod-hidden-order-candidate-harvest",
        "harvest_id": protocol.harvest_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "workflow_path": str(Path(__file__).resolve()),
        "workflow_sha256": sha256_file(__file__),
        "metadata_sources": metadata_sources,
        "coverage": {
            "n_unique_metadata_records": len(metadata),
            "n_downloads_planned": len(rows),
            "n_cifs_downloaded_or_cached": len(cif_artifacts),
            "n_download_failures": len(download_failures),
            "n_parse_failures": len(parse_failures),
            "n_disordered": sum(row["n_disordered_sites"] > 0 for row in records),
            "n_automatic_pass": sum(row["passes_automatic_screen"] for row in records),
            "n_selected": len(selected),
        },
        "download_failures": download_failures,
        "parse_failures": parse_failures,
        "records": records,
        "selected_cod_ids": [row["cod_id"] for row in selected],
        "selection_rules": {
            "max_selected": protocol.max_selected,
            "max_expected_ordered_atoms": protocol.max_expected_ordered_atoms,
            "composition_block_absolute_atoms": (
                protocol.composition_block_absolute_atoms
            ),
            "excluded_elements": list(protocol.excluded_elements),
            "max_per_reduced_formula": protocol.max_per_reduced_formula,
            "manual_novelty_review_required": True,
        },
        "execution": {
            "gpu_work_started": False,
            "ordering_started": False,
            "relaxation_started": False,
        },
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": "selected structures are unreviewed inputs, not discoveries",
        },
        "client_statistics": {
            "calls_made": http.calls_made,
            "cache_hits": http.cache_hits,
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    return report, cif_artifacts


def render_cod_harvest_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    selected = set(report["selected_cod_ids"])
    rows = [row for row in report["records"] if row["cod_id"] in selected]
    rows.sort(key=lambda row: -float(row["screening_score"]))
    lines = [
        "# COD hidden-order candidate harvest",
        "",
        f"Harvest: `{report['harvest_id']}`",
        "",
        (
            f"Metadata {coverage['n_unique_metadata_records']}; "
            f"CIFs {coverage['n_cifs_downloaded_or_cached']}; "
            f"disordered {coverage['n_disordered']}; "
            f"automatic pass {coverage['n_automatic_pass']}; "
            f"selected {coverage['n_selected']}."
        ),
        "",
        (
            "Selection is an input-quality screen. Every row still requires "
            "manual primary-paper and novelty review before any GPU work."
        ),
        "",
        "| COD | Formula | Atoms | Disorder | Mixed | Vacancy | Score | Paper |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        title = str(row.get("title") or "untitled").replace("|", "\\|")
        lines.append(
            f"| [{row['cod_id']}]({row['source_url']}) | {row['reduced_formula']} | "
            f"{row['expected_ordered_atoms']:.1f} | {row['n_disordered_sites']} | "
            f"{row['n_mixed_species_sites']} | {row['n_vacancy_bearing_sites']} | "
            f"{row['screening_score']:.2f} | {title} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def run_cod_harvest(path: Path | str) -> dict[str, Any]:
    """Persist selected public-domain CIFs and a disabled discovery protocol."""
    protocol = load_cod_harvest_protocol(path)
    report_path = protocol.root_dir / "harvest.json"
    markdown_path = protocol.root_dir / "harvest.md"
    if report_path.exists():
        report = _read_json(report_path)
        checks = {
            "protocol": report.get("protocol_sha256") == protocol.protocol_sha256,
            "workflow": report.get("workflow_sha256") == sha256_file(__file__),
            "markdown": markdown_path.is_file(),
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(
                f"COD harvest evidence changed ({failed}); use a new harvest_id"
            )
        return report

    report, artifacts = build_cod_harvest(protocol.protocol_path)
    selected = set(report["selected_cod_ids"])
    protocol.selected_dir.mkdir(parents=True, exist_ok=True)
    for cod_id in sorted(selected):
        artifact = artifacts[cod_id]
        atomic_write_text(protocol.selected_dir / f"cod-{cod_id}.cif", artifact.text)
    candidate_protocol = _write_candidate_protocol(
        [row for row in report["records"] if row["cod_id"] in selected], protocol
    )
    report["selected_directory"] = str(protocol.selected_dir)
    report["generated_discovery_protocol"] = str(candidate_protocol)
    unsigned = dict(report)
    unsigned.pop("report_fingerprint", None)
    report["report_fingerprint"] = fingerprint(unsigned)
    atomic_write_json(report_path, report)
    atomic_write_text(markdown_path, render_cod_harvest_markdown(report))
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_cod_harvest_protocol(args.protocol)
    if args.list_only:
        print(
            json.dumps(
                {
                    "harvest_id": protocol.harvest_id,
                    "protocol_sha256": protocol.protocol_sha256,
                    "queries": list(protocol.queries),
                    "max_downloads": protocol.max_downloads,
                    "max_selected": protocol.max_selected,
                    "max_workers": protocol.max_workers,
                    "gpu_work_started": False,
                },
                indent=2,
            )
        )
        return
    print(json.dumps(run_cod_harvest(protocol.protocol_path), indent=2))


if __name__ == "__main__":
    main()
