# ailab compute backend

The ailab host is dedicated to experiments. The owner changed its allocation on
2026-11-11: “ailab基本就是拿来做实验的了，基本不设限制”. There is no
administrator-imposed aggregate CPU, RAM, swap, PID or experimental disk cap.
Since its 2026-11-20 CPU upgrade (i7-14700K) the worker can use all 28 logical CPUs
(`config/remote-compute.json`: `cpu_threads` and `max_concurrent_jobs` 28; was 8),
about 61 GiB RAM, the existing 8 GiB swap,
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
label on ailab, not an 18 GiB machine limit. Admission uses the physical 28-thread,
62961-MiB capacity, permitting multiple jobs when their declared budgets fit. One topic
still holds at most `[program] campaign_compute_threads` (8) queued + running threads,
so a single job declares at most 8.
`wait` timing out does not cancel a job; its execution timeout remains authoritative.

## Waiting from an autonomous task (2026-11-14)

A factory agent must not hold its process open on `wait` for more than a few
minutes. On 2026-11-13 eight astronomy topics queued 14 four-CPU jobs behind two
running ones; their agents spent 4-hour task windows polling, and one campaign then
ran 61 lead-model replans whose only conclusion was "wait for job 9fe82e22".
Instead the agent ends its attempt with `"status": "awaiting_remote"` and
`"awaiting_remote": {"job_ids": [...], "resume_objective": "..."}`. The orchestrator
(`orchestrator/src/openlabs/remote_wait.py`) commits the staged state, creates the
continuation in task status `awaiting_remote` (never claimed, no Agent seconds, no
attempt, no replan or direction decision), reads each job's `status.json` once per
tick, and releases the continuation into the same Agent session when every job is
`succeeded`, `failed`, withdrawn (`WITHDRAWN*` marker) or missing, with the states
prepended to its objective. A wait expires at the longest declared job timeout plus
24 h (or the agent's `max_wait_seconds`), extended while a job runs, at most 7 days;
it is released once with a note, and a second yield on the same jobs stops the topic
for a human. A `needs_replan` result that names a still queued/running job is parked
the same way. The topic's 28-day calendar deadline is unaffected.

## Per-topic queue limit (2026-11-18)

An agent seat's environment carries `OPENLABS_CAMPAIGN_ID` and `OPENLABS_TASK_ID`
(set by the lab runner); `submit` records them in `jobs/JOB_ID/submitter.json`, beside
`request.json` (which is unchanged, so the bridge and the ailab gateway are not
affected; a job moved to the local queue keeps its tag). An owner seat also carries
`OPENLABS_CAMPAIGN_COMPUTE_THREADS` (`[program].campaign_compute_threads`, default 8):
before writing anything, `submit` sums the CPU threads declared by the topic's queued
(READY, not withdrawn) and running jobs in both queues and refuses a job that would go
past the limit, with exit code 4 and a message naming the jobs, the limit and what to do
(wait for them or end the seat `awaiting_remote`, then submit the next batch). A topic
with nothing in the queues may always submit one job. Sessions without the topic
variable are not limited.

## Listing and withdrawing jobs (2026-11-19)

Before the limit, owners had queued about 22 ailab jobs (about 96 declared threads against
8), mostly without `submitter.json`. The user approved on 2026-11-19 that owners clean up
their own over-limit queue ("同意负责人处理").

```sh
openlabs-remote list [--mine | --campaign ID] [--json]
openlabs-remote withdraw JOB_ID [JOB_ID ...] [--reason TEXT] [--any-topic]
```

`list` shows the queued (READY, not withdrawn) and running jobs of both queues with
threads, memory, creation time, source (local source directory, or the first entry of an
ailab payload) and topic. The topic comes from `submitter.json`; an untagged older job is
attributed (`BY` column) by `source_path` (a local source, a moved job's origin or the
command names the campaign workspace or its `attempt-workspaces/<token>` directory) or by
`workspace_mention` (the job id appears in text files, at most 256 KB each, of exactly one
campaign workspace under `openlabs-data/workspaces/DOMAIN/`; several campaigns make it
`ambiguous`). `OPENLABS_JOB_ATTRIBUTION_ROOTS` overrides the workspace roots. The scan
(about 4 s on cc-sg) runs only while untagged jobs exist. The per-topic limit at `submit`
and the owner brief count inferred jobs too.

`withdraw` takes back jobs that are still only queued. It refuses a job that is running,
finished, in transfer (`transport.log`), not dispatchable or already withdrawn (a running
job is not stopped), and, unless `--any-topic`, one tagged or attributed to another topic
than the caller's `OPENLABS_CAMPAIGN_ID`. Otherwise it writes `WITHDRAWN.by-submitter`
(JSON: who, when, reason, attribution), then renames `READY` to `READY.withdrawn`.
Dispatchers act only on `READY`: the bridge (`tools/remote-compute/bridge.py`) takes a job
by writing state `running` (after hashing the payload) and opening `transport.log`, and the
local dispatcher writes `running` before it starts. After 5 s `withdraw` checks again and
rolls a job back (`READY` restored, marker removed, reported "taken by the dispatcher") if
either has picked it up meanwhile. Exit code 0 means everything was withdrawn, 5 means
something was not. A waiting task (`awaiting_remote`) treats a withdrawn job as a normal
end of the wait (`withdrawn`, with the marker's who/why), never as a missing job. If a
dispatcher started the job despite a marker, the job's real state is used.

## Local overflow (2026-11-14)

ailab is preferred and should be kept full, but it is not the only place to work
(owner, 2026-11-14: "ailab 超订的话，其余的也派给本机"). `openlabs-remote submit`
routes automatically (default `--backend auto`, `orchestrator/src/openlabs/local_compute.py`
`overflow_decision`): a job goes to ailab unless ailab cannot start it now, i.e. the
declared CPUs (or memory, or job count) of its running plus dispatchable queued jobs plus
this job exceed `config/remote-compute.json`. Then it goes to the cc-sg container's
background queue `/workspace/.openlabs-local-compute/jobs/JOB_ID/` when all of these hold:

- task type `cpu` (math keeps its own rules) and default storage (no `--storage ssdN`);
- the local queue has room: at most `max_jobs` (3) jobs, `max_cpus` (8 of the container's
  15) and `max_memory_mib` (16384) declared at once, counting queued local jobs, and the
  container keeps `min_free_memory_mib` (8192) free after the job (`config/local-compute.json`;
  `OPENLABS_LOCAL_MAX_JOBS`, `_MAX_CPUS`, `_MAX_MEMORY_MIB`, `_MIN_FREE_MEMORY_MIB` override;
  `OPENLABS_COMPUTE_OVERFLOW=0` switches automatic overflow off);
- the job runs here unchanged: its scripts neither install nor download anything
  (`uv`/`pip`/`conda` installs, `download-direct`, `curl`/`wget`, `git clone`), use no
  `OPENLABS_STORAGE_ROOT` and name no absolute path this container lacks (`/data/ssdN/...`,
  `/usr/bin/time`, ...). `environment_aliases` maps a registered ailab environment to a
  container one built from the same hash lock (astronomy: `.../environments/astro-photometry`
  -> `build/lines/astro-survey-photometry/venv`); the rewrite is applied to the snapshot and
  recorded in `request.json` (`path_rewrites`) and in the receipt.

Otherwise the job queues on ailab as before; the client prints the reason on stderr and
`backend: ailab|local` on stdout. `--backend ailab` forces ailab; `--backend local` or
`bin/openlabs-local submit` queue locally explicitly. A local job never starts at
submission (the submitting agent's process tree is torn down when its attempt ends, which
killed local job 946ac0f9 on 2026-11-14); each orchestrator tick starts queued jobs detached
inside `bin/openlabs-resource-guard --task-type cpu` with `CUDA_VISIBLE_DEVICES=''`, and the
tick subtracts running local jobs' declared CPUs and memory from the capacity it gives new
agent tasks (`local_compute` in the tick report). Outputs go to `result/outputs`
(`$OPENLABS_OUTPUT_DIR`), with `result/receipt.json` (request, source and output hashes).
`openlabs-remote status/wait` and `awaiting_remote.job_ids` accept local ids. Stopping the
loop or the container stops local jobs; they are recorded as failed, not re-run.

A still-queued ailab job can be moved here under the same id with
`bin/openlabs-local adopt-ailab JOB_ID --reason TEXT`: it verifies the payload hash and the
portability rules, builds the local job, withdraws the ailab copy (`READY.withdrawn` plus
`WITHDRAWN.moved-to-local`) and re-checks that the bridge had not taken it. Lookups follow
that marker to the local copy, so waits on the id keep working. GPU work still reserves the
device explicitly through the resource guard.

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

Capacity accounting is rebuilt from the queue directory on every pass, not kept in
memory: a job whose `status.json` says `running` (READY present) may be executing on
ailab, so it always counts against `capacity` and is re-polled after a transport
failure (backoff 15 s doubling to 300 s) until it is succeeded or failed, even when
capacity is full; only new jobs wait for room. A restarted bridge therefore re-attaches
to every running job. A job still unreachable after `started + wall + 300 s` is failed
as before and gets `remote_cancel: pending`; the bridge keeps its capacity until the
gateway's `cancel` operation (`systemctl --user stop` of the job unit) succeeds, retried
once ailab answers again. Independently, each job unit has `RuntimeMaxSec = wall + 10`
on ailab, and the runner stops its process group at `wall`.

Deploy a bridge change from WSL with `tools/remote-compute/deploy-bridge.sh` (it finds
the `bridge.py` the unit runs, updates it if it is a copy, and restarts the service).
Gateway changes are installed on ailab as root into `/usr/local/lib/openlabs-remote/`.

The service is enabled at WSL user-manager startup. The remote worker's user manager
has lingering enabled; no remote research scheduler or model client runs there.
The gateway starts per-job systemd services, while the WSL dispatcher schedules
concurrent jobs against the physical CPU/RAM inventory (the container side advertises
`max_concurrent_jobs` 28 since 2026-11-20; it was eight on the earlier 8-thread host). Remote results never
write SQLite. `config/remote-compute.json` and the lab-runner prompt advertise this
backend to newly launched research agents, including those with global memory masked.

cc-sg keeps the existing fixed Singapore network namespace. Existing mounts,
credential access, login state and proxy chain were preserved. Only the official
optional telemetry/error-reporting opt-outs were added. These do not make a model
session anonymous or conceal prompts/tool outputs that are sent to the provider.

The original 200 GiB sparse image and prior allocation files were retained as backups,
not mounted over the live experiment directory. Do not re-run the historical initial
provisioning script: it documents the superseded 6-CPU/34-GiB policy.
