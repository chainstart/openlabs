---
name: math-research-state-machine
description: Run a mathematics project whose resource allocation and evidence gates are selected by an OpenLabs math research-policy binding. Use when a task names the math-state-machine protocol; do not apply its stages or gates to other mathematics projects.
---

# Mathematics research state machine

Own the mathematics while obeying the project's selected allocation policy. The policy is not a
proof recipe: choose and replace questions, representations, conjectures, tools, computations,
formalizations, and proof routes according to the evidence. Its stage graph controls only resource
authorization, independent-role boundaries, durable evidence requirements, and automatic stopping.

Read the task's project config, `domain_config_path`, and workstream state. Then read the active
stage and its possible transitions with the state-machine `status` command described in
[policy-contract.md](references/policy-contract.md). Treat policy stages and observation names as
project-local configuration; never infer that another math project uses the same funnel.

During the bounded task:

- pursue the stage objective continuously while useful work fits the same epistemic role;
- preserve failed routes, exact remaining gaps, and contrary evidence;
- create the evidence file before recording an observation that cites it;
- record only the observation actually established, with its exact verdict and current role;
- request a transition only when the configured evidence expression passes;
- pause the workstream when further allocation is scientifically unjustified instead of creating
  evidence or a successor merely to keep the scheduler busy;
- stop at a configured fresh reviewer or role boundary and return a truthful result bundle.

Use the deterministic CLI for observations, transitions, validation, and pause decisions. Never
edit `stage`, `status`, `policy_digest`, observations, or transition history by hand to bypass a
gate. Project config and its policy binding are administrator-owned inputs: do not edit them inside
an attempt or invoke `rebind-policy` to enlarge the current allocation. A terminal `paper_seed` or
similarly named stage is not proof of the original problem unless
the selected policy explicitly gives that terminal stage the corresponding meaning.

The ordinary OpenLabs result contract remains authoritative. Bind supported, verified, and
refuted claims to present hash-addressed artifacts, keep bulk output in artifact staging, and let
the control plane commit the isolated attempt.
