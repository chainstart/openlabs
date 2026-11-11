# ailab compute backend

The ailab host is dedicated to experiments. The owner changed its allocation on
2026-11-11: “ailab基本就是拿来做实验的了，基本不设限制”. There is no
administrator-imposed aggregate CPU, RAM, swap, PID or experimental disk cap.
The worker can use all 8 logical CPUs, about 61 GiB RAM, the existing 8 GiB swap,
and the combined available space of the six independent SSDs `/data/ssd1` through
`/data/ssd6` (about 5.45 TiB when the pool was registered). The system filesystem
is on a separate device and is excluded. Mathematical
jobs use the same policy on this host; local WSL/cc-sg mathematical limits do not
change. Jobs still declare their own CPU/memory budgets and finite wall timeout.

## Submit from cc-sg

```sh
openlabs-remote submit --source /absolute/path/to/experiment \
  --cpus 8 --memory-mib 49152 --timeout-seconds 3600 \
  -- python3 experiment.py
openlabs-remote status JOB_ID
openlabs-remote wait JOB_ID --timeout-seconds 3700
```

For storage, the default is `--storage auto`: choose the mounted experimental SSD
with most free space. To target a particular disk, add `--storage ssd1` through
`--storage ssd6` before `--`. `ssd1` and `ssd2` are NVMe; `ssd3`–`ssd6` are SATA SSDs.
No existing files are moved by pool registration. Old job identities remain pinned
to their original disk, including after reconnect; an unavailable original disk
causes a clear failure, never silent re-execution on another disk.

Each disk has `/data/ssdN/openlabs-worker/{jobs,cache,environments,datasets}`.
`OPENLABS_STORAGE_ROOT` is the selected worker root; `OPENLABS_STORAGE_ROOTS` is a
JSON object containing all six roots. `OPENLABS_SCRATCH_DIR`, `TMPDIR`, `TMP` and
`TEMP` point to the job scratch directory on the selected SSD; uv cache also uses
that SSD. Scripts may shard large datasets across the roots. The pool does not
stripe a single file across multiple filesystems.

Mount checks reject the system filesystem and unmounted SSD directories. Placement
metadata lives in the small control index under the worker home; experimental bulk
data stays on the SSDs. The remote receipt records disk id, root and filesystem UUID.

For mathematical experiments add `--task-type math`. This is a classification
label on ailab, not an 18 GiB machine limit. Admission uses the physical 8-CPU,
62961-MiB capacity, permitting multiple jobs when their declared budgets fit.
`wait` timing out does not cancel a job; its execution timeout remains authoritative.

The source directory must contain the actual script and required inputs, not the
whole campaign or home. The client snapshots it with SHA-256 and does not follow
symlinks. Obvious credential files are excluded from newly transmitted payloads.
This does not change any existing cc-sg mount or its ability to access credentials.
No login state or private SSH key is installed in the worker account.

Write outputs under the `OPENLABS_OUTPUT_DIR` environment variable. Do not hardcode
cc-sg paths in a remote script. Results, logs and a hash-bound receipt return to:

- cc-sg: `/workspace/.openlabs-remote/jobs/JOB_ID/result/`
- WSL: `~/work/projects/.openlabs-remote/jobs/JOB_ID/result/`

Copy relevant files into the attempt's artifact staging and declare their hashes in
the OpenLabs result bundle. Do not let the remote worker write the research database.
Nonzero exits, timeouts, and partial logs are retained as failures, not synthesized
successes. A transfer/reconnect reuses the job identity and existing receipt; it does
not silently re-run the same experiment. Input archives are limited to 1 GiB, and
inline result transfer to 2 GiB compressed / 4 GiB expanded; bulk data should stay on
the worker and use a separate explicit artifact transfer. These are transport limits,
not machine resource quotas.

## Experiment environments

`openlabs-worker` has no sudo, Docker-group or LXD-group membership. System compilers,
CMake, Ninja, Python, uv, Git and rootless Podman are prepared by the administrator.
The account can create environments, install dependencies, compile software, and
build/run rootless containers under its own directories without administrator rights.

```sh
uv venv --python /usr/bin/python3 /data/ssd1/openlabs-worker/environments/NAME
# Downloads use the verified domestic PyPI mirror and the direct subprocess helper.
download-direct uv pip install \
  --python /data/ssd1/openlabs-worker/environments/NAME/bin/python \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple PACKAGE==VERSION
```

Record exact versions/checksums for real experiments. Package/system-driver changes
still go through administrator maintenance. The account has no model login state;
Claude/Codex/model API calls belong in cc-sg, not on ailab.

## Transport and operations

cc-sg writes the shared file queue; it does not SSH or add a LAN route. The WSL user
service `openlabs-remote-bridge.service` alone holds a dedicated SSH key, outside the
container's project mount, and contacts the pinned ailab host key. The remote key is
restricted to the root-owned JSON/archive gateway, with no shell, PTY, port forwarding
or agent forwarding. It executes as the unprivileged worker, never as administrator.

```sh
systemctl --user status openlabs-remote-bridge.service
journalctl --user -u openlabs-remote-bridge.service -n 40
```

The service is enabled at WSL user-manager startup. The remote worker's user manager
has lingering enabled; no remote research scheduler or model client runs there.
The gateway starts per-job systemd services, while the WSL dispatcher schedules up
to eight concurrent jobs against the physical CPU/RAM inventory. Remote results never
write SQLite. `config/remote-compute.json` and the lab-runner prompt advertise this
backend to newly launched research agents, including those with global memory masked.

cc-sg keeps the existing fixed Singapore network namespace. Existing mounts,
credential access, login state and proxy chain were preserved. Only the official
optional telemetry/error-reporting opt-outs were added. These do not make a model
session anonymous or conceal prompts/tool outputs that are sent to the provider.

The original 200 GiB sparse image and prior allocation files were retained as backups,
not mounted over the live experiment directory. Do not re-run the historical initial
provisioning script: it documents the superseded 6-CPU/34-GiB policy.
