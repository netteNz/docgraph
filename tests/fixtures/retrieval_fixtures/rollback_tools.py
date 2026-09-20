"""
Deployment pipeline utility grab-bag.

This module accumulates small helpers used across the model deployment
pipeline: generic timestamping, config loading, path normalization, retry
plumbing, and (near the bottom, since nobody reorganizes this file) the
rollback guide generator an operator reaches for when a promoted model
needs to be rolled back to a previous checkpoint.
"""
import json
import os
import time


def utc_now():
    """Return the current UTC time as an ISO-8601 string.

    Generic helper reused all over the deployment codebase purely for log
    timestamps. Carries no rollback-specific meaning whatsoever — it is
    called from a dozen unrelated call sites, none of which have anything
    to do with promotion or rollback.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_pipeline_config(path):
    """Load a JSON pipeline configuration file from disk.

    Used by the deploy CLI to read cluster settings, resource limits, and
    unrelated scheduling parameters. Nothing here concerns model promotion
    or rollback state; it is pure generic config plumbing.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize_artifact_path(base_dir, relative_path):
    """Join and normalize a base directory with a relative artifact path.

    A small filesystem convenience used throughout the pipeline for build
    artifacts, log directories, and cache locations. Purely mechanical path
    arithmetic with no domain meaning attached.
    """
    return os.path.normpath(os.path.join(base_dir, relative_path))


def retry_with_backoff(fn, attempts=3, base_delay=0.1):
    """Call fn(), retrying up to `attempts` times with exponential backoff.

    Generic retry wrapper used by network calls, disk writes, and queue
    polling elsewhere in the pipeline. Unrelated to any specific pipeline
    stage — it is infrastructure glue, not business logic.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, generic retry helper
            last_exc = exc
            time.sleep(base_delay * (2 ** attempt))
    raise last_exc


def compute_checksum(data: bytes) -> str:
    """Compute a stable checksum for arbitrary artifact bytes.

    Used to verify build artifacts and cache entries haven't been corrupted
    in transit. Generic integrity helper, unrelated to promotion tracking.
    """
    import hashlib
    return hashlib.sha256(data).hexdigest()


def merge_dicts(base, override):
    """Shallow-merge two dictionaries, override wins on key collision.

    Generic utility used for merging default config with user overrides
    across many unrelated subsystems in this pipeline.
    """
    merged = dict(base)
    merged.update(override)
    return merged


def parse_duration(text: str) -> float:
    """Parse a duration string like '5m' or '30s' into seconds.

    Used by scheduling code for job timeouts and polling intervals. Purely
    a string-parsing utility with no relation to model lifecycle events.
    """
    units = {"s": 1.0, "m": 60.0, "h": 3600.0}
    if text[-1] in units:
        return float(text[:-1]) * units[text[-1]]
    return float(text)


def ensure_directory(path: str) -> None:
    """Create a directory (and parents) if it does not already exist.

    Generic filesystem bootstrap helper called before writing any artifact,
    log file, or cache entry anywhere in the pipeline.
    """
    os.makedirs(path, exist_ok=True)


def flatten_list(nested):
    """Flatten one level of nesting in a list of lists.

    Small collection utility used when combining batch results from
    parallel workers elsewhere in the pipeline. No domain meaning.
    """
    out = []
    for item in nested:
        out.extend(item)
    return out


def truncate_log_line(line: str, max_len: int = 500) -> str:
    """Truncate an overly long log line for display purposes.

    Cosmetic logging helper, used identically for every subsystem's log
    output regardless of what stage of the pipeline produced it.
    """
    if len(line) > max_len:
        return line[: max_len - 3] + "..."
    return line


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean feature flag from an environment variable.

    Generic environment-driven feature toggle helper, used for dozens of
    unrelated experimental flags across the codebase.
    """
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def clamp(value, low, high):
    """Clamp a numeric value into the inclusive [low, high] range.

    Generic numeric utility used across metrics collection and resource
    scaling code. No relation to model promotion or rollback.
    """
    return max(low, min(high, value))


def dedupe_preserve_order(items):
    """Remove duplicates from a sequence while preserving first-seen order.

    Generic collection utility used when merging tag lists and label sets
    from unrelated parts of the pipeline configuration.
    """
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def chunked(iterable, size):
    """Yield successive chunks of `size` items from `iterable`.

    Generic batching helper used by the metrics exporter and the log
    shipper, both unrelated to model promotion or rollback state.
    """
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


def slugify(text: str) -> str:
    """Turn arbitrary text into a filesystem-safe slug.

    Used for naming log files and cache directories from free-form job
    names elsewhere in the pipeline. No domain meaning.
    """
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def parse_bool_env_list(name: str) -> list[str]:
    """Parse a comma-separated environment variable into a list of strings.

    Generic env-var parsing helper reused for several unrelated
    comma-separated configuration knobs across the pipeline.
    """
    val = os.environ.get(name, "")
    return [part.strip() for part in val.split(",") if part.strip()]


def format_bytes(num_bytes: int) -> str:
    """Format a byte count as a human-readable string (KB/MB/GB).

    Cosmetic formatting helper used in log output and CLI summaries across
    many unrelated subsystems.
    """
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}PB"


def safe_int(text, default=0):
    """Parse an integer from text, falling back to a default on failure.

    Generic defensive parsing helper used when reading loosely-typed
    config values from environment variables or CLI flags.
    """
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def is_retryable_status(status_code: int) -> bool:
    """Return whether an HTTP status code should trigger a retry.

    Generic HTTP-client helper shared by every outbound network call in the
    pipeline, unrelated to any specific deployment stage.
    """
    return status_code in (408, 429, 500, 502, 503, 504)


def build_cache_key(*parts: str) -> str:
    """Join arbitrary string parts into a stable cache key.

    Generic cache-keying helper used by the artifact cache, the config
    cache, and the metrics cache — none of which relate to model
    promotion or rollback.
    """
    return ":".join(str(p) for p in parts)


def generate_rollback_guide(promoted_model: str, previous_model: str, reason: str = "") -> str:
    """Produce a step-by-step guide for rolling back a promoted model.

    This is the function an on-call operator actually needs when asked
    "how do I roll back a promoted model": given the currently promoted
    model and the previous promoted model it replaced, assemble the exact
    roll back steps so the rollback of the promoted model can be executed
    safely and verified afterward.
    """
    lines = [
        f"Rollback guide: roll back promoted model {promoted_model!r}",
        f"Restore previous promoted model: {previous_model!r}",
        "Step 1: pause traffic to the currently promoted model.",
        "Step 2: roll back the promoted model's serving configuration to "
        "point at the previous promoted model's checkpoint.",
        "Step 3: verify the rolled-back model now matches the previous "
        "promoted model's checkpoint hash.",
        "Step 4: resume traffic and monitor the rolled-back promoted model "
        "for regressions before closing out the rollback.",
    ]
    if reason:
        lines.append(f"Reason for rolling back this promoted model: {reason}")
    else:
        lines.append("Reason for rollback: not provided")
    return "\n".join(lines)
