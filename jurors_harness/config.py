"""Run configuration. Paid dispatch stays off unless authority, caps, and prices are all present."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from jurors_harness.constants import CONFIG_SCHEMA, STRATA
from jurors_harness.hashing import reject_absolute, sha256_text
from jurors_harness.io_util import read_json

STAGES = ("probe", "reader_a", "reader_b", "adjudication", "sample_label")
PROVIDERS = ("openrouter", "gemini", "scripted")


class ConfigError(ValueError):
    pass


@dataclass
class Route:
    name: str
    provider: str
    model: str
    env_key: str | None
    prompt_version: str
    prompt_path: Path
    prompt_text: str
    prompt_sha256: str
    temperature: float
    max_tokens: int
    price_in: float
    price_out: float
    worst_in_tokens: int
    timeout: float
    thinking_level: str | None = None

    def worst_usd(self, *, max_tokens: int | None = None, worst_in: int | None = None) -> float:
        incoming = self.worst_in_tokens if worst_in is None else worst_in
        outgoing = self.max_tokens if max_tokens is None else max_tokens
        return (incoming * self.price_in + outgoing * self.price_out) / 1_000_000


@dataclass
class RunConfig:
    schema: str
    run_id: str
    year: int
    witness: str
    edition: str
    release_id: str
    root: Path
    work_dir: Path
    inputs_dir: Path
    inventory: str
    census: str
    reference: str | None
    priors: str | None
    lexicon: str | None
    scripted_responses: Path | None
    fields: list[str]
    dispatch: bool
    price_ceiling: float
    concurrency: int
    acknowledge_billing_stop: str | None
    retry_unknown: bool
    total_usd: float
    stage_budgets: dict[str, float]
    sample_seed: int
    sample_allocations: dict[str, int]
    order_seed: int
    reveal_priors: bool
    export_prior_text: bool
    max_retries: int
    backoff_seconds: float
    probe_max_tokens: int
    probe_worst_in: int
    routes: dict[str, Route]
    inherited_ledgers: list[Path] = field(default_factory=list)

    def route(self, name: str) -> Route:
        if name not in self.routes:
            raise ConfigError(f"no route configured for {name}")
        return self.routes[name]


def load_config(path: Path, *, root: Path, work_override: Path | None = None) -> RunConfig:
    if not path.exists():
        raise ConfigError(f"config not found: {path.name}")
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    if raw.get("schema") != CONFIG_SCHEMA:
        raise ConfigError(f"config schema must be {CONFIG_SCHEMA}")
    root = root.resolve()
    # --work may be an absolute scratch directory. It is never copied into a manifest.
    if work_override is not None:
        work = work_override if work_override.is_absolute() else (root / work_override)
    else:
        work = _relative(root, _as_relative(raw.get("work_dir"), "work_dir"), "work_dir")
    inputs = _relative(root, _as_relative(raw.get("inputs_dir"), "inputs_dir"), "inputs_dir")
    authority = raw.get("authority") or {}
    caps = raw.get("caps") or {}
    budgets = caps.get("stages") or {}
    if set(budgets) != set(STAGES):
        raise ConfigError(f"stage budgets must be exactly {list(STAGES)}")
    total = _money(caps.get("total_usd"), "caps.total_usd")
    stage_budgets = {name: _money(budgets[name], f"caps.stages.{name}") for name in STAGES}
    if sum(stage_budgets.values()) - total > 1e-9:
        raise ConfigError("stage budgets exceed the total cap; no automatic transfer is applied")
    ceiling = _money(authority.get("price_ceiling_usd_per_call"), "authority.price_ceiling_usd_per_call")
    concurrency = int(authority.get("concurrency", 1))
    if concurrency != 1:
        raise ConfigError("concurrency greater than 1 is refused; one in-flight request is the safety default")
    retry = raw.get("retry") or {}
    max_retries = int(retry.get("max_retries", 2))
    if max_retries != 2:
        raise ConfigError("max_retries must be 2 (at most two retries after the first attempt)")
    sample = raw.get("sample") or {}
    allocations = sample.get("allocations") or {}
    if set(allocations) != set(STRATA):
        raise ConfigError(f"sample allocations must be exactly {list(STRATA)}")
    learning = raw.get("learning") or {}
    adjudication = raw.get("adjudication") or {}
    routes_raw = raw.get("routes") or {}
    for required in ("reader_a", "reader_b", "adjudication"):
        if required not in routes_raw:
            raise ConfigError(f"missing route {required}")
    routes = {
        name: _route(name, routes_raw[name], root=root, ceiling=ceiling)
        for name in ("reader_a", "reader_b", "adjudication")
    }
    providers = {route.provider for route in routes.values()}
    if "scripted" in providers and providers != {"scripted"}:
        raise ConfigError("the scripted provider cannot be mixed with a network provider")
    scripted = raw.get("scripted_responses")
    scripted_path = None if not scripted else _relative(root, _as_relative(scripted, "scripted_responses"), "scripted_responses")
    if "scripted" in providers and scripted_path is None:
        raise ConfigError("scripted routes require scripted_responses")
    inherited = []
    for item in raw.get("inherited_ledgers") or []:
        inherited.append(_relative(root, _as_relative(item, "inherited_ledgers"), "inherited_ledgers"))
    fields = list(raw.get("fields") or ["name", "occupation", "abode"])
    if not fields:
        raise ConfigError("fields must not be empty")
    return RunConfig(
        schema=CONFIG_SCHEMA,
        run_id=str(raw["run_id"]),
        year=int(raw["year"]),
        witness=str(raw["witness"]),
        edition=str(raw["edition"]),
        release_id=str(raw["release_id"]),
        root=root,
        work_dir=work,
        inputs_dir=inputs,
        inventory=str(raw.get("inventory") or "inventory.csv"),
        census=str(raw.get("census") or "census.json"),
        reference=raw.get("reference"),
        priors=raw.get("priors"),
        lexicon=raw.get("lexicon"),
        scripted_responses=scripted_path,
        fields=fields,
        dispatch=bool(authority.get("dispatch", False)),
        price_ceiling=ceiling,
        concurrency=concurrency,
        acknowledge_billing_stop=authority.get("acknowledge_billing_stop"),
        retry_unknown=bool(authority.get("retry_unknown_attempts", False)),
        total_usd=total,
        stage_budgets=stage_budgets,
        sample_seed=int(sample["seed"]),
        sample_allocations={name: int(allocations[name]) for name in STRATA},
        order_seed=int(adjudication.get("order_seed", sample["seed"])),
        reveal_priors=bool(learning.get("reveal_priors_at_adjudication", False)),
        export_prior_text=bool(learning.get("export_prior_text", False)),
        max_retries=max_retries,
        backoff_seconds=float(retry.get("backoff_seconds", 1.0)),
        probe_max_tokens=int(raw.get("probe_max_tokens", 32)),
        probe_worst_in=int(raw.get("probe_worst_input_tokens", 256)),
        routes=routes,
        inherited_ledgers=inherited,
    )


def dispatch_allowed(config: RunConfig, environ: dict[str, str] | None = None) -> tuple[bool, str]:
    """Dispatch requires the config flag, caps, prices, and an env authorization equal to the run id."""
    env = os.environ if environ is None else environ
    if not config.dispatch:
        return False, "authority.dispatch is false"
    if config.total_usd <= 0:
        return False, "total cap is missing"
    if any(value < 0 for value in config.stage_budgets.values()):
        return False, "a stage budget is negative"
    if config.price_ceiling <= 0:
        return False, "price ceiling is missing"
    authorized = env.get("JURORS_HARNESS_AUTHORIZE", "")
    if authorized != config.run_id:
        return False, "JURORS_HARNESS_AUTHORIZE does not match run_id"
    for name, route in config.routes.items():
        if route.provider == "scripted":
            continue
        if not route.env_key or not env.get(route.env_key, ""):
            return False, f"missing environment variable {route.env_key} for {name}"
    return True, "authorized"


def _route(name: str, raw: dict, *, root: Path, ceiling: float) -> Route:
    provider = raw.get("provider")
    if provider not in PROVIDERS:
        raise ConfigError(f"{name} provider must be one of {PROVIDERS}")
    model = str(raw.get("model") or "")
    if not model or any(char.isspace() for char in model):
        raise ConfigError(f"{name} model is missing")
    prompt_path = _relative(root, _as_relative(raw.get("prompt_path"), f"{name}.prompt_path"), f"{name}.prompt_path")
    if not prompt_path.exists():
        raise ConfigError(f"prompt file missing for {name}")
    text = prompt_path.read_text(encoding="utf-8")
    price_in = _money(raw.get("price_input_per_million"), f"{name}.price_input_per_million")
    price_out = _money(raw.get("price_output_per_million"), f"{name}.price_output_per_million")
    route = Route(
        name=name,
        provider=provider,
        model=model,
        env_key=raw.get("env_key"),
        prompt_version=str(raw.get("prompt_version") or prompt_path.stem),
        prompt_path=prompt_path,
        prompt_text=text,
        prompt_sha256=sha256_text(text),
        temperature=float(raw.get("temperature", 0)),
        max_tokens=int(raw["max_tokens"]),
        price_in=price_in,
        price_out=price_out,
        worst_in_tokens=int(raw["worst_input_tokens"]),
        timeout=float(raw.get("timeout_seconds", 180)),
        thinking_level=raw.get("thinking_level"),
    )
    if route.worst_usd() - ceiling > 1e-12:
        raise ConfigError(f"{name} worst-case call {route.worst_usd():.6f} exceeds the price ceiling {ceiling:.6f}")
    if provider != "scripted" and not route.env_key:
        raise ConfigError(f"{name} needs env_key naming the environment variable that holds the credential")
    return route


def _money(value: object, label: str) -> float:
    if value is None:
        raise ConfigError(f"{label} is required")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be a number") from exc
    if number < 0:
        raise ConfigError(f"{label} must be >= 0")
    return number


def _as_relative(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label} must be a relative path")
    path = Path(value)
    reject_absolute(path, label=label)
    return path


def _relative(root: Path, path: Path, label: str) -> Path:
    reject_absolute(path, label=label)
    return root / path
