"""Code-first upload admission; local evidence storage is a separate concern."""
from pathlib import Path
from collections.abc import Mapping

DEFAULT_LIMITS = {"max_file_bytes": 10 * 1024 * 1024,
                  "max_total_bytes": 50 * 1024 * 1024, "max_files": 2000}
GENERATED_SUFFIXES = {".npy", ".npz", ".h5", ".hdf5", ".parquet", ".pkl", ".pickle",
                      ".pt", ".pth", ".ckpt", ".safetensors", ".traj", ".dcd", ".xtc"}
ARCHIVE_SUFFIXES = {".zip", ".gz", ".bz2", ".xz", ".7z", ".tar", ".tgz", ".zst"}
EXCLUDED_PARTS = {"cache", "caches", "__pycache__", ".cache", "checkpoints",
                  "trajectories", "intermediates", "intermediate", "raw_data", "raw-data"}


def validate_upload_sources(paths, *, repo_root, settings=None):
    """Fail before networking, not silently drop evidence or recursively unpack it.

    Compressed source trees must be unpacked and explicitly selected, so neither
    compressed arrays nor nested archives can evade the uncompressed size limits.
    This applies to new uploads; historical read-only verification is unaffected.
    """
    from paper_writing.support import SupportPackageError
    root = Path(repo_root).resolve()
    if settings is None:
        from paper_writing.registry import load_registry_settings
        settings = load_registry_settings(root) if (root/'registry/settings.yaml').exists() else {}
    policy = settings.get('support_publication', {}).get('package_policy', {})
    if not isinstance(policy, Mapping):
        raise SupportPackageError('support_publication.package_policy must be a mapping')
    limits = {k: policy.get(k, default) for k, default in DEFAULT_LIMITS.items()}
    if any(type(n) is not int or n <= 0 for n in limits.values()):
        raise SupportPackageError('Support upload limits must be positive integers')
    selected = sorted(set(Path(p).resolve() for p in paths))
    inventory = []
    for path in selected:
        if not path.is_relative_to(root) or not path.is_file():
            raise SupportPackageError('Invalid upload source: '+str(path))
        inventory.append((path.relative_to(root), path.stat().st_size))
    return _check_inventory(inventory, limits)


def _check_inventory(inventory, limits):
    from paper_writing.support import SupportPackageError
    total = 0
    errors = []
    for relative, size in inventory:
        total += size
        suffix = relative.suffix.lower()
        reason = None
        if suffix in ARCHIVE_SUFFIXES:
            reason = 'compressed payload/nested archive; select unpacked source code instead'
        elif suffix in GENERATED_SUFFIXES or set(p.lower() for p in relative.parts) & EXCLUDED_PARTS:
            reason = 'generated arrays, cache, trajectory, checkpoint or raw-data directory'
        elif size > limits['max_file_bytes']:
            reason = f"file exceeds {limits['max_file_bytes']} bytes"
        if reason:
            errors.append(f'{relative}: {reason} ({size} bytes)')
    if len(inventory) > limits['max_files']:
        errors.append(f"file count {len(inventory)} exceeds {limits['max_files']}")
    if total > limits['max_total_bytes']:
        errors.append(f"uncompressed source total {total} exceeds {limits['max_total_bytes']} bytes")
    if errors:
        raise SupportPackageError('Code-first support upload blocked: '+'; '.join(errors[:12])+
            (f'; and {len(errors)-12} further violations' if len(errors)>12 else '')+
            '. Keep generated evidence locally; include generators, parameters, dependencies, '
            'reproduction commands and small reference summaries. Cite external data versions/sources. '
            'Do not split, rename or recompress payloads to evade this check. '
            'Essential non-regenerable inputs require a separately approved policy change.')
    return {'policy': 'code_first', 'files': len(inventory), 'uncompressed_bytes': total, 'limits': limits}


def validate_upload_packages(paths, *, repo_root, settings=None):
    """Inspect actual ZIP member sizes, including legacy low-level upload plans.

    No extraction/decompression; even highly compressed generated data is rejected
    from its declared uncompressed size or member type. This is not ZIP integrity
    verification, which the canonical prepare/release workflow performs separately.
    """
    import zipfile
    from paper_writing.support import SupportPackageError
    if settings is None:
        from paper_writing.registry import load_registry_settings
        root=Path(repo_root)
        settings=load_registry_settings(root) if (root/'registry/settings.yaml').exists() else {}
    configured=settings.get('support_publication', {}).get('package_policy', {})
    if not isinstance(configured, Mapping):
        raise SupportPackageError('support_publication.package_policy must be a mapping')
    limits={k:configured.get(k,v) for k,v in DEFAULT_LIMITS.items()}
    if any(type(n) is not int or n <= 0 for n in limits.values()):
        raise SupportPackageError('Support upload limits must be positive integers')
    inventory=[]
    for path in map(Path,paths):
        if path.stat().st_size>limits['max_total_bytes']:
            raise SupportPackageError('Code-first support upload blocked: archive/file exceeds total upload limit')
        if path.suffix.lower()!='.zip':
            inventory.append((Path(path.name),path.stat().st_size));continue
        try:
            with zipfile.ZipFile(path) as archive:
                seen=set()
                for item in archive.infolist():
                    name=Path(item.filename)
                    if (name.is_absolute() or '..' in name.parts or '\\' in item.filename
                            or item.filename in seen or (item.external_attr >> 16) & 0o170000 == 0o120000):
                        raise SupportPackageError('Unsafe or duplicate supporting ZIP member')
                    seen.add(item.filename)
                    if not item.is_dir():inventory.append((name,item.file_size))
        except zipfile.BadZipFile as exc:
            raise SupportPackageError('Invalid supporting upload ZIP') from exc
    return _check_inventory(inventory,limits)
